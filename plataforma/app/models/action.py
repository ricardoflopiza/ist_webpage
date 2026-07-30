# -*- coding: utf-8 -*-
"""Planes de acción y compromisos de mejora (§19)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TenantScoped, Timestamps, UUIDPk

AI_PROPOSED = "propuesta"
AI_APPROVED = "aprobada"
AI_RUNNING = "en_ejecucion"
AI_BLOCKED = "bloqueada"
AI_DONE = "completada"
AI_CANCELLED = "cancelada"
AI_EVALUATION = "en_evaluacion"
ACTION_STATES = (AI_PROPOSED, AI_APPROVED, AI_RUNNING, AI_BLOCKED, AI_DONE, AI_CANCELLED, AI_EVALUATION)
OPEN_ACTION_STATES = (AI_PROPOSED, AI_APPROVED, AI_RUNNING, AI_BLOCKED, AI_EVALUATION)


class ActionPlan(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "action_plans"

    campaign_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("survey_campaigns.id", ondelete="SET NULL"), index=True
    )
    org_unit_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("org_units.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("platform_users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(30), default="activo", nullable=False)
    starts_on: Mapped[dt.date | None] = mapped_column(Date)
    ends_on: Mapped[dt.date | None] = mapped_column(Date)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    items: Mapped[list[ActionItem]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class ActionItem(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "action_items"

    plan_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("action_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    finding_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("findings.id", ondelete="SET NULL"), index=True
    )
    problem: Mapped[str | None] = mapped_column(Text)
    objective: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("platform_users.id", ondelete="SET NULL"), index=True
    )
    owner_label: Mapped[str | None] = mapped_column(String(160))     # responsable sin cuenta
    team: Mapped[str | None] = mapped_column(String(200))
    org_unit_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("org_units.id", ondelete="SET NULL")
    )
    starts_on: Mapped[dt.date | None] = mapped_column(Date)
    due_on: Mapped[dt.date | None] = mapped_column(Date, index=True)
    indicator: Mapped[str | None] = mapped_column(String(250))
    target: Mapped[str | None] = mapped_column(String(120))
    resources: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)
    risks: Mapped[str | None] = mapped_column(Text)
    comments: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="media", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=AI_PROPOSED, nullable=False, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    next_review_on: Mapped[dt.date | None] = mapped_column(Date)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    plan: Mapped[ActionPlan] = relationship(back_populates="items")

    @property
    def is_overdue(self) -> bool:
        return bool(
            self.due_on
            and self.status in OPEN_ACTION_STATES
            and self.due_on < dt.date.today()
        )
