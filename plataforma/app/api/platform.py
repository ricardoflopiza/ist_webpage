# -*- coding: utf-8 -*-
"""Consola de plataforma: métricas de la consultora, leads y auditoría global (§5)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import (
    ActionItem,
    Lead,
    Organization,
    OrganizationMembership,
    SurveyCampaign,
    SurveyInvitation,
    SurveyResponse,
)
from ..models.action import OPEN_ACTION_STATES
from ..models.campaign import C_ACTIVE, C_ANALYSIS, C_CLOSED, C_FOLLOWUP, C_PUBLISHED
from ..models.response import R_SUBMITTED
from ..security.deps import Viewer, client_ip, platform_viewer
from ..security.permissions import P_CONSOLE_VIEW, P_LEADS_VIEW
from ..services import audit as audit_svc
from . import API_PREFIX

router = APIRouter(prefix=f"{API_PREFIX}/platform", tags=["plataforma"])

ALL = {"include_all": True}


def _visible_org_ids(db: Session, viewer: Viewer) -> list[str] | None:
    """None = todas (superadministrador). Lista = sólo las asignadas."""
    if viewer.is_superadmin:
        return None
    return [
        m.organization_id for m in db.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == viewer.user.id,
                OrganizationMembership.is_active.is_(True),
            ).execution_options(**ALL)
        ).scalars()
    ]


@router.get("/overview", summary="Indicadores del panel de la consultora")
def overview(viewer: Viewer = Depends(platform_viewer), db: Session = Depends(get_session)):
    viewer.require(P_CONSOLE_VIEW)
    org_ids = _visible_org_ids(db, viewer)

    def scope(stmt, column):
        return stmt if org_ids is None else stmt.where(column.in_(org_ids))

    orgs = db.execute(
        scope(select(Organization).where(Organization.is_active.is_(True)), Organization.id)
        .execution_options(**ALL)
    ).scalars().all()
    campaigns = db.execute(
        scope(select(SurveyCampaign), SurveyCampaign.organization_id).execution_options(**ALL)
    ).scalars().all()
    active = [c for c in campaigns if c.status == C_ACTIVE]

    invited = db.execute(
        scope(select(func.count()).select_from(SurveyInvitation), SurveyInvitation.organization_id)
        .execution_options(**ALL)
    ).scalar_one()
    submitted = db.execute(
        scope(
            select(func.count()).select_from(SurveyResponse)
            .where(SurveyResponse.status == R_SUBMITTED),
            SurveyResponse.organization_id,
        ).execution_options(**ALL)
    ).scalar_one()

    items = db.execute(
        scope(select(ActionItem), ActionItem.organization_id).execution_options(**ALL)
    ).scalars().all()
    overdue = [i for i in items if i.is_overdue]

    today = dt.date.today()
    closing_soon = [
        c for c in active
        if c.ends_on and 0 <= (c.ends_on - today).days <= 7
    ]
    pulses = [c for c in campaigns if c.is_pulse and c.status in (C_ACTIVE, "programada")]

    per_org = []
    for o in orgs:
        o_campaigns = [c for c in campaigns if c.organization_id == o.id]
        o_active = [c for c in o_campaigns if c.status == C_ACTIVE]
        o_invited = sum(c.invited_count for c in o_active)
        o_submitted = db.execute(
            select(func.count()).select_from(SurveyResponse).where(
                SurveyResponse.organization_id == o.id,
                SurveyResponse.status == R_SUBMITTED,
                SurveyResponse.campaign_id.in_([c.id for c in o_active] or [""]),
            ).execution_options(**ALL)
        ).scalar_one()
        o_items = [i for i in items if i.organization_id == o.id]
        per_org.append({
            "slug": o.slug, "name": o.name, "sector": o.sector, "plan": o.plan,
            "is_demo": o.is_demo,
            "campaigns": len(o_campaigns), "active_campaigns": len(o_active),
            "participation": round(o_submitted / o_invited * 100, 1) if o_invited else None,
            "open_actions": len([i for i in o_items if i.status in OPEN_ACTION_STATES]),
            "overdue_actions": len([i for i in o_items if i.is_overdue]),
            "has_action_plan": bool(o_items),
            "stage": _funnel_stage(o_campaigns),
        })

    return {
        "organizations_active": len(orgs),
        "campaigns_active": len(active),
        "people_invited": invited,
        "responses_received": submitted,
        "average_participation": round(submitted / invited * 100, 1) if invited else None,
        "closing_soon": [{"slug": _slug(orgs, c), "name": c.name,
                          "ends_on": c.ends_on.isoformat() if c.ends_on else None}
                         for c in closing_soon],
        "overdue_actions": len(overdue),
        "scheduled_pulses": len(pulses),
        "low_participation": [o for o in per_org
                              if o["participation"] is not None and o["participation"] < 50],
        "without_action_plan": [o for o in per_org if not o["has_action_plan"]],
        "organizations": per_org,
        "funnel": _funnel(per_org),
        "note": "Los indicadores comerciales requieren el módulo de contratos (ConsultingEngagement).",
    }


def _slug(orgs, campaign) -> str | None:
    return next((o.slug for o in orgs if o.id == campaign.organization_id), None)


def _funnel_stage(campaigns) -> str:
    if not campaigns:
        return "configurado"
    statuses = {c.status for c in campaigns}
    if C_FOLLOWUP in statuses:
        return "en_seguimiento"
    if C_PUBLISHED in statuses:
        return "devuelto"
    if C_ANALYSIS in statuses or C_CLOSED in statuses:
        return "analizado"
    if C_ACTIVE in statuses:
        return "en_aplicacion"
    return "configurado"


def _funnel(per_org: list[dict]) -> dict:
    stages = ["configurado", "en_aplicacion", "analizado", "devuelto", "en_seguimiento"]
    return {s: len([o for o in per_org if o["stage"] == s]) for s in stages}


@router.get("/activity", summary="Actividad reciente de la consultora")
def activity(viewer: Viewer = Depends(platform_viewer), db: Session = Depends(get_session),
             limit: int = 30):
    viewer.require(P_CONSOLE_VIEW)
    org_ids = _visible_org_ids(db, viewer)
    rows = audit_svc.recent(db, None, limit=limit * 3)
    if org_ids is not None:
        rows = [r for r in rows if r.organization_id in org_ids]
    return {"items": [
        {"action": r.action, "entity": r.entity, "actor": r.actor_email,
         "organization_id": r.organization_id, "at": r.created_at, "result": r.result}
        for r in rows[:limit]
    ]}


# ------------------------------------------------------------------ leads públicos
class LeadIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    organization: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=120)
    email: EmailStr
    size_bucket: str | None = Field(default=None, max_length=60)
    need: str | None = Field(default=None, max_length=120)
    message: str | None = Field(default=None, max_length=4000)


@router.post("/leads", status_code=201, summary="Solicitud de contacto (formulario público)")
def create_lead(payload: LeadIn, request: Request, db: Session = Depends(get_session)):
    """Endpoint público. Protegido con rate limiting por IP (§26)."""
    from ..security.sessions import is_locked, record_fail

    ip = client_ip(request)
    if is_locked(f"lead:{ip}"):
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Demasiadas solicitudes. Intenta más tarde.")
    record_fail(f"lead:{ip}")   # cuenta cada envío: 5 en 5 minutos bloquean 15
    lead = Lead(**payload.model_dump(), source_ip=ip)
    db.add(lead)
    db.commit()
    return {"id": lead.id, "status": "recibido"}


@router.get("/leads", summary="Solicitudes recibidas")
def list_leads(viewer: Viewer = Depends(platform_viewer), db: Session = Depends(get_session)):
    viewer.require(P_LEADS_VIEW)
    rows = db.execute(
        select(Lead).order_by(Lead.created_at.desc()).limit(200).execution_options(**ALL)
    ).scalars().all()
    return {"items": [
        {"id": r.id, "name": r.name, "organization": r.organization, "role": r.role,
         "email": r.email, "size_bucket": r.size_bucket, "need": r.need,
         "message": r.message, "status": r.status, "created_at": r.created_at}
        for r in rows
    ]}
