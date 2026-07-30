# -*- coding: utf-8 -*-
"""Planes de acción y compromisos (§19)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import ActionItem, ActionPlan, Finding
from ..models.action import ACTION_STATES, AI_DONE, OPEN_ACTION_STATES
from ..security.deps import Viewer, require_perm
from ..security.permissions import P_ACTION_MANAGE, P_ACTION_UPDATE, P_ACTION_VIEW
from ..services import audit as audit_svc
from . import API_PREFIX

router = APIRouter(prefix=f"{API_PREFIX}/o/{{org_slug}}/action-plans", tags=["planes de acción"])


class PlanIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    campaign_id: str | None = None
    org_unit_id: str | None = None
    owner_user_id: str | None = None
    starts_on: dt.date | None = None
    ends_on: dt.date | None = None


class ItemIn(BaseModel):
    action: str = Field(min_length=3)
    finding_id: str | None = None
    problem: str | None = None
    objective: str | None = None
    owner_user_id: str | None = None
    owner_label: str | None = None
    team: str | None = None
    org_unit_id: str | None = None
    starts_on: dt.date | None = None
    due_on: dt.date | None = None
    indicator: str | None = None
    target: str | None = None
    resources: str | None = None
    evidence: str | None = None
    risks: str | None = None
    comments: str | None = None
    priority: str = "media"
    status: str = "propuesta"
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    next_review_on: dt.date | None = None


class ItemUpdate(ItemIn):
    action: str | None = None


def _item_dict(i: ActionItem) -> dict:
    return {
        "id": i.id, "plan_id": i.plan_id, "finding_id": i.finding_id, "action": i.action,
        "problem": i.problem, "objective": i.objective, "owner_user_id": i.owner_user_id,
        "owner_label": i.owner_label, "team": i.team, "org_unit_id": i.org_unit_id,
        "starts_on": i.starts_on, "due_on": i.due_on, "indicator": i.indicator,
        "target": i.target, "resources": i.resources, "evidence": i.evidence,
        "risks": i.risks, "comments": i.comments, "priority": i.priority,
        "status": i.status, "progress": i.progress, "next_review_on": i.next_review_on,
        "is_overdue": i.is_overdue, "is_demo": i.is_demo,
    }


def _plan_dict(p: ActionPlan) -> dict:
    items = list(p.items)
    return {
        "id": p.id, "name": p.name, "description": p.description, "status": p.status,
        "campaign_id": p.campaign_id, "org_unit_id": p.org_unit_id,
        "owner_user_id": p.owner_user_id, "starts_on": p.starts_on, "ends_on": p.ends_on,
        "n_items": len(items),
        "progress": round(sum(i.progress for i in items) / len(items), 2) if items else 0.0,
        "is_demo": p.is_demo,
    }


@router.get("", summary="Planes de acción")
def list_plans(viewer: Viewer = Depends(require_perm(P_ACTION_VIEW)),
               db: Session = Depends(get_session)):
    rows = db.execute(select(ActionPlan).order_by(ActionPlan.created_at.desc())).scalars().all()
    return {"items": [_plan_dict(p) for p in rows], "total": len(rows)}


@router.post("", status_code=201, summary="Crear plan")
def create_plan(payload: PlanIn, viewer: Viewer = Depends(require_perm(P_ACTION_MANAGE)),
                db: Session = Depends(get_session)):
    p = ActionPlan(organization_id=viewer.organization.id, **payload.model_dump())
    db.add(p)
    db.commit()
    return _plan_dict(p)


@router.get("/dashboard", summary="Tablero de seguimiento de acciones")
def dashboard(viewer: Viewer = Depends(require_perm(P_ACTION_VIEW)),
              db: Session = Depends(get_session)):
    items = db.execute(select(ActionItem)).scalars().all()
    findings = db.execute(select(Finding)).scalars().all()
    with_action = {i.finding_id for i in items if i.finding_id}
    active = [i for i in items if i.status in OPEN_ACTION_STATES]
    return {
        "total": len(items),
        "active": len(active),
        "overdue": [_item_dict(i) for i in items if i.is_overdue],
        "by_status": {s: len([i for i in items if i.status == s]) for s in ACTION_STATES},
        "by_priority": {p: len([i for i in active if i.priority == p])
                        for p in ("alta", "media", "baja")},
        "average_progress": round(sum(i.progress for i in active) / len(active), 2) if active else 0.0,
        "without_owner": [_item_dict(i) for i in active if not (i.owner_user_id or i.owner_label)],
        "without_evidence": [_item_dict(i) for i in items
                             if i.status == AI_DONE and not i.evidence],
        "findings_without_action": [
            {"id": f.id, "title": f.title, "ftype": f.ftype, "priority": f.priority}
            for f in findings if f.id not in with_action
        ],
    }


@router.get("/{plan_id}", summary="Detalle de plan")
def get_plan(plan_id: str, viewer: Viewer = Depends(require_perm(P_ACTION_VIEW)),
             db: Session = Depends(get_session)):
    p = db.get(ActionPlan, plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    return {**_plan_dict(p), "items": [_item_dict(i) for i in p.items]}


@router.post("/{plan_id}/items", status_code=201, summary="Agregar acción")
def create_item(plan_id: str, payload: ItemIn,
                viewer: Viewer = Depends(require_perm(P_ACTION_MANAGE)),
                db: Session = Depends(get_session)):
    p = db.get(ActionPlan, plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    if payload.status not in ACTION_STATES:
        raise HTTPException(status_code=422, detail="Estado de acción inválido")
    if payload.finding_id and not db.get(Finding, payload.finding_id):
        raise HTTPException(status_code=422, detail="El hallazgo no pertenece a esta organización")
    item = ActionItem(organization_id=viewer.organization.id, plan_id=p.id, **payload.model_dump())
    db.add(item)
    db.commit()
    audit_svc.log_view(db, viewer, "accion_creada", entity="action_item", entity_id=item.id)
    return _item_dict(item)


@router.patch("/items/{item_id}", summary="Actualizar acción")
def update_item(item_id: str, payload: ItemUpdate,
                viewer: Viewer = Depends(require_perm(P_ACTION_UPDATE)),
                db: Session = Depends(get_session)):
    """Una jefatura puede actualizar avance y evidencia de las acciones de su
    alcance; cambiar la definición del compromiso requiere `action.manage`."""
    item = db.get(ActionItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Acción no encontrada")
    data = payload.model_dump(exclude_none=True)
    editable_by_leader = {"progress", "evidence", "comments", "status", "next_review_on", "risks"}
    if not viewer.can(P_ACTION_MANAGE):
        if set(data) - editable_by_leader:
            raise HTTPException(
                status_code=403,
                detail="Sólo puedes actualizar avance, estado, evidencia y comentarios",
            )
        if item.org_unit_id and viewer.scope_unit_ids and item.org_unit_id not in viewer.scope_unit_ids:
            raise HTTPException(status_code=403, detail="Acción fuera de tu alcance")
    if data.get("status") == AI_DONE and not (data.get("evidence") or item.evidence):
        raise HTTPException(status_code=422, detail="Para cerrar una acción hay que registrar evidencia")
    for k, v in data.items():
        setattr(item, k, v)
    if item.status == AI_DONE and not item.completed_at:
        item.completed_at = dt.datetime.now(dt.UTC)
        item.progress = 1.0
    db.commit()
    audit_svc.log_view(db, viewer, "accion_actualizada", entity="action_item",
                       entity_id=item.id, detail={"campos": list(data)})
    return _item_dict(item)
