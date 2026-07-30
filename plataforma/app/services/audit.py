# -*- coding: utf-8 -*-
"""Auditoría: quién vio o exportó qué, y qué se le denegó.

Nunca se guarda aquí el contenido de un comentario sensible; sólo su
identificador. Un correo de alerta con el texto completo sacaría el comentario
del perímetro de control (§17).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditLog
from ..models.audit import (  # noqa: F401
    A_CONFIG,
    A_EXPORT,
    A_LOGIN,
    A_LOGIN_FAIL,
    A_PUBLISH,
    A_SUPPRESSED,
    A_TENANT_DENIED,
    A_VIEW_COMMENTS,
    A_VIEW_RESULTS,
    A_VIEW_SENSITIVE,
)


def log(
    db: Session,
    action: str,
    *,
    organization_id: str | None = None,
    user_id: str | None = None,
    actor_email: str | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
    detail: dict | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    result: str = "ok",
) -> AuditLog:
    row = AuditLog(
        organization_id=organization_id, user_id=user_id, actor_email=actor_email,
        action=action, entity=entity, entity_id=entity_id, detail=detail,
        ip=ip, user_agent=(user_agent or "")[:500], result=result,
    )
    db.add(row)
    db.commit()
    return row


def log_view(db: Session, viewer, action: str, *, entity: str | None = None,
             entity_id: str | None = None, detail: dict | None = None,
             ip: str | None = None, result: str = "ok") -> None:
    log(
        db, action,
        organization_id=viewer.organization.id if viewer.organization else None,
        user_id=viewer.user.id, actor_email=viewer.user.email,
        entity=entity, entity_id=entity_id, detail=detail, ip=ip, result=result,
    )


def log_raw_access(db: Session, viewer, response_id: str, reason: str, ip: str | None = None) -> None:
    """Acceso técnico excepcional a una respuesta individual.

    Requiere justificación escrita y queda marcado como `excepcional` para que
    salte en cualquier revisión de la bitácora.
    """
    log(
        db, "acceso_respuesta_individual",
        organization_id=viewer.organization.id if viewer.organization else None,
        user_id=viewer.user.id, actor_email=viewer.user.email,
        entity="survey_response", entity_id=response_id,
        detail={"justificacion": reason, "excepcional": True}, ip=ip, result="excepcional",
    )


def recent(db: Session, organization_id: str | None = None, limit: int = 100) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if organization_id:
        stmt = stmt.where(AuditLog.organization_id == organization_id)
    return list(db.execute(stmt.execution_options(include_all=True)).scalars())
