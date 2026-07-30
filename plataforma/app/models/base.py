# -*- coding: utf-8 -*-
"""Declarative base, mixins e identificadores.

Todas las claves primarias son UUID en texto: nunca se expone un identificador
secuencial en una URL pública (requisito §9 del encargo).
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column
from sqlalchemy.types import JSON


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON, list: JSON}


class UUIDPk:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)


class Timestamps:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TenantScoped:
    """Marca una entidad como perteneciente a una organización.

    Basta heredar de esta clase para quedar cubierto por el filtro automático de
    `app.db.install_guards()`. No agregar `organization_id` a mano en un modelo
    sin heredar de aquí: quedaría fuera del guard.
    """

    @declared_attr
    def organization_id(cls) -> Mapped[str]:  # noqa: N805
        return mapped_column(
            String(32), ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False, index=True,
        )


class PlatformOrTenantScoped:
    """Entidad que puede ser de plataforma (organization_id NULL) o de un tenant.

    Sólo para catálogos compartidos: plantillas maestras, banco de preguntas,
    servicios de consultoría y benchmarks. Una organización ve lo suyo y lo de
    plataforma, nunca lo de otro tenant.
    """

    @declared_attr
    def organization_id(cls) -> Mapped[str | None]:  # noqa: N805
        return mapped_column(
            String(32), ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True, index=True,
        )
