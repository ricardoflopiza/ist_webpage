# -*- coding: utf-8 -*-
"""Catálogo de servicios y contrataciones (§21)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import ConsultingEngagement, ConsultingService
from ..security.deps import Viewer, platform_viewer, require_perm
from ..security.permissions import P_ENGAGEMENT_MANAGE, P_ORG_VIEW, P_SERVICES_MANAGE
from . import API_PREFIX

router = APIRouter(prefix=f"{API_PREFIX}", tags=["servicios"])
ALL = {"include_all": True}


class ServiceIn(BaseModel):
    code: str = Field(min_length=2, max_length=60)
    name: str
    summary: str | None = None
    includes: list[str] | None = None
    price_clp: int | None = None       # None ⇒ "Cotizar"
    price_note: str | None = None
    family: str = "servicio"
    is_active: bool = True
    sort_order: int = 0


class EngagementIn(BaseModel):
    service_id: str | None = None
    name: str
    status: str = "propuesta"
    stage: str = "configurado"
    lead_consultant_id: str | None = None
    starts_on: dt.date | None = None
    ends_on: dt.date | None = None
    amount_clp: int | None = None
    notes: str | None = None


def _dict(s: ConsultingService) -> dict:
    return {
        "id": s.id, "code": s.code, "name": s.name, "summary": s.summary,
        "includes": s.includes or [], "price_clp": s.price_clp, "price_note": s.price_note,
        "family": s.family, "is_active": s.is_active, "sort_order": s.sort_order,
    }


@router.get("/services", summary="Catálogo de servicios (público)")
def list_services(db: Session = Depends(get_session), family: str | None = None):
    stmt = select(ConsultingService).where(
        ConsultingService.is_active.is_(True), ConsultingService.organization_id.is_(None)
    ).order_by(ConsultingService.sort_order)
    if family:
        stmt = stmt.where(ConsultingService.family == family)
    rows = db.execute(stmt.execution_options(**ALL)).scalars().all()
    return {"items": [_dict(s) for s in rows], "total": len(rows),
            "note": "Los valores sin precio se cotizan según alcance y tamaño de la organización."}


@router.post("/services", status_code=201, summary="Crear servicio")
def create_service(payload: ServiceIn, viewer: Viewer = Depends(platform_viewer),
                   db: Session = Depends(get_session)):
    viewer.require(P_SERVICES_MANAGE)
    s = ConsultingService(organization_id=None, **payload.model_dump())
    db.add(s)
    db.commit()
    return _dict(s)


@router.patch("/services/{service_id}", summary="Actualizar servicio o su precio")
def update_service(service_id: str, payload: ServiceIn,
                   viewer: Viewer = Depends(platform_viewer),
                   db: Session = Depends(get_session)):
    viewer.require(P_SERVICES_MANAGE)
    s = db.execute(
        select(ConsultingService).where(ConsultingService.id == service_id)
        .execution_options(**ALL)
    ).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(s, k, v)
    db.commit()
    return _dict(s)


@router.get("/o/{org_slug}/engagements", summary="Servicios contratados por la organización")
def list_engagements(viewer: Viewer = Depends(require_perm(P_ORG_VIEW)),
                     db: Session = Depends(get_session)):
    rows = db.execute(select(ConsultingEngagement)).scalars().all()
    return {"items": [
        {"id": e.id, "name": e.name, "status": e.status, "stage": e.stage,
         "service_id": e.service_id, "starts_on": e.starts_on, "ends_on": e.ends_on,
         "amount_clp": e.amount_clp, "notes": e.notes}
        for e in rows
    ], "total": len(rows)}


@router.post("/o/{org_slug}/engagements", status_code=201, summary="Registrar contratación")
def create_engagement(payload: EngagementIn,
                      viewer: Viewer = Depends(require_perm(P_ENGAGEMENT_MANAGE)),
                      db: Session = Depends(get_session)):
    e = ConsultingEngagement(organization_id=viewer.organization.id, **payload.model_dump())
    db.add(e)
    db.commit()
    return {"id": e.id, "name": e.name, "stage": e.stage}
