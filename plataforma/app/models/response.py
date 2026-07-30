# -*- coding: utf-8 -*-
"""Respuestas, ítems respondidos y comentarios abiertos.

Invariante duro de todo el módulo: **ninguna fila de aquí permite volver a la
persona**. No hay FK a `employee_population` ni a `survey_invitations`.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TenantScoped, Timestamps, UUIDPk

R_STARTED = "iniciada"
R_PARTIAL = "parcial"
R_SUBMITTED = "enviada"
R_DISCARDED = "descartada"


class SurveyResponse(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "survey_responses"

    campaign_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("survey_campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(24), default=R_STARTED, nullable=False, index=True)

    # Fotografía de segmentación tomada de la nómina al iniciar. Sin identidad.
    # Ej: {"unidad": "<org_unit_id>", "antiguedad": "3-5", "modalidad": "hibrido"}
    segment: Mapped[dict | None] = mapped_column(default=None)
    org_unit_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("org_units.id", ondelete="SET NULL"), index=True
    )

    # Hash del ticket de retomar (firmado y guardado en cookie del navegador).
    # Guardar el hash impide reconstruir el ticket desde la base.
    ticket_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    consent_version: Mapped[str | None] = mapped_column(String(20))
    consent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(24))     # enlace_token, qr, codigo…
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    answers: Mapped[list[Answer]] = relationship(
        back_populates="response", cascade="all, delete-orphan"
    )


class Answer(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "answers"

    response_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("survey_responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("survey_campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("survey_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    value_num: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(Text)
    value_json: Mapped[list | None] = mapped_column(default=None)   # múltiple, ranking, matriz
    is_na: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    response: Mapped[SurveyResponse] = relationship(back_populates="answers")


class OpenComment(UUIDPk, Timestamps, TenantScoped, Base):
    """Comentario abierto extraído de una respuesta de texto, para análisis cualitativo (§17)."""

    __tablename__ = "open_comments"

    campaign_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("survey_campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("survey_questions.id", ondelete="SET NULL")
    )
    answer_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("answers.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    redacted_text: Mapped[str | None] = mapped_column(Text)   # con datos personales ocultos
    segment: Mapped[dict | None] = mapped_column(default=None)
    org_unit_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("org_units.id", ondelete="SET NULL"), index=True
    )

    themes: Mapped[list | None] = mapped_column(default=None)      # etiquetas temáticas
    sentiment: Mapped[str | None] = mapped_column(String(20))      # positivo/neutro/negativo
    is_proposal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Protocolo de comentarios sensibles (§17)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    sensitive_flags: Mapped[list | None] = mapped_column(default=None)
    sensitive_reviewed_by_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("platform_users.id", ondelete="SET NULL")
    )
    sensitive_reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    review_status: Mapped[str | None] = mapped_column(String(30))

    # Trazabilidad de asistencia automática: siempre revisable por humano.
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_reviewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
