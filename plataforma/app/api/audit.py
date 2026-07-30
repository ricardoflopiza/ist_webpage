# -*- coding: utf-8 -*-
"""Consulta de la bitácora de auditoría (§11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import SurveyResponse
from ..security.deps import Viewer, client_ip, org_viewer, platform_viewer, require_perm
from ..security.permissions import P_AUDIT_VIEW, P_ORG_MANAGE, P_RAW_RESPONSE
from ..services import audit as svc
from . import API_PREFIX

router = APIRouter(prefix=f"{API_PREFIX}", tags=["auditoría"])


def _row(r) -> dict:
    return {
        "id": r.id, "at": r.created_at, "action": r.action, "actor": r.actor_email,
        "entity": r.entity, "entity_id": r.entity_id, "detail": r.detail,
        "ip": r.ip, "result": r.result, "organization_id": r.organization_id,
    }


@router.get("/audit", summary="Bitácora global de plataforma")
def global_audit(viewer: Viewer = Depends(platform_viewer), db: Session = Depends(get_session),
                 limit: int = 200):
    viewer.require(P_AUDIT_VIEW)
    return {"items": [_row(r) for r in svc.recent(db, None, limit)]}


@router.get("/o/{org_slug}/audit", summary="Bitácora de la organización")
def org_audit(viewer: Viewer = Depends(require_perm(P_ORG_MANAGE)),
              db: Session = Depends(get_session), limit: int = 200):
    return {"items": [_row(r) for r in svc.recent(db, viewer.organization.id, limit)]}


class RawAccessIn(BaseModel):
    reason: str = Field(min_length=20, max_length=500)


@router.post("/o/{org_slug}/responses/{response_id}/raw", summary="Acceso técnico excepcional")
def raw_response(response_id: str, payload: RawAccessIn, request: Request,
                 viewer: Viewer = Depends(org_viewer), db: Session = Depends(get_session)):
    """Acceso a una respuesta individual: función técnica excepcional.

    Ningún rol tiene `response.raw.read` por defecto —tampoco el
    superadministrador—, así que este endpoint devuelve 403 salvo que la
    capacidad se otorgue de forma expresa y temporal. Aun así exige una
    justificación escrita y deja registro permanente en la bitácora.

    Lo que devuelve son las respuestas de un cuestionario **sin** ninguna
    referencia a la persona: la plataforma no guarda ese vínculo.
    """
    if not viewer.can(P_RAW_RESPONSE):
        svc.log_view(db, viewer, "acceso_respuesta_denegado", entity="survey_response",
                     entity_id=response_id, ip=client_ip(request), result="denegado")
        raise HTTPException(
            status_code=403,
            detail="El acceso a respuestas individuales no está habilitado para ningún rol.",
        )
    resp = db.get(SurveyResponse, response_id)
    if not resp:
        raise HTTPException(status_code=404, detail="Respuesta no encontrada")
    svc.log_raw_access(db, viewer, response_id, payload.reason, ip=client_ip(request))
    return {
        "id": resp.id, "campaign_id": resp.campaign_id, "status": resp.status,
        "submitted_at": resp.submitted_at, "segment": resp.segment,
        "answers": [{"question_id": a.question_id, "value_num": a.value_num,
                     "value_text": a.value_text, "is_na": a.is_na} for a in resp.answers],
        "warning": "La plataforma no almacena a qué persona corresponde esta respuesta.",
    }
