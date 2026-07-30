# -*- coding: utf-8 -*-
"""Puente entre la base de datos y el motor de cálculo.

Toda salida de resultados pasa por `can_display_segment()`. Si la decisión es
negativa, esta capa devuelve la decisión y **ningún número**: no hay una versión
"completa" del payload circulando que el frontend deba recordar ocultar.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Answer,
    Benchmark,
    EmployeePopulation,
    OrgUnit,
    ResultSnapshot,
    SurveyCampaign,
    SurveyDimension,
    SurveyInvitation,
    SurveyModule,
    SurveyQuestion,
    SurveyResponse,
    SurveyTemplateVersion,
)
from ..models.response import R_SUBMITTED
from ..security.deps import Viewer
from . import drivers as drivers_mod
from .anonymity import SegmentDecision, can_display_segment, suppress_small_groups
from .scales import get_scale
from .scoring import DimensionDef, Instrument, ItemDef, ResponseData, aggregate

OUTCOME_LABELS = {
    "satisfaccion": "Satisfacción general",
    "recomendacion": "Recomendación",
    "compromiso": "Compromiso",
    "permanencia": "Intención de permanencia",
    "calidad_trabajo": "Capacidad de hacer un trabajo de calidad",
}


# ------------------------------------------------------------------ instrumento
def load_instrument(db: Session, version_id: str) -> Instrument:
    rows = db.execute(
        select(SurveyDimension, SurveyQuestion)
        .join(SurveyModule, SurveyModule.id == SurveyDimension.module_id)
        .outerjoin(SurveyQuestion, SurveyQuestion.dimension_id == SurveyDimension.id)
        .where(SurveyModule.version_id == version_id, SurveyModule.is_enabled.is_(True))
        .order_by(SurveyModule.sort_order, SurveyDimension.sort_order, SurveyQuestion.sort_order)
    ).all()

    dims: dict[str, DimensionDef] = {}
    for dim, q in rows:
        d = dims.get(dim.code)
        if d is None:
            d = DimensionDef(code=dim.code, name=dim.name,
                             is_outcome=dim.is_outcome, index_key=dim.index_key)
            dims[dim.code] = d
        if q is not None:
            d.items.append(ItemDef(
                id=q.id, code=q.code, text=q.text, dimension_code=dim.code,
                scale=get_scale(q.scale_key), is_reverse=q.is_reverse, qtype=q.qtype,
            ))
    return Instrument(dimensions=list(dims.values()))


def question_map(db: Session, version_id: str) -> dict[str, SurveyQuestion]:
    qs = db.execute(
        select(SurveyQuestion)
        .join(SurveyDimension, SurveyDimension.id == SurveyQuestion.dimension_id)
        .join(SurveyModule, SurveyModule.id == SurveyDimension.module_id)
        .where(SurveyModule.version_id == version_id)
    ).scalars().all()
    return {q.id: q for q in qs}


# ------------------------------------------------------------------ respuestas
def load_responses(
    db: Session, campaign: SurveyCampaign, filters: dict | None = None
) -> list[ResponseData]:
    """Carga las respuestas **enviadas** (las parciales no entran al cálculo)."""
    stmt = select(SurveyResponse).where(
        SurveyResponse.campaign_id == campaign.id,
        SurveyResponse.status == R_SUBMITTED,
    )
    responses = db.execute(stmt).scalars().all()
    responses = [r for r in responses if _matches(r, filters)]
    if not responses:
        return []

    ids = [r.id for r in responses]
    answers = db.execute(
        select(Answer).where(Answer.response_id.in_(ids), Answer.is_na.is_(False))
    ).scalars().all()
    by_response: dict[str, dict[str, float]] = {rid: {} for rid in ids}
    for a in answers:
        if a.value_num is not None:
            by_response[a.response_id][a.question_id] = float(a.value_num)

    return [
        ResponseData(id=r.id, values=by_response.get(r.id, {}),
                     segment=dict(r.segment or {}), org_unit_id=r.org_unit_id)
        for r in responses
    ]


def _matches(response: SurveyResponse, filters: dict | None) -> bool:
    if not filters:
        return True
    seg = response.segment or {}
    for key, value in filters.items():
        if value in (None, "", []):
            continue
        if key in ("org_unit_id", "unidad"):
            if not _in_unit(response, value):
                return False
        elif str(seg.get(key)) != str(value):
            return False
    return True


def _in_unit(response: SurveyResponse, unit_id: str) -> bool:
    seg = response.segment or {}
    path = seg.get("unit_path") or []
    return response.org_unit_id == unit_id or unit_id in path


# ------------------------------------------------------------------ participación
def participation(db: Session, campaign: SurveyCampaign) -> dict:
    invited = db.execute(
        select(func.count()).select_from(SurveyInvitation)
        .where(SurveyInvitation.campaign_id == campaign.id)
    ).scalar_one()
    submitted = db.execute(
        select(func.count()).select_from(SurveyResponse).where(
            SurveyResponse.campaign_id == campaign.id,
            SurveyResponse.status == R_SUBMITTED,
        )
    ).scalar_one()
    started = db.execute(
        select(func.count()).select_from(SurveyResponse)
        .where(SurveyResponse.campaign_id == campaign.id)
    ).scalar_one()
    universe = invited or campaign.invited_count or 0
    return {
        "invited": universe,
        "started": started,
        "submitted": submitted,
        "rate": round(submitted / universe * 100, 1) if universe else None,
        "completion_rate": round(submitted / started * 100, 1) if started else None,
    }


def unit_universe(db: Session, campaign: SurveyCampaign, unit_id: str | None) -> int | None:
    """Personas de la nómina en la unidad (para el chequeo de universo pequeño)."""
    if not unit_id:
        return None
    return db.execute(
        select(func.count()).select_from(EmployeePopulation).where(
            EmployeePopulation.org_unit_id == unit_id,
            EmployeePopulation.is_active.is_(True),
        )
    ).scalar_one()


# ------------------------------------------------------------------ comparaciones
def baseline_scores(db: Session, campaign: SurveyCampaign) -> dict[str, float]:
    """Puntajes de la medición anterior. Sólo si comparte versión de instrumento:
    comparar contra otra versión sería comparar preguntas distintas (§23)."""
    if not campaign.baseline_campaign_id:
        return {}
    prev = db.get(SurveyCampaign, campaign.baseline_campaign_id)
    if not prev or prev.version_id != campaign.version_id:
        return {}
    snap = db.execute(
        select(ResultSnapshot).where(
            ResultSnapshot.campaign_id == prev.id, ResultSnapshot.scope == "global"
        ).order_by(ResultSnapshot.computed_at.desc())
    ).scalars().first()
    if snap and snap.payload:
        return {
            d["code"]: d["score"]
            for d in snap.payload.get("dimensions", []) + snap.payload.get("outcomes", [])
            if d.get("score") is not None
        }
    payload = compute_payload(db, prev)
    return {d["code"]: d["score"] for d in payload["dimensions"] if d.get("score") is not None}


def benchmark_scores(db: Session, campaign: SurveyCampaign, organization) -> tuple[dict, Benchmark | None]:
    version = db.get(SurveyTemplateVersion, campaign.version_id)
    if not version:
        return {}, None
    template = version.template
    stmt = select(Benchmark).where(
        Benchmark.is_published.is_(True),
        Benchmark.template_code == template.code,
    ).execution_options(include_all=True)
    candidates = db.execute(stmt).scalars().all()
    if not candidates:
        return {}, None
    # Preferir el del mismo sector; si no hay, el global.
    best = next((b for b in candidates if b.sector and b.sector == organization.sector), None)
    best = best or next((b for b in candidates if b.scope_kind == "global"), candidates[0])
    stats = best.stats or {}
    return {k: v.get("mean") for k, v in stats.items() if isinstance(v, dict)}, best


# ------------------------------------------------------------------ cálculo completo
def compute_payload(
    db: Session, campaign: SurveyCampaign, filters: dict | None = None,
    *, organization=None, with_drivers: bool = True,
) -> dict:
    instrument = load_instrument(db, campaign.version_id)
    responses = load_responses(db, campaign, filters)
    org = organization
    min_completion = (
        campaign.min_item_completion
        or (org.min_item_completion if org else None)
        or 0.6
    )
    base = baseline_scores(db, campaign)
    bench, bench_obj = benchmark_scores(db, campaign, org) if org else ({}, None)

    payload = aggregate(instrument, responses, min_completion=min_completion,
                        baseline=base, benchmark=bench)
    payload["participation"] = participation(db, campaign)
    payload["benchmark_source"] = (
        {"name": bench_obj.name, "n_organizations": bench_obj.n_organizations,
         "n_responses": bench_obj.n_responses, "limitations": bench_obj.limitations}
        if bench_obj else None
    )

    person_scores = payload.pop("person_scores", {})
    if with_drivers:
        climate = [d["code"] for d in payload["dimensions"]]
        outcomes = [(o["code"], o["name"]) for o in payload["outcomes"]]
        labels = {d["code"]: d["name"] for d in payload["dimensions"] + payload["outcomes"]}
        payload["drivers"] = drivers_mod.analyze(person_scores, climate, outcomes, labels)
        main = payload["drivers"][0] if payload["drivers"] else None
        payload["priority_matrix"] = drivers_mod.priority_matrix(payload["dimensions"], main)
    return payload


def results_for_viewer(
    db: Session, campaign: SurveyCampaign, viewer: Viewer, filters: dict | None = None
) -> tuple[SegmentDecision, dict | None]:
    """Punto de entrada único de la API de resultados."""
    filters = {k: v for k, v in (filters or {}).items() if v not in (None, "", [])}
    unit_id = filters.get("org_unit_id")
    n_responses = len(load_responses(db, campaign, filters))
    decision = can_display_segment(
        filters, viewer, campaign,
        organization=viewer.organization,
        n_responses=n_responses,
        n_universe=unit_universe(db, campaign, unit_id),
    )
    if not decision.allowed:
        return decision, None
    payload = compute_payload(db, campaign, filters, organization=viewer.organization)
    payload["filters"] = filters
    payload["threshold"] = decision.threshold
    return decision, payload


# ------------------------------------------------------------------ heatmap por unidad
def unit_heatmap(
    db: Session, campaign: SurveyCampaign, viewer: Viewer, kind: str | None = None
) -> dict:
    """Mapa de calor unidades × dimensiones, con supresión de grupos pequeños."""
    from ..models.org import UNIT_DEPARTMENT

    threshold = can_display_segment(
        {}, viewer, campaign, organization=viewer.organization,
        n_responses=10 ** 6,
    ).threshold
    units = db.execute(
        select(OrgUnit).where(
            OrgUnit.kind == (kind or UNIT_DEPARTMENT), OrgUnit.is_active.is_(True)
        ).order_by(OrgUnit.name)
    ).scalars().all()
    if viewer.role not in ("superadmin", "consultant", "client_admin", "analyst"):
        allowed = set(viewer.scope_unit_ids or [])
        units = [u for u in units if u.id in allowed]

    global_payload = compute_payload(db, campaign, None, organization=viewer.organization,
                                     with_drivers=False)
    dim_codes = [(d["code"], d["name"]) for d in global_payload["dimensions"]]

    rows = []
    for u in units:
        payload = compute_payload(db, campaign, {"org_unit_id": u.id},
                                  organization=viewer.organization, with_drivers=False)
        rows.append({
            "key": u.id, "org_unit_id": u.id, "label": u.name,
            "n": payload["n_responses"],
            "scores": {d["code"]: d["score"] for d in payload["dimensions"]},
            "general": payload["general_score"],
        })
    rows = suppress_small_groups(rows, threshold)
    return {
        "threshold": threshold,
        "dimensions": [{"code": c, "name": n} for c, n in dim_codes],
        "rows": rows,
        "global": {d["code"]: d["score"] for d in global_payload["dimensions"]},
    }


# ------------------------------------------------------------------ snapshots
def save_snapshot(db: Session, campaign: SurveyCampaign, organization, segment_key: str | None = None,
                  filters: dict | None = None) -> ResultSnapshot:
    payload = compute_payload(db, campaign, filters, organization=organization)
    part = payload["participation"]
    snap = ResultSnapshot(
        organization_id=campaign.organization_id,
        campaign_id=campaign.id,
        scope="segmento" if segment_key else "global",
        segment_key=segment_key,
        n_responses=payload["n_responses"],
        n_invited=part["invited"],
        participation=part["rate"],
        payload=payload,
        computed_at=dt.datetime.now(dt.UTC),
    )
    db.add(snap)
    db.commit()
    return snap


def latest_snapshot(db: Session, campaign_id: str) -> ResultSnapshot | None:
    return db.execute(
        select(ResultSnapshot).where(
            ResultSnapshot.campaign_id == campaign_id, ResultSnapshot.scope == "global"
        ).order_by(ResultSnapshot.computed_at.desc())
    ).scalars().first()


# ------------------------------------------------------------------ hallazgos sugeridos
def suggest_findings(payload: dict, *, strength_cut: float = 75.0, alert_cut: float = 55.0) -> list[dict]:
    """Propone hallazgos a partir del cálculo (§18).

    Salen siempre marcados como `sugerido_por_sistema`: son un borrador para el
    consultor, nunca una conclusión publicable.
    """
    out = []
    for d in payload.get("dimensions", []):
        if d.get("score") is None:
            continue
        if d["score"] >= strength_cut:
            out.append({
                "ftype": "fortaleza", "dimension_code": d["code"],
                "title": f"Fortaleza en {d['name'].lower()}",
                "priority": "baja",
                "quant_evidence": {"score": d["score"], "favorable_pct": d["favorable_pct"], "n": d["n"]},
                "interpretation": (
                    f"{d['name']} obtiene {d['score']} puntos con {d['favorable_pct']}% de "
                    f"respuestas favorables (n={d['n']})."
                ),
            })
        elif d["score"] < alert_cut:
            out.append({
                "ftype": "alerta", "dimension_code": d["code"],
                "title": f"Resultado bajo en {d['name'].lower()}",
                "priority": "alta",
                "quant_evidence": {"score": d["score"], "unfavorable_pct": d["unfavorable_pct"], "n": d["n"]},
                "interpretation": (
                    f"{d['name']} obtiene {d['score']} puntos y {d['unfavorable_pct']}% de "
                    f"respuestas desfavorables (n={d['n']})."
                ),
            })
        if (d.get("polarization") or 0) >= 0.6:
            out.append({
                "ftype": "hipotesis", "dimension_code": d["code"],
                "title": f"Opiniones divididas en {d['name'].lower()}",
                "priority": "media",
                "quant_evidence": {"polarization": d["polarization"], "distribution": d["distribution"]},
                "interpretation": (
                    "El promedio esconde posiciones opuestas dentro de la organización. "
                    "Conviene revisar el detalle por unidad antes de concluir."
                ),
            })
    for dr in payload.get("drivers", [])[:1]:
        for d in dr.get("drivers", [])[:3]:
            if d.get("beta") is None or abs(d["beta"]) < 0.2:
                continue
            out.append({
                "ftype": "palanca", "dimension_code": d["code"],
                "title": f"Posible palanca: {d['name'].lower()}",
                "priority": "alta",
                "quant_evidence": {"beta": d["beta"], "r": d["r"], "outcome": dr["outcome_code"], "n": dr["n"]},
                "interpretation": (
                    f"{d['name']} es el factor más asociado a {dr['outcome_name'].lower()} "
                    f"(beta={d['beta']}). Asociación estadística, no causalidad."
                ),
                "limitations": dr.get("disclaimer"),
            })
    return out
