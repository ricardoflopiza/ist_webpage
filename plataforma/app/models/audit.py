# -*- coding: utf-8 -*-
"""Bitácora de auditoría.

No es TenantScoped: registra también eventos de plataforma y accesos denegados
entre tenants (que por definición ocurren fuera del alcance de una organización).
La consulta desde la aplicación siempre filtra por `organization_id` de forma
explícita en `services/audit.py`.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Timestamps, UUIDPk

# Acciones de alto riesgo que siempre se registran.
A_LOGIN = "login"
A_LOGIN_FAIL = "login_fallido"
A_VIEW_RESULTS = "ver_resultados"
A_VIEW_COMMENTS = "ver_comentarios"
A_VIEW_SENSITIVE = "ver_comentario_sensible"
A_EXPORT = "exportacion"
A_TENANT_DENIED = "acceso_cruzado_denegado"
A_SUPPRESSED = "segmento_suprimido"
A_PUBLISH = "publicacion"
A_CONFIG = "configuracion"


class AuditLog(UUIDPk, Timestamps, Base):
    __tablename__ = "audit_logs"

    organization_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("platform_users.id", ondelete="SET NULL"), index=True
    )
    actor_email: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    entity: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(32))
    # Nunca se guarda aquí el texto de un comentario sensible: sólo su identificador.
    detail: Mapped[dict | None] = mapped_column(default=None)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(20), default="ok", nullable=False)
