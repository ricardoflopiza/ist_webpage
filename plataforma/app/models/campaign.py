# -*- coding: utf-8 -*-
"""Campañas, invitaciones y pulsos."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantScoped, Timestamps, UUIDPk

# --------------------------------------------------------------- estados (§9)
C_DRAFT = "borrador"
C_REVIEW = "en_revision"
C_SCHEDULED = "programada"
C_ACTIVE = "activa"
C_PAUSED = "pausada"
C_CLOSED = "cerrada"
C_ANALYSIS = "en_analisis"
C_PUBLISHED = "resultados_publicados"
C_FOLLOWUP = "en_seguimiento"
C_ARCHIVED = "archivada"

CAMPAIGN_STATES = (
    C_DRAFT, C_REVIEW, C_SCHEDULED, C_ACTIVE, C_PAUSED, C_CLOSED,
    C_ANALYSIS, C_PUBLISHED, C_FOLLOWUP, C_ARCHIVED,
)
# Estados en que se aceptan respuestas nuevas.
OPEN_STATES = (C_ACTIVE,)
# Estados en que ya se pueden calcular/mostrar resultados.
RESULT_STATES = (C_CLOSED, C_ANALYSIS, C_PUBLISHED, C_FOLLOWUP, C_ARCHIVED)

# --------------------------------------------------------------- acceso (§9)
ACCESS_EMAIL = "email"
ACCESS_TOKEN_LINK = "enlace_token"
ACCESS_QR = "qr"
ACCESS_CODE = "codigo"
ACCESS_OPEN = "enlace_abierto"
ACCESS_MANUAL = "carga_manual"
ACCESS_METHODS = (ACCESS_EMAIL, ACCESS_TOKEN_LINK, ACCESS_QR, ACCESS_CODE, ACCESS_OPEN, ACCESS_MANUAL)

# --------------------------------------------------------------- invitación
INV_PENDING = "pendiente"
INV_SENT = "enviada"
INV_STARTED = "iniciada"
INV_RESPONDED = "respondida"
INV_BOUNCED = "rebotada"
INV_EXCLUDED = "excluida"


class SurveyCampaign(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "survey_campaigns"

    version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("survey_template_versions.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    period_label: Mapped[str | None] = mapped_column(String(60))     # "2026 · S1"
    status: Mapped[str] = mapped_column(String(32), default=C_DRAFT, nullable=False, index=True)
    is_pulse: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    baseline_campaign_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("survey_campaigns.id", ondelete="SET NULL")
    )

    starts_on: Mapped[dt.date | None] = mapped_column(Date)
    ends_on: Mapped[dt.date | None] = mapped_column(Date)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    access_method: Mapped[str] = mapped_column(String(24), default=ACCESS_TOKEN_LINK, nullable=False)
    access_code: Mapped[str | None] = mapped_column(String(40))      # para ACCESS_CODE/QR

    # Población: filtro sobre la nómina. None ⇒ toda la nómina activa.
    population_filter: Mapped[dict | None] = mapped_column(default=None)
    invited_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Variables de segmentación autorizadas para esta campaña (claves de attributes).
    segmentation_keys: Mapped[list | None] = mapped_column(default=None)

    # Confidencialidad: override del umbral del tenant (nunca por debajo de él).
    anonymity_threshold: Mapped[int | None] = mapped_column(Integer)
    min_item_completion: Mapped[float | None] = mapped_column()

    consent_version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
    consent_text: Mapped[str | None] = mapped_column(Text)
    welcome_text: Mapped[str | None] = mapped_column(Text)
    closing_text: Mapped[str | None] = mapped_column(Text)
    invitation_subject: Mapped[str | None] = mapped_column(String(200))
    invitation_body: Mapped[str | None] = mapped_column(Text)
    inclusive_language: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    results_published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class SurveyInvitation(UUIDPk, Timestamps, TenantScoped, Base):
    """Invitación nominal.

    ⚠️ Invariante: esta tabla **no** tiene ninguna referencia a `SurveyResponse`,
    ni al revés. El token se guarda sólo como hash SHA-256 (irreversible) y se
    marca `responded_at` sin registrar qué respuesta se produjo.
    """

    __tablename__ = "survey_invitations"
    __table_args__ = (
        UniqueConstraint("campaign_id", "employee_id", name="uq_invitation_person"),
    )

    campaign_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("survey_campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("employee_population.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default=INV_PENDING, nullable=False, index=True)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    first_opened_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    reminders_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PulseSurvey(UUIDPk, Timestamps, TenantScoped, Base):
    """Metadatos del pulso: a qué está enganchado y contra qué línea base compara (§20)."""

    __tablename__ = "pulse_surveys"

    campaign_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("survey_campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_campaign_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("survey_campaigns.id", ondelete="SET NULL")
    )
    dimension_code: Mapped[str | None] = mapped_column(String(80))
    finding_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("findings.id", ondelete="SET NULL")
    )
    action_plan_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("action_plans.id", ondelete="SET NULL")
    )
    org_unit_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("org_units.id", ondelete="SET NULL")
    )
    cadence: Mapped[str | None] = mapped_column(String(40))   # mensual, trimestral…
    scheduled_for: Mapped[dt.date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
