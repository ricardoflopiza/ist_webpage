# -*- coding: utf-8 -*-
"""Campañas, invitaciones, participación y pulsos (§9, §20)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import (
    EmployeePopulation,
    OrgUnit,
    PulseSurvey,
    SurveyCampaign,
    SurveyInvitation,
    SurveyTemplateVersion,
)
from ..models.campaign import (
    C_ACTIVE,
    CAMPAIGN_STATES,
    INV_PENDING,
    INV_RESPONDED,
    INV_SENT,
    INV_STARTED,
)
from ..models.survey import VERSION_PUBLISHED
from ..security.deps import Viewer, require_perm
from ..security.permissions import (
    P_CAMPAIGN_CLOSE,
    P_CAMPAIGN_MANAGE,
    P_CAMPAIGN_PUBLISH,
    P_CAMPAIGN_VIEW,
    P_INVITATION_MANAGE,
    P_PARTICIPATION_VIEW,
    P_PULSE_MANAGE,
)
from ..services import audit as audit_svc
from ..services import campaigns as svc
from ..services import results as results_svc
from ..services.anonymity import effective_threshold, suppress_small_groups
from . import API_PREFIX
from .common import get_campaign

router = APIRouter(prefix=f"{API_PREFIX}/o/{{org_slug}}/campaigns", tags=["campañas"])


class CampaignIn(BaseModel):
    version_id: str
    name: str = Field(min_length=2, max_length=200)
    period_label: str | None = None
    starts_on: dt.date | None = None
    ends_on: dt.date | None = None
    access_method: str = "enlace_token"
    population_filter: dict | None = None
    segmentation_keys: list[str] | None = None
    anonymity_threshold: int | None = Field(default=None, ge=3, le=50)
    min_item_completion: float | None = Field(default=None, ge=0.1, le=1.0)
    consent_text: str | None = None
    welcome_text: str | None = None
    closing_text: str | None = None
    invitation_subject: str | None = None
    invitation_body: str | None = None
    inclusive_language: bool = True
    is_pulse: bool = False
    baseline_campaign_id: str | None = None
    notes: str | None = None


class CampaignUpdate(CampaignIn):
    version_id: str | None = None
    name: str | None = None


class StatusIn(BaseModel):
    status: str


class PulseIn(BaseModel):
    campaign_id: str
    baseline_campaign_id: str | None = None
    dimension_code: str | None = None
    finding_id: str | None = None
    action_plan_id: str | None = None
    org_unit_id: str | None = None
    cadence: str | None = None
    scheduled_for: dt.date | None = None
    notes: str | None = None


def _dict(c: SurveyCampaign) -> dict:
    return {
        "id": c.id, "name": c.name, "status": c.status, "period_label": c.period_label,
        "version_id": c.version_id, "is_pulse": c.is_pulse, "is_demo": c.is_demo,
        "starts_on": c.starts_on, "ends_on": c.ends_on, "closed_at": c.closed_at,
        "access_method": c.access_method, "invited_count": c.invited_count,
        "segmentation_keys": c.segmentation_keys or [],
        "anonymity_threshold": c.anonymity_threshold,
        "results_published_at": c.results_published_at,
        "baseline_campaign_id": c.baseline_campaign_id,
    }


@router.get("", summary="Campañas de la organización")
def list_campaigns(viewer: Viewer = Depends(require_perm(P_CAMPAIGN_VIEW)),
                   db: Session = Depends(get_session), status: str | None = None):
    stmt = select(SurveyCampaign).order_by(SurveyCampaign.created_at.desc())
    if status:
        stmt = stmt.where(SurveyCampaign.status == status)
    rows = db.execute(stmt).scalars().all()
    return {"items": [_dict(c) for c in rows], "total": len(rows)}


@router.post("", status_code=201, summary="Crear campaña")
def create_campaign(payload: CampaignIn, viewer: Viewer = Depends(require_perm(P_CAMPAIGN_MANAGE)),
                    db: Session = Depends(get_session)):
    version = db.get(SurveyTemplateVersion, payload.version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Versión de instrumento no encontrada")
    if version.status != VERSION_PUBLISHED:
        raise HTTPException(
            status_code=409,
            detail="Sólo se puede aplicar una versión publicada: garantiza que el "
                   "instrumento no cambie durante el levantamiento.",
        )
    threshold_min = viewer.organization.anonymity_threshold
    if payload.anonymity_threshold and payload.anonymity_threshold < threshold_min:
        raise HTTPException(
            status_code=422,
            detail=f"El umbral de la campaña no puede ser menor que el de la organización ({threshold_min}).",
        )
    campaign = SurveyCampaign(organization_id=viewer.organization.id, **payload.model_dump())
    db.add(campaign)
    db.commit()
    audit_svc.log_view(db, viewer, "campania_creada", entity="survey_campaign", entity_id=campaign.id)
    return _dict(campaign)


@router.get("/{campaign_id}", summary="Detalle de campaña")
def get_one(campaign_id: str, viewer: Viewer = Depends(require_perm(P_CAMPAIGN_VIEW)),
            db: Session = Depends(get_session)):
    c = get_campaign(db, campaign_id)
    data = _dict(c)
    data["participation"] = results_svc.participation(db, c)
    data["effective_threshold"] = effective_threshold(viewer.organization, c)
    return data


@router.patch("/{campaign_id}", summary="Actualizar campaña (sólo antes de activarla)")
def update_campaign(campaign_id: str, payload: CampaignUpdate,
                    viewer: Viewer = Depends(require_perm(P_CAMPAIGN_MANAGE)),
                    db: Session = Depends(get_session)):
    c = get_campaign(db, campaign_id)
    if c.status not in ("borrador", "en_revision", "programada"):
        raise HTTPException(status_code=409, detail="La campaña ya no admite cambios de configuración")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(c, k, v)
    db.commit()
    return _dict(c)


@router.post("/{campaign_id}/status", summary="Cambiar estado de la campaña")
def change_status(campaign_id: str, payload: StatusIn,
                  viewer: Viewer = Depends(require_perm(P_CAMPAIGN_PUBLISH)),
                  db: Session = Depends(get_session)):
    c = get_campaign(db, campaign_id)
    if payload.status not in CAMPAIGN_STATES:
        raise HTTPException(status_code=422, detail="Estado desconocido")
    if payload.status == "cerrada":
        viewer.require(P_CAMPAIGN_CLOSE)
        svc.close_and_mark(db, c)
    else:
        svc.transition(db, c, payload.status)
    audit_svc.log_view(db, viewer, "campania_estado", entity="survey_campaign",
                       entity_id=c.id, detail={"estado": c.status})
    return _dict(c)


@router.post("/{campaign_id}/invitations", summary="Generar invitaciones")
def generate(campaign_id: str, viewer: Viewer = Depends(require_perm(P_INVITATION_MANAGE)),
             db: Session = Depends(get_session)):
    c = get_campaign(db, campaign_id)
    created = svc.generate_invitations(db, c)
    audit_svc.log_view(db, viewer, "invitaciones_generadas", entity="survey_campaign",
                       entity_id=c.id, detail={"creadas": len(created)})
    # Los enlaces se devuelven una única vez: el token no vuelve a estar disponible.
    return {
        "created": len(created), "invited_total": c.invited_count,
        "links": [{"invitation_id": inv.id, "url": svc.invitation_link(tok)}
                  for inv, tok in created],
        "note": ("Los enlaces sólo se muestran ahora: en la base queda únicamente el "
                 "hash del token. Guárdalos o envíalos antes de cerrar esta respuesta."),
    }


@router.post("/{campaign_id}/invitations/mark-sent", summary="Marcar invitaciones como enviadas")
def mark_sent(campaign_id: str, viewer: Viewer = Depends(require_perm(P_INVITATION_MANAGE)),
              db: Session = Depends(get_session)):
    c = get_campaign(db, campaign_id)
    n = svc.mark_sent(db, c)
    return {"marked": n}


@router.get("/{campaign_id}/participation", summary="Seguimiento de participación (§6)")
def participation(campaign_id: str, viewer: Viewer = Depends(require_perm(P_PARTICIPATION_VIEW)),
                  db: Session = Depends(get_session)):
    """La participación se puede seguir con la campaña abierta; los resultados no.

    El detalle por unidad respeta el umbral: saber que en un equipo de 4 personas
    respondieron 4 ya es información sensible cuando se cruza con los resultados.
    """
    c = get_campaign(db, campaign_id)
    base = results_svc.participation(db, c)
    threshold = effective_threshold(viewer.organization, c)

    invitations = db.execute(
        select(SurveyInvitation).where(SurveyInvitation.campaign_id == c.id)
    ).scalars().all()
    by_status = {}
    for i in invitations:
        by_status[i.status] = by_status.get(i.status, 0) + 1

    units = db.execute(select(OrgUnit).where(OrgUnit.is_active.is_(True))).scalars().all()
    rows = []
    for u in units:
        n = db.query(SurveyInvitation).join(
            EmployeePopulation, SurveyInvitation.employee_id == EmployeePopulation.id
        ).filter(
            SurveyInvitation.campaign_id == c.id,
            EmployeePopulation.org_unit_id == u.id,
        ).count()
        responded = len(results_svc.load_responses(db, c, {"org_unit_id": u.id}))
        rows.append({"key": u.id, "label": u.name, "kind": u.kind, "invited": n,
                     "n": responded, "rate": round(responded / n * 100, 1) if n else None})
    rows = suppress_small_groups(rows, threshold)

    return {**base, "threshold": threshold, "by_invitation_status": {
        "pendiente": by_status.get(INV_PENDING, 0), "enviada": by_status.get(INV_SENT, 0),
        "iniciada": by_status.get(INV_STARTED, 0), "respondida": by_status.get(INV_RESPONDED, 0),
    }, "by_unit": rows}


@router.get("/{campaign_id}/access", summary="Datos de acceso público a la encuesta")
def access(campaign_id: str, viewer: Viewer = Depends(require_perm(P_INVITATION_MANAGE)),
           db: Session = Depends(get_session)):
    from ..config import settings

    c = get_campaign(db, campaign_id)
    code = svc.ensure_access_code(db, c)
    return {
        "access_method": c.access_method,
        "access_code": code or None,
        "public_url": f"{settings.public_base_url}/e/codigo/{code}" if code else None,
        "status": c.status,
        "open": c.status == C_ACTIVE,
    }


# ------------------------------------------------------------------ pulsos
pulse_router = APIRouter(prefix=f"{API_PREFIX}/o/{{org_slug}}/pulses", tags=["pulsos"])


@pulse_router.get("", summary="Pulsos configurados")
def list_pulses(viewer: Viewer = Depends(require_perm(P_CAMPAIGN_VIEW)),
                db: Session = Depends(get_session)):
    rows = db.execute(select(PulseSurvey)).scalars().all()
    out = []
    for p in rows:
        c = db.get(SurveyCampaign, p.campaign_id)
        out.append({
            "id": p.id, "campaign_id": p.campaign_id, "campaign": c.name if c else None,
            "status": c.status if c else None, "dimension_code": p.dimension_code,
            "cadence": p.cadence, "scheduled_for": p.scheduled_for,
            "baseline_campaign_id": p.baseline_campaign_id,
            "finding_id": p.finding_id, "action_plan_id": p.action_plan_id,
            "org_unit_id": p.org_unit_id, "notes": p.notes,
        })
    return {"items": out, "total": len(out)}


@pulse_router.post("", status_code=201, summary="Crear pulso")
def create_pulse(payload: PulseIn, viewer: Viewer = Depends(require_perm(P_PULSE_MANAGE)),
                 db: Session = Depends(get_session)):
    c = get_campaign(db, payload.campaign_id)
    if not c.is_pulse:
        raise HTTPException(status_code=422, detail="La campaña asociada debe estar marcada como pulso")
    p = PulseSurvey(organization_id=viewer.organization.id, **payload.model_dump())
    db.add(p)
    db.commit()
    return {"id": p.id}


@pulse_router.get("/{pulse_id}/comparison", summary="Pulso versus línea base")
def pulse_comparison(pulse_id: str, viewer: Viewer = Depends(require_perm(P_CAMPAIGN_VIEW)),
                     db: Session = Depends(get_session)):
    """Compara sólo las dimensiones presentes en ambas mediciones.

    Un pulso no es un diagnóstico: con menos ítems y menos participación, sirve
    para ver dirección de cambio, no para reemplazar la medición integral.
    """
    p = db.get(PulseSurvey, pulse_id)
    if not p:
        raise HTTPException(status_code=404, detail="Pulso no encontrado")
    campaign = get_campaign(db, p.campaign_id)
    decision, payload = results_svc.results_for_viewer(db, campaign, viewer)
    if not decision.allowed:
        return {"allowed": False, "reason": decision.reason, "message": decision.message}
    baseline = {}
    if p.baseline_campaign_id:
        base_campaign = db.get(SurveyCampaign, p.baseline_campaign_id)
        if base_campaign:
            snap = results_svc.latest_snapshot(db, base_campaign.id)
            if snap and snap.payload:
                baseline = {d["code"]: d["score"] for d in snap.payload.get("dimensions", [])}
    comparison = []
    for d in payload["dimensions"]:
        if d["code"] in baseline and d["score"] is not None:
            comparison.append({
                "code": d["code"], "name": d["name"], "pulse": d["score"],
                "baseline": baseline[d["code"]],
                "delta": round(d["score"] - baseline[d["code"]], 1),
                "n": d["n"],
            })
    return {
        "allowed": True, "campaign": campaign.name, "n": payload["n_responses"],
        "participation": payload["participation"], "comparison": comparison,
        "note": ("Un pulso mide pocos ítems con menor participación: indica dirección "
                 "de cambio, no reemplaza un diagnóstico integral."),
    }
