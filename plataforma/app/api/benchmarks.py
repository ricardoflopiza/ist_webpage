# -*- coding: utf-8 -*-
"""Benchmarks anonimizados (§23).

Dos reglas que la implementación hace cumplir:
1. Una organización sólo entra a un benchmark si dio consentimiento explícito
   (`benchmark_consent`) — el aporte es siempre agregado, nunca fila a fila.
2. Sólo se comparan campañas de la **misma plantilla y versión**: comparar
   puntajes de preguntas distintas produce diferencias que no significan nada.
"""
from __future__ import annotations

import datetime as dt
import statistics

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Benchmark, Organization, ResultSnapshot, SurveyCampaign, SurveyTemplateVersion
from ..security.deps import Viewer, platform_viewer, require_perm
from ..security.permissions import P_BENCHMARK_MANAGE, P_BENCHMARK_VIEW
from ..services import audit as audit_svc
from . import API_PREFIX

router = APIRouter(prefix=f"{API_PREFIX}", tags=["benchmarks"])
ALL = {"include_all": True}

MIN_ORGS = 3          # menos organizaciones ⇒ el benchmark identifica a sus miembros
MIN_RESPONSES = 150


class BenchmarkIn(BaseModel):
    code: str = Field(min_length=2, max_length=80)
    name: str
    template_code: str
    version_number: int | None = None
    scope_kind: str = "global"
    sector: str | None = None
    size_bucket: str | None = None
    region: str | None = None
    org_type: str | None = None
    work_mode: str | None = None
    period_label: str | None = None
    period_from: dt.date | None = None
    period_to: dt.date | None = None
    inclusion_criteria: str | None = None
    limitations: str | None = None


def _dict(b: Benchmark) -> dict:
    return {
        "id": b.id, "code": b.code, "name": b.name, "scope_kind": b.scope_kind,
        "sector": b.sector, "size_bucket": b.size_bucket, "region": b.region,
        "org_type": b.org_type, "work_mode": b.work_mode, "period_label": b.period_label,
        "template_code": b.template_code, "version_number": b.version_number,
        "n_organizations": b.n_organizations, "n_responses": b.n_responses,
        "period_from": b.period_from, "period_to": b.period_to,
        "inclusion_criteria": b.inclusion_criteria, "limitations": b.limitations,
        "stats": b.stats, "is_published": b.is_published, "is_demo": b.is_demo,
    }


@router.get("/benchmarks", summary="Benchmarks publicados")
def list_benchmarks(viewer: Viewer = Depends(platform_viewer), db: Session = Depends(get_session)):
    rows = db.execute(
        select(Benchmark).order_by(Benchmark.name).execution_options(**ALL)
    ).scalars().all()
    if not viewer.can(P_BENCHMARK_MANAGE):
        rows = [b for b in rows if b.is_published]
    return {"items": [_dict(b) for b in rows], "total": len(rows)}


@router.get("/o/{org_slug}/benchmarks", summary="Benchmarks aplicables a la organización")
def org_benchmarks(viewer: Viewer = Depends(require_perm(P_BENCHMARK_VIEW)),
                   db: Session = Depends(get_session)):
    rows = db.execute(
        select(Benchmark).where(Benchmark.is_published.is_(True)).execution_options(**ALL)
    ).scalars().all()
    org = viewer.organization
    return {"items": [
        {**_dict(b), "applicable": (b.scope_kind == "global" or b.sector == org.sector
                                    or b.size_bucket == org.size_bucket)}
        for b in rows
    ], "consent": org.benchmark_consent,
        "note": ("Esta organización " + ("sí" if org.benchmark_consent else "no") +
                 " autoriza aportar sus resultados agregados a benchmarks.")}


