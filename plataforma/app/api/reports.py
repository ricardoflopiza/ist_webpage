# -*- coding: utf-8 -*-
"""Reportes ejecutivo, organizacional y de equipo (§22).

Todos se construyen sobre `results_for_viewer()`: un reporte no puede contener
un dato que la persona no podría ver en el dashboard. La exportación queda
registrada en la auditoría.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import ActionItem, Finding, OrgUnit, Report
from ..models.analysis import FS_VALIDATED
from ..security.deps import Viewer, client_ip, require_perm
from ..security.permissions import P_REPORT_EXPORT, P_REPORT_GENERATE, P_REPORT_VIEW
from ..services import audit as audit_svc
from ..services import results as results_svc
from . import API_PREFIX
from .common import get_campaign

router = APIRouter(prefix=f"{API_PREFIX}/o/{{org_slug}}/reports", tags=["reportes"])

METHODOLOGY = {
    "instrumento": "Encuesta autoadministrada con escalas de 5 puntos y preguntas abiertas.",
    "puntaje": "Los ítems se normalizan a una escala 0-100: ((valor - mínimo) / rango) × 100.",
    "favorabilidad": "Favorable = 4 y 5; neutral = 3; desfavorable = 1 y 2.",
    "items_invertidos": "Los ítems redactados en negativo se recodifican antes de promediar.",
    "cobertura": "Una dimensión no se calcula para quien respondió menos del mínimo de sus ítems.",
    "confidencialidad": "No se reportan segmentos bajo el umbral de la organización.",
    "limitaciones": [
        "Datos transversales y autoinformados: describen percepciones en un momento dado.",
        "Las asociaciones estadísticas no permiten afirmar causalidad.",
        "Los índices agregados son agrupaciones propuestas, pendientes de validación psicométrica.",
        "Los resultados son organizacionales y grupales; no constituyen diagnóstico clínico individual.",
        "El instrumento no reemplaza los protocolos regulatorios de riesgo psicosocial.",
    ],
}


def _base(db: Session, campaign_id: str, viewer: Viewer, filters: dict | None = None):
    campaign = get_campaign(db, campaign_id)
    decision, payload = results_svc.results_for_viewer(db, campaign, viewer, filters)
    if not decision.allowed:
        raise HTTPException(status_code=409, detail=decision.message)
    return campaign, payload


@router.get("/{campaign_id}/executive", summary="Reporte ejecutivo")
def executive(campaign_id: str, viewer: Viewer = Depends(require_perm(P_REPORT_VIEW)),
              db: Session = Depends(get_session)):
    campaign, payload = _base(db, campaign_id, viewer)
    dims = sorted([d for d in payload["dimensions"] if d["score"] is not None],
                  key=lambda d: d["score"], reverse=True)
    findings = db.execute(
        select(Finding).where(Finding.campaign_id == campaign.id, Finding.status == FS_VALIDATED)
    ).scalars().all()
    items = db.execute(select(ActionItem)).scalars().all()
    return {
        "kind": "ejecutivo", "campaign": campaign.name, "period": campaign.period_label,
        "participation": payload["participation"],
        "general_score": payload["general_score"],
        "strengths": dims[:3], "alerts": dims[-3:][::-1],
        "levers": (payload.get("priority_matrix") or {}).get("points", [])[:3],
        "outcomes": payload["outcomes"],
        "evolution": [{"code": d["code"], "name": d["name"], "delta": d.get("delta")}
                      for d in payload["dimensions"] if d.get("delta") is not None],
        "findings": [{"title": f.title, "ftype": f.ftype, "priority": f.priority,
                      "recommendation": f.recommendation} for f in findings],
        "action_status": {
            "total": len(items),
            "completed": len([i for i in items if i.status == "completada"]),
            "overdue": len([i for i in items if i.is_overdue]),
        },
        "methodology": METHODOLOGY,
    }


@router.get("/{campaign_id}/organizational", summary="Reporte organizacional completo")
def organizational(campaign_id: str, request: Request,
                   viewer: Viewer = Depends(require_perm(P_REPORT_VIEW)),
                   db: Session = Depends(get_session)):
    campaign, payload = _base(db, campaign_id, viewer)
    heatmap = results_svc.unit_heatmap(db, campaign, viewer)
    return {
        "kind": "organizacional", "campaign": campaign.name, "period": campaign.period_label,
        "technical_sheet": {
            "instrumento": campaign.version_id,
            "aplicacion": {"desde": campaign.starts_on, "hasta": campaign.ends_on},
            "acceso": campaign.access_method,
            "umbral_confidencialidad": payload.get("threshold"),
            "cobertura_minima_items": payload.get("min_item_completion"),
            "version_motor": payload.get("engine_version"),
        },
        "participation": payload["participation"],
        "dimensions": payload["dimensions"],
        "outcomes": payload["outcomes"],
        "indices": payload["indices"],
        "drivers": payload.get("drivers"),
        "priority_matrix": payload.get("priority_matrix"),
        "segmentation": heatmap,
        "benchmark": payload.get("benchmark_source"),
        "methodology": METHODOLOGY,
    }


@router.get("/{campaign_id}/team/{unit_id}", summary="Reporte de equipo")
def team_report(campaign_id: str, unit_id: str,
                viewer: Viewer = Depends(require_perm(P_REPORT_VIEW)),
                db: Session = Depends(get_session)):
    unit = db.get(OrgUnit, unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unidad no encontrada")
    campaign, payload = _base(db, campaign_id, viewer, {"org_unit_id": unit_id})
    dims = sorted([d for d in payload["dimensions"] if d["score"] is not None],
                  key=lambda d: d["score"], reverse=True)
    items = db.execute(
        select(ActionItem).where(ActionItem.org_unit_id == unit_id)
    ).scalars().all()
    return {
        "kind": "equipo", "unit": unit.name, "campaign": campaign.name,
        "n": payload["n_responses"], "participation": payload["participation"],
        "strengths": dims[:3], "opportunities": dims[-3:][::-1],
        "reflection_questions": [
            "¿Qué de lo que vemos aquí reconocemos en el día a día?",
            "¿Qué explicación tenemos para el resultado más bajo?",
            "¿Qué está en nuestras manos cambiar en los próximos tres meses?",
            "¿Qué necesitamos de otras áreas o de la jefatura para lograrlo?",
        ],
        "actions": [{"action": i.action, "status": i.status, "due_on": i.due_on,
                     "progress": i.progress} for i in items],
        "note": ("Resultados agregados del equipo. No se muestran respuestas individuales "
                 "ni segmentos bajo el umbral de confidencialidad."),
    }


@router.get("/{campaign_id}/export.csv", summary="Exportar resultados autorizados (CSV)")
def export_csv(campaign_id: str, request: Request,
               viewer: Viewer = Depends(require_perm(P_REPORT_EXPORT)),
               db: Session = Depends(get_session)):
    campaign, payload = _base(db, campaign_id, viewer)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["dimension", "codigo", "puntaje_0_100", "n", "favorable_%", "neutral_%",
                "desfavorable_%", "desviacion", "variacion_periodo_anterior", "benchmark"])
    for d in payload["dimensions"] + payload["outcomes"]:
        w.writerow([d["name"], d["code"], d["score"], d["n"], d["favorable_pct"],
                    d["neutral_pct"], d["unfavorable_pct"], d["sd"],
                    d.get("delta"), d.get("benchmark")])
    buf.seek(0)
    audit_svc.log_view(db, viewer, "exportacion", entity="survey_campaign",
                       entity_id=campaign.id, detail={"formato": "csv"}, ip=client_ip(request))
    # El nombre del archivo viaja en una cabecera HTTP: sólo ASCII, o algunos
    # clientes fallan al decodificarla.
    slug_name = unicodedata.normalize("NFKD", campaign.name).encode("ascii", "ignore").decode()
    slug_name = re.sub(r"[^A-Za-z0-9]+", "_", slug_name).strip("_") or "campania"
    filename = f"resultados_{slug_name}_{dt.date.today()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{campaign_id}/generate", status_code=201, summary="Guardar un reporte generado")
def generate(campaign_id: str, kind: str = "ejecutivo",
             viewer: Viewer = Depends(require_perm(P_REPORT_GENERATE)),
             db: Session = Depends(get_session)):
    campaign, payload = _base(db, campaign_id, viewer)
    report = Report(
        organization_id=viewer.organization.id, campaign_id=campaign.id, kind=kind,
        title=f"Reporte {kind} · {campaign.name}", payload=payload,
        generated_by_id=viewer.user.id, status="generado",
    )
    db.add(report)
    db.commit()
    audit_svc.log_view(db, viewer, "reporte_generado", entity="report", entity_id=report.id)
    return {"id": report.id, "kind": report.kind, "title": report.title}


@router.get("", summary="Reportes guardados")
def list_reports(viewer: Viewer = Depends(require_perm(P_REPORT_VIEW)),
                 db: Session = Depends(get_session)):
    rows = db.execute(select(Report).order_by(Report.created_at.desc())).scalars().all()
    return {"items": [
        {"id": r.id, "kind": r.kind, "title": r.title, "status": r.status,
         "campaign_id": r.campaign_id, "created_at": r.created_at}
        for r in rows
    ], "total": len(rows)}
