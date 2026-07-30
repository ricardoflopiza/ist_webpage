# -*- coding: utf-8 -*-
"""Dependencias de acceso: quién mira, desde qué organización y con qué permisos."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_session, tenant_scope
from ..models import Organization, OrganizationMembership, PlatformUser
from ..models.org import ROLE_SUPERADMIN
from .permissions import WHOLE_ORG_VIEWERS, permissions_for
from .sessions import SESSION_COOKIE, read_session

_ORG_IN_PATH = re.compile(r"/o/([A-Za-z0-9_-]{1,64})(?:/|$)")


# ------------------------------------------------------------------ middleware
class TenantMiddleware:
    """Middleware ASGI puro que activa el aislamiento por organización.

    Es ASGI puro a propósito: corre en la misma tarea que el endpoint, así el
    `ContextVar` de `app.db` queda visible tanto en endpoints `async` como en los
    `def` que Starlette despacha al threadpool (que hereda una copia del
    contexto). Con `BaseHTTPMiddleware` el comportamiento sería más frágil.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        org_id = _resolve_org_id(scope.get("path", ""))
        with tenant_scope(org_id):
            await self.app(scope, receive, send)


def _resolve_org_id(path: str) -> str | None:
    m = _ORG_IN_PATH.search(path)
    if not m:
        return None
    slug = m.group(1)
    db = SessionLocal()
    try:
        org = db.execute(
            select(Organization).where(Organization.slug == slug)
        ).scalar_one_or_none()
        return org.id if org else None
    finally:
        db.close()


# ------------------------------------------------------------------ viewer
@dataclass
class Viewer:
    user: PlatformUser
    organization: Organization | None = None
    role: str = ""
    permissions: set[str] = field(default_factory=set)
    scope_unit_ids: list[str] = field(default_factory=list)

    @property
    def is_superadmin(self) -> bool:
        return bool(self.user.is_superadmin)

    @property
    def sees_whole_org(self) -> bool:
        return self.role in WHOLE_ORG_VIEWERS

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def require(self, permission: str) -> None:
        if not self.can(permission):
            raise HTTPException(status_code=403, detail=f"Sin permiso: {permission}")


def current_user(request: Request, db: Session = Depends(get_session)) -> PlatformUser | None:
    data = read_session(request.cookies.get(SESSION_COOKIE))
    if not data:
        return None
    user = db.get(PlatformUser, data["user_id"])
    if not user or not user.is_active:
        return None
    return user


def require_user(user: PlatformUser | None = Depends(current_user)) -> PlatformUser:
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    return user


def _membership(db: Session, org: Organization, user: PlatformUser) -> OrganizationMembership | None:
    return db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == org.id,
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.is_active.is_(True),
        )
    ).scalar_one_or_none()


def build_viewer(db: Session, user: PlatformUser, org: Organization | None) -> Viewer:
    if org is None:
        role = ROLE_SUPERADMIN if user.is_superadmin else ""
        return Viewer(user=user, role=role, permissions=permissions_for(role))
    m = _membership(db, org, user)
    if m is None:
        if user.is_superadmin:
            # El superadministrador entra por función técnica, sin membresía: queda auditado.
            return Viewer(user=user, organization=org, role=ROLE_SUPERADMIN,
                          permissions=permissions_for(ROLE_SUPERADMIN))
        raise HTTPException(status_code=404, detail="Organización no encontrada")
    return Viewer(
        user=user, organization=org, role=m.role,
        permissions=permissions_for(m.role),
        scope_unit_ids=list(m.scope_unit_ids or []),
    )


def platform_viewer(
    user: PlatformUser = Depends(require_user), db: Session = Depends(get_session)
) -> Viewer:
    """Contexto de plataforma (sin organización activa): consola de la consultora."""
    if user.is_superadmin:
        return build_viewer(db, user, None)
    # Un consultor sin organización activa recibe los permisos de consola, y sus
    # listados se limitan a las organizaciones donde tiene membresía.
    from ..models.org import ROLE_CONSULTANT
    roles = {
        m.role
        for m in db.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user.id,
                OrganizationMembership.is_active.is_(True),
            ).execution_options(include_all=True)
        ).scalars()
    }
    role = ROLE_CONSULTANT if ROLE_CONSULTANT in roles else (sorted(roles)[0] if roles else "")
    return Viewer(user=user, role=role, permissions=permissions_for(role))


def org_viewer(
    org_slug: str,
    user: PlatformUser = Depends(require_user),
    db: Session = Depends(get_session),
) -> Viewer:
    """Contexto de una organización. El aislamiento ya lo activó `TenantMiddleware`."""
    org = db.execute(
        select(Organization).where(Organization.slug == org_slug)
        .execution_options(include_all=True)
    ).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organización no encontrada")
    return build_viewer(db, user, org)


def require_perm(permission: str):
    """Fábrica de dependencias: `Depends(require_perm(P_RESULTS_ORG))`."""

    def _dep(viewer: Viewer = Depends(org_viewer)) -> Viewer:
        viewer.require(permission)
        return viewer

    return _dep


def client_ip(request: Request) -> str:
    return (
        request.headers.get("cf-connecting-ip")
        or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "?")
    )