@router.post("/benchmarks/build", status_code=201, summary="Construir benchmark a partir de campañas")
def build(payload: BenchmarkIn, viewer: Viewer = Depends(platform_viewer),
          db: Session = Depends(get_session)):
    viewer.require(P_BENCHMARK_MANAGE)
    versions = db.execute(
        select(SurveyTemplateVersion).join(
            SurveyTemplateVersion.template
        ).where(SurveyTemplateVersion.template.has(code=payload.template_code))
        .execution_options(**ALL)
    ).scalars().all()
    if payload.version_number:
        versions = [v for v in versions if v.number == payload.version_number]
    version_ids = {v.id for v in versions}
    if not version_ids:
        raise HTTPException(status_code=404, detail="No hay versiones de esa plantilla")

    orgs = {
        o.id: o for o in db.execute(
            select(Organization).where(Organization.benchmark_consent.is_(True))
            .execution_options(**ALL)
        ).scalars()
    }
    if payload.sector:
        orgs = {i: o for i, o in orgs.items() if o.sector == payload.sector}
    if payload.size_bucket:
        orgs = {i: o for i, o in orgs.items() if o.size_bucket == payload.size_bucket}
    if payload.region:
        orgs = {i: o for i, o in orgs.items() if o.region == payload.region}
    if payload.org_type:
        orgs = {i: o for i, o in orgs.items() if o.org_type == payload.org_type}

    campaigns = [
        c for c in db.execute(select(SurveyCampaign).execution_options(**ALL)).scalars()
        if c.version_id in version_ids and c.organization_id in orgs and not c.is_pulse
    ]
    if payload.period_from:
        campaigns = [c for c in campaigns if c.ends_on and c.ends_on >= payload.period_from]
    if payload.period_to:
        campaigns = [c for c in campaigns if c.ends_on and c.ends_on <= payload.period_to]

    by_dimension: dict[str, list[float]] = {}
    n_responses = 0
    used_orgs = set()
    for c in campaigns:
        snap = db.execute(
            select(ResultSnapshot).where(
                ResultSnapshot.campaign_id == c.id, ResultSnapshot.scope == "global"
            ).order_by(ResultSnapshot.computed_at.desc()).execution_options(**ALL)
        ).scalars().first()
        if not snap or not snap.payload:
            continue
        used_orgs.add(c.organization_id)
        n_responses += snap.n_responses
        for d in snap.payload.get("dimensions", []):
            if d.get("score") is not None:
                by_dimension.setdefault(d["code"], []).append(d["score"])

    if len(used_orgs) < MIN_ORGS or n_responses < MIN_RESPONSES:
        raise HTTPException(
            status_code=409,
            detail=(f"Insuficiente para anonimizar: {len(used_orgs)} organizaciones y "
                    f"{n_responses} respuestas. Se exigen al menos {MIN_ORGS} y {MIN_RESPONSES}."),
        )

    stats = {}
    for code, values in by_dimension.items():
        values = sorted(values)
        stats[code] = {
            "mean": round(statistics.fmean(values), 1),
            "median": round(statistics.median(values), 1),
            "sd": round(statistics.pstdev(values), 2) if len(values) > 1 else None,
            "p25": round(_percentile(values, 25), 1),
            "p50": round(_percentile(values, 50), 1),
            "p75": round(_percentile(values, 75), 1),
            "n_organizations": len(values),
        }

    b = Benchmark(
        organization_id=None, n_organizations=len(used_orgs), n_responses=n_responses,
        stats=stats, is_published=False, **payload.model_dump(),
    )
    db.add(b)
    db.commit()
    audit_svc.log(db, "benchmark_construido", user_id=viewer.user.id,
                  actor_email=viewer.user.email, entity="benchmark", entity_id=b.id,
                  detail={"organizaciones": len(used_orgs), "respuestas": n_responses})
    return _dict(b)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    k = (len(values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


@router.post("/benchmarks/{benchmark_id}/publish", summary="Publicar benchmark")
def publish(benchmark_id: str, viewer: Viewer = Depends(platform_viewer),
            db: Session = Depends(get_session)):
    viewer.require(P_BENCHMARK_MANAGE)
    b = db.execute(
        select(Benchmark).where(Benchmark.id == benchmark_id).execution_options(**ALL)
    ).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="Benchmark no encontrado")
    if b.n_organizations < MIN_ORGS:
        raise HTTPException(status_code=409, detail="No cumple el mínimo de organizaciones")
    b.is_published = True
    db.commit()
    return _dict(b)
