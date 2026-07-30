# -*- coding: utf-8 -*-
"""Resultados calculados, hallazgos consultivos, benchmarks y reportes."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, PlatformOrTenantScoped, TenantScoped, Timestamps, UUIDPk

# --------------------------------------------------------------- hallazgos (§18)
F_STRENGTH = "fortaleza"
F_ALERT = "alerta"
F_GAP = "brecha"
F_LEVER = "palanca"
F_HYPOTHESIS = "hipotesis"
F_RISK = "riesgo"
FINDING_TYPES = (F_STRENGTH, F_ALERT, F_GAP, F_LEVER, F_HYPOTHESIS, F_RISK)

FS_SUGGESTED = "sugerido_por_sistema"   # nunca se presenta como conclusión hasta validarse
FS_IN_REVIEW = "en_revision"
FS_VALIDATED = "validado"
FS_DISCARDED = "descartado"


class ResultSnapshot(UUIDPk, Timestamps, TenantScoped, Base):
    """Cálculo materializado de una campaña (opcionalmente de un segmento).

    Los resultados se calculan en el servidor (`services/scoring.py`) y se
    congelan aquí: el frontend nunca recalcula, sólo dibuja.
    """

    __tablename__ = "result_snapshots"

    campaign_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("survey_campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(String(24), default="global", nullable=False)  # global|segmento
    segment_key: Mapped[str | None] = mapped_column(String(200), index=True)
    n_responses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    n_invited: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    participation: Mapped[float | None] = mapped_column(Float)
    payload: Mapped[dict | None] = mapped_column(default=None)     # dimensiones, ítems, índices
    engine_version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
    computed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Finding(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "findings"

    campaign_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("survey_campaigns.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    ftype: Mapped[str] = mapped_column(String(24), default=F_ALERT, nullable=False, index=True)
    dimension_code: Mapped[str | None] = mapped_column(String(80), index=True)
    priority: Mapped[str] = mapped_column(String(20), default="media", nullable=False)

    quant_evidence: Mapped[dict | None] = mapped_column(default=None)
    qual_evidence: Mapped[str | None] = mapped_column(Text)
    segments: Mapped[list | None] = mapped_column(default=None)

    interpretation: Mapped[str | None] = mapped_column(Text)
    limitations: Mapped[str | None] = mapped_column(Text)
    recommendation: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(30), default=FS_SUGGESTED, nullable=False, index=True)
    is_system_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    validated_by_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("platform_users.id", ondelete="SET NULL")
    )
    validated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # Ajuste consultivo de prioridad (§16): un riesgo ético no cede ante una correlación baja.
    override_reason: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Benchmark(UUIDPk, Timestamps, PlatformOrTenantScoped, Base):
    """Referencia comparativa anonimizada y agregada (§23)."""

    __tablename__ = "benchmarks"

    code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(40), default="global", nullable=False)
    sector: Mapped[str | None] = mapped_column(String(80))
    size_bucket: Mapped[str | None] = mapped_column(String(40))
    region: Mapped[str | None] = mapped_column(String(80))
    org_type: Mapped[str | None] = mapped_column(String(80))
    work_mode: Mapped[str | None] = mapped_column(String(40))
    period_label: Mapped[str | None] = mapped_column(String(60))

    template_code: Mapped[str | None] = mapped_column(String(80), index=True)
    version_number: Mapped[int | None] = mapped_column(Integer)

    n_organizations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    n_responses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    period_from: Mapped[dt.date | None] = mapped_column(Date)
    period_to: Mapped[dt.date | None] = mapped_column(Date)
    inclusion_criteria: Mapped[str | None] = mapped_column(Text)
    limitations: Mapped[str | None] = mapped_column(Text)
    # {"liderazgo": {"mean":68.2,"median":69,"sd":9.1,"p25":61,"p50":69,"p75":75,"n":1240}}
    stats: Mapped[dict | None] = mapped_column(default=None)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Report(UUIDPk, Timestamps, TenantScoped, Base):
    """Reporte generado (ejecutivo, organizacional o de equipo)."""

    __tablename__ = "reports"

    campaign_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("survey_campaigns.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(30), default="ejecutivo", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    org_unit_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("org_units.id", ondelete="SET NULL")
    )
    audience: Mapped[str | None] = mapped_column(String(60))
    payload: Mapped[dict | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String(24), default="borrador", nullable=False)
    generated_by_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("platform_users.id", ondelete="SET NULL")
    )
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
