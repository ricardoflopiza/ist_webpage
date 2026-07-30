# -*- coding: utf-8 -*-
"""Hallazgos consultivos (§18)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import ActionItem, Finding
from ..models.analysis import FINDING_TYPES, FS_SUGGESTED, FS_VALIDATED
from ..security.deps import Viewer, require_perm
from ..security.permissions import P_FINDING_MANAGE, P_FINDING_VALIDATE, P_FINDING_VIEW
from ..services import audit as audit_svc
from ..services import results as results_svc
from . import API_PREFIX
from .common import get_campaign

router = APIRouter(prefix=f"{API_PREFIX}/o/{{org_slug}}/findings", tags=["hallazgos"])


class FindingIn(BaseModel):
    campaign_id: str | None = None
    title: str = Field(min_length=3, max_length=250)
    ftype: str = "alerta"
    dimension_code: str | None = None
    priority: str = "media"
    quant_evidence: dict | None = None
    qual_evidence: str | None = None
    segments: list[str] | None = None
    interpretation: str | None = None
    limitations: str | None = None
    recommendation: str | None = None
    override_reason: str | None = None


class FindingUpdate(FindingIn):
    title: str | None = None
    status: str | None = None


def _dict(f: Finding, actions: int = 0) -> dict:
    return {
        "id": f.id, "title": f.title, "ftype": f.ftype, "dimension_code": f.dimension_code,
        "priority": f.priority, "status": f.status, "campaign_id": f.campaign_id,
        "quant_evidence": f.quant_evidence, "qual_evidence": f.qual_evidence,
        "segments": f.segments or [], "interpretation": f.interpretation,
        "limitations": f.limitations, "recommendation": f.recommendation,
        "is_system_generated": f.is_system_generated, "validated_at": f.validated_at,
        "override_reason": f.override_reason, "n_actions": actions, "is_demo": f.is_demo,
    }


@router.get("", summary="Hallazgos registrados")
def list_findings(viewer: Viewer = Depends(require_perm(P_FINDING_VIEW)),
                  db: Session = Depends(get_session),
                  campaign_id: str | None = None, status: str | None = None,
                  ftype: str | None = None):
    stmt = select(Finding).order_by(Finding.created_at.desc())
    if campaign_id:
        stmt = stmt.where(Finding.campaign_id == campaign_id)
    if status:
        stmt = stmt.where(Finding.status == status)
    if ftype:
        stmt = stmt.where(Finding.ftype == ftype)
    rows = db.execute(stmt).scalars().all()
    counts = {}
    for a in db.execute(select(ActionItem)).scalars():
        if a.finding_id:
            counts[a.finding_id] = counts.get(a.finding_id, 0) + 1
    return {
        "items": [_dict(f, counts.get(f.id, 0)) for f in rows],
        "total": len(rows),
        "without_action": [f.id for f in rows if not counts.get(f.id)],
    }


@router.post("", status_code=201, summary="Registrar hallazgo")
def create_finding(payload: FindingIn, viewer: Viewer = Depends(require_perm(P_FINDING_MANAGE)),
                   db: Session = Depends(get_session)):
    if payload.ftype not in FINDING_TYPES:
        raise HTTPException(status_code=422, detail=f"Tipo de hallazgo inválido: {payload.ftype}")
    f = Finding(organization_id=viewer.organization.id, status=FS_SUGGESTED,
                **payload.model_dump())
    db.add(f)
    db.commit()
    audit_svc.log_view(db, viewer, "hallazgo_creado", entity="finding", entity_id=f.id)
    return _dict(f)


@router.post("/suggest/{campaign_id}", summary="Generar hallazgos sugeridos por el sistema")
def suggest(campaign_id: str, viewer: Viewer = Depends(require_perm(P_FINDING_MANAGE)),
            db: Session = Depends(get_session)):
    """Crea borradores a partir del cálculo.

    Quedan siempre en estado `sugerido_por_sistema`: mientras no los valide una
    persona, la interfaz los muestra marcados y no entran a ningún reporte.
    """
    campaign = get_campaign(db, campaign_id)
    decision, payload = results_svc.results_for_viewer(db, campaign, viewer)
    if not decision.allowed:
        raise HTTPException(status_code=409, detail=decision.message)
    existing = {
        (f.ftype, f.dimension_code) for f in db.execute(
            select(Finding).where(Finding.campaign_id == campaign.id)
        ).scalars()
    }
    created = []
    for spec in results_svc.suggest_findings(payload):
        if (spec["ftype"], spec["dimension_code"]) in existing:
            continue
        f = Finding(organization_id=viewer.organization.id, campaign_id=campaign.id,
                    status=FS_SUGGESTED, is_system_generated=True, **spec)
        db.add(f)
        created.append(f)
    db.commit()
    return {"created": len(created), "items": [_dict(f) for f in created],
            "note": "Hallazgos sugeridos por el sistema. Requieren validación de un consultor."}


@router.patch("/{finding_id}", summary="Actualizar hallazgo")
def update_finding(finding_id: str, payload: FindingUpdate,
                   viewer: Viewer = Depends(require_perm(P_FINDING_MANAGE)),
                   db: Session = Depends(get_session)):
    f = db.get(Finding, finding_id)
    if not f:
        raise HTTPException(status_code=404, detail="Hallazgo no encontrado")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(f, k, v)
    db.commit()
    return _dict(f)


@router.post("/{finding_id}/validate", summary="Validar hallazgo")
def validate_finding(finding_id: str, viewer: Viewer = Depends(require_perm(P_FINDING_VALIDATE)),
                     db: Session = Depends(get_session)):
    f = db.get(Finding, finding_id)
    if not f:
        raise HTTPException(status_code=404, detail="Hallazgo no encontrado")
    f.status = FS_VALIDATED
    f.validated_by_id = viewer.user.id
    f.validated_at = dt.datetime.now(dt.UTC)
    f.is_system_generated = f.is_system_generated  # se conserva el origen
    db.commit()
    audit_svc.log_view(db, viewer, "hallazgo_validado", entity="finding", entity_id=f.id)
    return _dict(f)
