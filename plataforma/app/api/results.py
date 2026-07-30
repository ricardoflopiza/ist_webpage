# -*- coding: utf-8 -*-
"""Resultados, impulsores y matriz de prioridad (§12, §15, §16).

Todos los endpoints de este módulo pasan por `results_for_viewer()`, que aplica
el umbral de confidencialidad antes de calcular nada que se pueda entregar.
Cuando el segmento no alcanza el umbral, la respuesta es 200 con
`allowed: false` y el motivo — no un 403 — para que la interfaz pueda explicar
la regla en lugar de mostrar un error.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_session
from ..models.campaign import RESULT_STATES
from ..security.deps import Viewer, client_ip, org_viewer, require_perm
from ..security.permissions import P_DRIVERS_VIEW, P_RESULTS_ORG, P_RESULTS_PUBLISH, P_RESULTS_UNIT
from ..services import audit as audit_svc
from ..services import results as svc
from . import API_PREFIX
from .common import get_campaign, parse_filters

router = APIRouter(prefix=f"{API_PREFIX}/o/{{org_slug}}/results", tags=["resultados"])


def _viewer_can_see_results(viewer: Viewer) -> Viewer:
    if not (viewer.can(P_RESULTS_ORG) or viewer.can(P_RESULTS_UNIT)):
        raise HTTPException(status_code=403, detail="Sin permiso para ver resultados")
    return viewer


def _blocked(decision) -> dict:
    return {
        "allowed": False, "reason": decision.reason, "message": decision.message,
        "threshold": decision.threshold,
        "note": "No se entregan datos de segmentos bajo el umbral de confidencialidad.",
    }


@router.get("/{campaign_id}", summary="Resultados de una campaña (con filtros de segmentación)")
def campaign_results(campaign_id: str, request: Request,
                     viewer: Viewer = Depends(org_viewer), db: Session = Depends(get_session)):
    _viewer_can_see_results(viewer)
    campaign = get_campaign(db, campaign_id)
    filters = parse_filters(request)
    decision, payload = svc.results_for_viewer(db, campaign, viewer, filters)
    audit_svc.log_view(
        db, viewer, "ver_resultados", entity="survey_campaign", entity_id=campaign.id,
        detail={"filtros": filters, "permitido": decision.allowed, "motivo": decision.reason},
        ip=client_ip(request), result="ok" if decision.allowed else "suprimido",
    )
    if not decision.allowed:
        return _blocked(decision)
    return {"allowed": True, "campaign": {"id": campaign.id, "name": campaign.name,
                                          "status": campaign.status,
                                          "period_label": campaign.period_label},
            **payload}


@router.get("/{campaign_id}/summary", summary="Resumen ejecutivo")
def executive_summary(campaign_id: str, request: Request,
                      viewer: Viewer = Depends(org_viewer), db: Session = Depends(get_session)):
    _viewer_can_see_results(viewer)
    campaign = get_campaign(db, campaign_id)
    decision, payload = svc.results_for_viewer(db, campaign, viewer, parse_filters(request))
    if not decision.allowed:
        return _blocked(decision)
    dims = [d for d in payload["dimensions"] if d["score"] is not None]
    ranked = sorted(dims, key=lambda d: d["score"], reverse=True)
    matrix = payload.get("priority_matrix", {})
    critical = [p for p in matrix.get("points", []) if p["quadrant"] == "prioridad_critica"]
    return {
        "allowed": True,
        "participation": payload["participation"],
        "general_score": payload["general_score"],
        "indices": payload["indices"],
        "strengths": ranked[:3],
        "alerts": ranked[-3:][::-1],
        "levers": critical[:3],
        "outcomes": payload["outcomes"],
        "evolution": [
            {"code": d["code"], "name": d["name"], "delta": d.get("delta")}
            for d in payload["dimensions"] if d.get("delta") is not None
        ],
        "recommendations": svc.suggest_findings(payload),
        "methodological_note": (
            "Resultados organizacionales y grupales. No constituyen diagnóstico clínico "
            "individual ni reemplazan los instrumentos regulatorios de riesgo psicosocial."
        ),
    }


@router.get("/{campaign_id}/heatmap", summary="Mapa de calor por unidad")
def heatmap(campaign_id: str, kind: str | None = None,
            viewer: Viewer = Depends(org_viewer), db: Session = Depends(get_session)):
    _viewer_can_see_results(viewer)
    campaign = get_campaign(db, campaign_id)
    if campaign.status not in RESULT_STATES:
        return {"allowed": False, "reason": "campania_abierta",
                "message": "La campaña sigue abierta: los resultados se publican al cerrarla."}
    return {"allowed": True, **svc.unit_heatmap(db, campaign, viewer, kind)}


@router.get("/{campaign_id}/drivers", summary="Análisis de impulsores")
def drivers(campaign_id: str, request: Request,
            viewer: Viewer = Depends(require_perm(P_DRIVERS_VIEW)),
            db: Session = Depends(get_session)):
    campaign = get_campaign(db, campaign_id)
    decision, payload = svc.results_for_viewer(db, campaign, viewer, parse_filters(request))
    if not decision.allowed:
        return _blocked(decision)
    return {
        "allowed": True,
        "drivers": payload.get("drivers", []),
        "priority_matrix": payload.get("priority_matrix"),
        "language_note": (
            "Se habla de factores asociados y posibles palancas. Ninguna de estas "
            "relaciones permite afirmar causalidad."
        ),
    }


@router.get("/{campaign_id}/dimension/{dimension_code}", summary="Detalle de una dimensión")
def dimension_detail(campaign_id: str, dimension_code: str, request: Request,
                     viewer: Viewer = Depends(org_viewer), db: Session = Depends(get_session)):
    _viewer_can_see_results(viewer)
    campaign = get_campaign(db, campaign_id)
    decision, payload = svc.results_for_viewer(db, campaign, viewer, parse_filters(request))
    if not decision.allowed:
        return _blocked(decision)
    everything = payload["dimensions"] + payload["outcomes"]
    dim = next((d for d in everything if d["code"] == dimension_code), None)
    if not dim:
        raise HTTPException(status_code=404, detail="Dimensión no encontrada en esta campaña")
    return {"allowed": True, "dimension": dim, "threshold": decision.threshold}


@router.post("/{campaign_id}/snapshot", summary="Congelar el cálculo actual")
def snapshot(campaign_id: str, viewer: Viewer = Depends(require_perm(P_RESULTS_PUBLISH)),
             db: Session = Depends(get_session)):
    campaign = get_campaign(db, campaign_id)
    snap = svc.save_snapshot(db, campaign, viewer.organization)
    audit_svc.log_view(db, viewer, "snapshot_resultados", entity="result_snapshot", entity_id=snap.id)
    return {"id": snap.id, "computed_at": snap.computed_at, "n_responses": snap.n_responses}
