# -*- coding: utf-8 -*-
"""Instrumentos: plantillas, versiones inmutables, módulos, dimensiones y preguntas."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, PlatformOrTenantScoped, Timestamps, UUIDPk

# --------------------------------------------------------------- tipos de pregunta
Q_LIKERT = "likert"
Q_NUMERIC = "numeric"
Q_SINGLE = "single_choice"
Q_MULTI = "multi_choice"
Q_TEXT = "open_text"
Q_MATRIX = "matrix"
Q_YESNO = "yes_no"
Q_RANKING = "ranking"
Q_NPS = "nps"
QUESTION_TYPES = (Q_LIKERT, Q_NUMERIC, Q_SINGLE, Q_MULTI, Q_TEXT, Q_MATRIX, Q_YESNO, Q_RANKING, Q_NPS)

# Sólo estos tipos entran al cálculo 0-100 de dimensiones.
SCORABLE_TYPES = (Q_LIKERT, Q_NUMERIC, Q_NPS)

# --------------------------------------------------------------- estados de versión
VERSION_DRAFT = "borrador"
VERSION_PUBLISHED = "publicada"
VERSION_RETIRED = "retirada"

# --------------------------------------------------------------- familias de índice (§14)
INDEX_MANAGEMENT = "gestion_organizacional"
INDEX_TRUST = "confianza_relaciones"
INDEX_SUSTAIN = "sostenibilidad_sentido"


class SurveyTemplate(UUIDPk, Timestamps, PlatformOrTenantScoped, Base):
    """Identidad de un instrumento. Maestra (organization_id NULL) o adaptada por tenant."""

    __tablename__ = "survey_templates"

    code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(40), default="clima", nullable=False)
    sector_hint: Mapped[str | None] = mapped_column(String(80))
    # Trazabilidad de la adaptación: de qué plantilla maestra deriva.
    derived_from_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("survey_templates.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    versions: Mapped[list[SurveyTemplateVersion]] = relationship(
        back_populates="template", cascade="all, delete-orphan", order_by="SurveyTemplateVersion.number"
    )


class SurveyTemplateVersion(UUIDPk, Timestamps, PlatformOrTenantScoped, Base):
    """Versión del instrumento. Al publicarse queda **inmutable**.

    Las campañas apuntan a una versión, no a la plantilla: cambiar el instrumento
    nunca altera resultados ya levantados, y el benchmark sabe qué se comparó.
    """

    __tablename__ = "survey_template_versions"
    __table_args__ = (UniqueConstraint("template_id", "number", name="uq_version_number"),)

    template_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("survey_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default=VERSION_DRAFT, nullable=False)
    changelog: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    published_by_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("platform_users.id", ondelete="SET NULL")
    )
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)

    template: Mapped[SurveyTemplate] = relationship(back_populates="versions")
    modules: Mapped[list[SurveyModule]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="SurveyModule.sort_order"
    )

    @property
    def is_editable(self) -> bool:
        return self.status == VERSION_DRAFT


class SurveyModule(UUIDPk, Timestamps, PlatformOrTenantScoped, Base):
    """Bloque activable/desactivable dentro de una versión (clima, liderazgo, remoto…)."""

    __tablename__ = "survey_modules"

    version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("survey_template_versions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    version: Mapped[SurveyTemplateVersion] = relationship(back_populates="modules")
    dimensions: Mapped[list[SurveyDimension]] = relationship(
        back_populates="module", cascade="all, delete-orphan", order_by="SurveyDimension.sort_order"
    )


class SurveyDimension(UUIDPk, Timestamps, PlatformOrTenantScoped, Base):
    """Dimensión medida. `is_outcome=True` marca variable de resultado (§13).

    Las variables de resultado (satisfacción, recomendación, compromiso,
    permanencia, calidad del trabajo) NO se promedian con las dimensiones de
    clima: se usan como criterio en el análisis de impulsores.
    """

    __tablename__ = "survey_dimensions"

    module_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("survey_modules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    definition: Mapped[str | None] = mapped_column(Text)
    is_outcome: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    index_key: Mapped[str | None] = mapped_column(String(60))   # índice agregado (§14), hipótesis
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    module: Mapped[SurveyModule] = relationship(back_populates="dimensions")
    questions: Mapped[list[SurveyQuestion]] = relationship(
        back_populates="dimension", cascade="all, delete-orphan", order_by="SurveyQuestion.sort_order"
    )


class SurveyQuestion(UUIDPk, Timestamps, PlatformOrTenantScoped, Base):
    __tablename__ = "survey_questions"

    dimension_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("survey_dimensions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    help_text: Mapped[str | None] = mapped_column(Text)
    qtype: Mapped[str] = mapped_column(String(24), default="likert", nullable=False)
    scale_key: Mapped[str | None] = mapped_column(String(40))     # acuerdo, frecuencia, nps…
    options: Mapped[list | None] = mapped_column(default=None)    # opciones/filas de matriz
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_na: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_reverse: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tags: Mapped[list | None] = mapped_column(default=None)
    # Lógica condicional: {"question_code": "...", "op": "in|=|!=", "values": [...]}
    display_logic: Mapped[dict | None] = mapped_column(default=None)
    bank_item_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("question_bank_items.id", ondelete="SET NULL")
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    dimension: Mapped[SurveyDimension] = relationship(back_populates="questions")


class QuestionBankItem(UUIDPk, Timestamps, PlatformOrTenantScoped, Base):
    """Banco reutilizable de preguntas (§7)."""

    __tablename__ = "question_bank_items"

    code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    qtype: Mapped[str] = mapped_column(String(24), default="likert", nullable=False)
    scale_key: Mapped[str | None] = mapped_column(String(40))
    dimension_code: Mapped[str | None] = mapped_column(String(80), index=True)
    options: Mapped[list | None] = mapped_column(default=None)
    is_reverse: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tags: Mapped[list | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(Text)
