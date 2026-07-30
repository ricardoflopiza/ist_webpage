# -*- coding: utf-8 -*-
"""Usuarios y membresías por organización."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import OrganizationMembership, OrgUnit, PlatformUser
from ..models.org import ORG_ROLES, ROLE_LEADER
from ..security.deps import Viewer, org_viewer, require_perm
from ..security.passwords import generate_password, hash_password
from ..security.permissions import P_ORG_USERS, P_ORG_VIEW, permissions_for
from ..services import audit as audit_svc
from . import API_PREFIX

router = APIRouter(prefix=f"{API_PREFIX}/o/{{org_slug}}", tags=["usuarios"])
ALL = {"include_all": True}


class MemberIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=160)
    role: str
    scope_unit_ids: list[str] = Field(default_factory=list)


class MemberUpdate(BaseModel):
    role: str | None = None
    scope_unit_ids: list[str] | None = None
    is_active: bool | None = None


@router.get("/members", summary="Miembros de la organización")
def list_members(viewer: Viewer = Depends(require_perm(P_ORG_VIEW)),
                 db: Session = Depends(get_session)):
    rows = db.execute(select(OrganizationMembership)).scalars().all()
    users = {
        u.id: u for u in db.execute(
            select(PlatformUser).where(PlatformUser.id.in_([m.user_id for m in rows] or [""]))
            .execution_options(**ALL)
        ).scalars()
    }
    return {"items": [
        {"id": m.id, "user_id": m.user_id, "email": users[m.user_id].email if m.user_id in users else None,
         "full_name": users[m.user_id].full_name if m.user_id in users else None,
         "role": m.role, "scope_unit_ids": m.scope_unit_ids or [], "is_active": m.is_active,
         "permissions": sorted(permissions_for(m.role))}
        for m in rows
    ], "total": len(rows)}


@router.post("/members", status_code=201, summary="Agregar miembro")
def add_member(payload: MemberIn, viewer: Viewer = Depends(require_perm(P_ORG_USERS)),
               db: Session = Depends(get_session)):
    if payload.role not in ORG_ROLES:
        raise HTTPException(status_code=422, detail=f"Rol inválido: {payload.role}")
    if payload.role == ROLE_LEADER and not payload.scope_unit_ids:
        raise HTTPException(
            status_code=422,
            detail="Una jefatura necesita al menos una unidad en su alcance",
        )
    for uid in payload.scope_unit_ids:
        if not db.get(OrgUnit, uid):
            raise HTTPException(status_code=422, detail="Unidad fuera de la organización")

    email = payload.email.strip().lower()
    user = db.execute(
        select(PlatformUser).where(PlatformUser.email == email).execution_options(**ALL)
    ).scalar_one_or_none()
    temporary = None
    if not user:
        temporary = generate_password()
        user = PlatformUser(email=email, full_name=payload.full_name,
                            password_hash=hash_password(temporary))
        db.add(user)
        db.flush()
    if db.execute(select(OrganizationMembership).where(
            OrganizationMembership.user_id == user.id)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="La persona ya es miembro de esta organización")
    m = OrganizationMembership(
        organization_id=viewer.organization.id, user_id=user.id, role=payload.role,
        scope_unit_ids=payload.scope_unit_ids or None,
    )
    db.add(m)
    db.commit()
    audit_svc.log_view(db, viewer, "miembro_agregado", entity="organization_membership",
                       entity_id=m.id, detail={"rol": payload.role})
    return {"id": m.id, "user_id": user.id, "temporary_password": temporary}


@router.patch("/members/{membership_id}", summary="Actualizar miembro")
def update_member(membership_id: str, payload: MemberUpdate,
                  viewer: Viewer = Depends(require_perm(P_ORG_USERS)),
                  db: Session = Depends(get_session)):
    m = db.get(OrganizationMembership, membership_id)
    if not m or m.organization_id != viewer.organization.id:
        raise HTTPException(status_code=404, detail="Miembro no encontrado")
    data = payload.model_dump(exclude_none=True)
    if data.get("role") and data["role"] not in ORG_ROLES:
        raise HTTPException(status_code=422, detail="Rol inválido")
    for k, v in data.items():
        setattr(m, k, v)
    db.commit()
    audit_svc.log_view(db, viewer, "miembro_actualizado", entity="organization_membership",
                       entity_id=m.id, detail={"campos": list(data)})
    return {"id": m.id, "role": m.role, "is_active": m.is_active}


@router.get("/me", summary="Mi contexto en esta organización")
def me(viewer: Viewer = Depends(org_viewer)):
    return {
        "email": viewer.user.email, "name": viewer.user.full_name,
        "role": viewer.role, "is_superadmin": viewer.is_superadmin,
        "permissions": sorted(viewer.permissions),
        "scope_unit_ids": viewer.scope_unit_ids,
        "organization": viewer.organization.slug if viewer.organization else None,
    }
