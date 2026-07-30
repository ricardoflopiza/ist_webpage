# -*- coding: utf-8 -*-
"""Organizaciones, estructura organizacional y nómina."""
from __future__ import annotations

import csv
import io
import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_session
from ..models import EmployeePopulation, Organization, OrganizationMembership, OrgUnit
from ..models.org import ROLE_CLIENT_ADMIN, UNIT_KINDS
from ..security.deps import Viewer, org_viewer, platform_viewer, require_perm
from ..security.permissions import (
    P_ORG_CREATE,
    P_ORG_MANAGE,
    P_ORG_VIEW,
    P_POPULATION_MANAGE,
    P_STRUCTURE_MANAGE,
)
from ..services import audit as audit_svc
from . import API_PREFIX

router = APIRouter(prefix=f"{API_PREFIX}", tags=["organizaciones"])
ALL = {"include_all": True}
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


# ------------------------------------------------------------------ esquemas
class OrganizationIn(BaseModel):
    slug: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=200)
    legal_name: str | None = None
    sector: str | None = None
    org_type: str | None = None
    region: str | None = None
    size_bucket: str | None = None
    plan: str = "esencial"
    anonymity_threshold: int = Field(default=7, ge=3, le=50)
    min_item_completion: float = Field(default=0.6, ge=0.1, le=1.0)
    benchmark_consent: bool = False


class OrganizationUpdate(BaseModel):
    name: str | None = None
    legal_name: str | None = None
    sector: str | None = None
    org_type: str | None = None
    region: str | None = None
    size_bucket: str | None = None
    plan: str | None = None
    anonymity_threshold: int | None = Field(default=None, ge=3, le=50)
    min_item_completion: float | None = Field(default=None, ge=0.1, le=1.0)
    benchmark_consent: bool | None = None
    logo_url: str | None = None
    notes: str | None = None


class UnitIn(BaseModel):
    kind: str
    name: str = Field(min_length=1, max_length=200)
    code: str | None = None
    parent_id: str | None = None
    leader_user_id: str | None = None
    headcount: int | None = None


class PersonIn(BaseModel):
    external_id: str | None = None
    email: str | None = None
    full_name: str | None = None
    org_unit_id: str | None = None
    attributes: dict = Field(default_factory=dict)


def _org_dict(o: Organization) -> dict:
    return {
        "slug": o.slug, "name": o.name, "legal_name": o.legal_name, "sector": o.sector,
        "org_type": o.org_type, "region": o.region, "size_bucket": o.size_bucket,
        "plan": o.plan, "is_demo": o.is_demo, "is_active": o.is_active,
        "anonymity_threshold": o.anonymity_threshold,
        "min_item_completion": o.min_item_completion,
        "benchmark_consent": o.benchmark_consent, "logo_url": o.logo_url,
    }


# ------------------------------------------------------------------ organizaciones
@router.get("/organizations", summary="Organizaciones visibles para quien consulta")
def list_organizations(viewer: Viewer = Depends(platform_viewer), db: Session = Depends(get_session)):
    from .platform import _visible_org_ids

    ids = _visible_org_ids(db, viewer)
    stmt = select(Organization).order_by(Organization.name)
    if ids is not None:
        stmt = stmt.where(Organization.id.in_(ids or [""]))
    rows = db.execute(stmt.execution_options(**ALL)).scalars().all()
    return {"items": [_org_dict(o) for o in rows], "total": len(rows)}


@router.post("/organizations", status_code=201, summary="Crear organización (tenant)")
def create_organization(payload: OrganizationIn, viewer: Viewer = Depends(platform_viewer),
                        db: Session = Depends(get_session)):
    viewer.require(P_ORG_CREATE)
    if not _SLUG.match(payload.slug):
        raise HTTPException(status_code=422, detail="El identificador debe ser minúsculas, números o guiones")
    if db.execute(select(Organization).where(Organization.slug == payload.slug)
                  .execution_options(**ALL)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Ya existe una organización con ese identificador")
    org = Organization(**payload.model_dump())
    db.add(org)
    db.commit()
    audit_svc.log(db, "organizacion_creada", organization_id=org.id, user_id=viewer.user.id,
                  actor_email=viewer.user.email, entity="organization", entity_id=org.id)
    return _org_dict(org)


@router.get("/o/{org_slug}", summary="Ficha de la organización")
def get_organization(viewer: Viewer = Depends(org_viewer)):
    viewer.require(P_ORG_VIEW)
    return _org_dict(viewer.organization)


@router.patch("/o/{org_slug}", summary="Actualizar la organización")
def update_organization(payload: OrganizationUpdate,
                        viewer: Viewer = Depends(require_perm(P_ORG_MANAGE)),
                        db: Session = Depends(get_session)):
    org = viewer.organization
    data = payload.model_dump(exclude_none=True)
    if "anonymity_threshold" in data and data["anonymity_threshold"] < 3:
        raise HTTPException(status_code=422, detail="El umbral de anonimato no puede bajar de 3")
    for k, v in data.items():
        setattr(org, k, v)
    db.commit()
    audit_svc.log_view(db, viewer, "configuracion", entity="organization",
                       entity_id=org.id, detail={"campos": list(data)})
    return _org_dict(org)


# ------------------------------------------------------------------ estructura
@router.get("/o/{org_slug}/units", summary="Estructura organizacional")
def list_units(viewer: Viewer = Depends(require_perm(P_ORG_VIEW)),
               db: Session = Depends(get_session), kind: str | None = None):
    stmt = select(OrgUnit).order_by(OrgUnit.kind, OrgUnit.name)
    if kind:
        stmt = stmt.where(OrgUnit.kind == kind)
    rows = db.execute(stmt).scalars().all()
    return {"items": [
        {"id": u.id, "kind": u.kind, "code": u.code, "name": u.name,
         "parent_id": u.parent_id, "headcount": u.headcount,
         "leader_user_id": u.leader_user_id, "is_active": u.is_active}
        for u in rows
    ], "total": len(rows)}


@router.post("/o/{org_slug}/units", status_code=201, summary="Crear unidad")
def create_unit(payload: UnitIn, viewer: Viewer = Depends(require_perm(P_STRUCTURE_MANAGE)),
                db: Session = Depends(get_session)):
    if payload.kind not in UNIT_KINDS:
        raise HTTPException(status_code=422, detail=f"Tipo de unidad inválido: {payload.kind}")
    if payload.parent_id and not db.get(OrgUnit, payload.parent_id):
        raise HTTPException(status_code=422, detail="La unidad superior no existe")
    unit = OrgUnit(organization_id=viewer.organization.id, **payload.model_dump())
    db.add(unit)
    db.commit()
    return {"id": unit.id, "name": unit.name, "kind": unit.kind}


@router.patch("/o/{org_slug}/units/{unit_id}", summary="Actualizar unidad")
def update_unit(unit_id: str, payload: UnitIn,
                viewer: Viewer = Depends(require_perm(P_STRUCTURE_MANAGE)),
                db: Session = Depends(get_session)):
    unit = db.get(OrgUnit, unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unidad no encontrada")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(unit, k, v)
    db.commit()
    return {"id": unit.id, "name": unit.name}


@router.delete("/o/{org_slug}/units/{unit_id}", summary="Desactivar unidad")
def deactivate_unit(unit_id: str, viewer: Viewer = Depends(require_perm(P_STRUCTURE_MANAGE)),
                    db: Session = Depends(get_session)):
    unit = db.get(OrgUnit, unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unidad no encontrada")
    unit.is_active = False
    db.commit()
    return {"id": unit.id, "is_active": False}


# ------------------------------------------------------------------ nómina
@router.get("/o/{org_slug}/population", summary="Nómina (universo invitable)")
def list_population(viewer: Viewer = Depends(require_perm(P_POPULATION_MANAGE)),
                    db: Session = Depends(get_session), limit: int = 100, offset: int = 0):
    rows = db.execute(
        select(EmployeePopulation).order_by(EmployeePopulation.external_id)
        .limit(limit).offset(offset)
    ).scalars().all()
    total = db.query(EmployeePopulation).count()
    return {"items": [
        {"id": p.id, "external_id": p.external_id, "email": p.email, "full_name": p.full_name,
         "org_unit_id": p.org_unit_id, "attributes": p.attributes, "is_active": p.is_active}
        for p in rows
    ], "total": total, "limit": limit, "offset": offset}


@router.post("/o/{org_slug}/population", status_code=201, summary="Agregar persona a la nómina")
def add_person(payload: PersonIn, viewer: Viewer = Depends(require_perm(P_POPULATION_MANAGE)),
               db: Session = Depends(get_session)):
    person = EmployeePopulation(organization_id=viewer.organization.id, **payload.model_dump())
    db.add(person)
    db.commit()
    return {"id": person.id}


@router.post("/o/{org_slug}/population/import", summary="Cargar nómina desde CSV")
def import_population(file: UploadFile = File(...),
                      viewer: Viewer = Depends(require_perm(P_POPULATION_MANAGE)),
                      db: Session = Depends(get_session)):
    """CSV con cabecera. Columnas reconocidas: `external_id`, `email`, `full_name`,
    `unidad` (código de unidad) y cualquier otra columna, que se guarda como
    variable de segmentación."""
    raw = file.file.read().decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    units = {u.code: u.id for u in db.execute(select(OrgUnit)).scalars() if u.code}
    known = {"external_id", "email", "full_name", "unidad", "nombre", "correo", "id_externo"}
    created = updated = 0
    for row in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        ext = row.get("external_id") or row.get("id_externo") or row.get("email") or row.get("correo")
        if not ext:
            continue
        attrs = {k: v for k, v in row.items() if k and k not in known and v}
        person = db.execute(
            select(EmployeePopulation).where(EmployeePopulation.external_id == ext)
        ).scalar_one_or_none()
        if person is None:
            person = EmployeePopulation(organization_id=viewer.organization.id, external_id=ext)
            db.add(person)
            created += 1
        else:
            updated += 1
        person.email = row.get("email") or row.get("correo") or person.email
        person.full_name = row.get("full_name") or row.get("nombre") or person.full_name
        unit_code = row.get("unidad")
        if unit_code and unit_code in units:
            person.org_unit_id = units[unit_code]
        person.attributes = {**(person.attributes or {}), **attrs}
        person.is_active = True
    db.commit()
    audit_svc.log_view(db, viewer, "carga_nomina", entity="employee_population",
                       detail={"creadas": created, "actualizadas": updated})
    return {"created": created, "updated": updated}


@router.get("/o/{org_slug}/segmentation-keys", summary="Variables de segmentación disponibles")
def segmentation_keys(viewer: Viewer = Depends(require_perm(P_ORG_VIEW)),
                      db: Session = Depends(get_session)):
    keys: dict[str, set] = {}
    for p in db.execute(select(EmployeePopulation).limit(2000)).scalars():
        for k, v in (p.attributes or {}).items():
            keys.setdefault(k, set()).add(str(v))
    return {"items": [
        {"key": k, "values": sorted(v)[:50], "n_values": len(v)}
        for k, v in sorted(keys.items())
    ]}


@router.post("/o/{org_slug}/members/invite-admin", status_code=201,
             summary="Invitar al administrador del cliente")
def invite_admin(email: str, full_name: str,
                 viewer: Viewer = Depends(require_perm(P_ORG_MANAGE)),
                 db: Session = Depends(get_session)):
    from ..models import PlatformUser
    from ..security.passwords import generate_password, hash_password

    email = email.strip().lower()
    user = db.execute(
        select(PlatformUser).where(PlatformUser.email == email).execution_options(**ALL)
    ).scalar_one_or_none()
    temporary = None
    if not user:
        temporary = generate_password()
        user = PlatformUser(email=email, full_name=full_name, password_hash=hash_password(temporary))
        db.add(user)
        db.flush()
    if not db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.organization_id == viewer.organization.id,
        )
    ).scalar_one_or_none():
        db.add(OrganizationMembership(
            organization_id=viewer.organization.id, user_id=user.id, role=ROLE_CLIENT_ADMIN,
        ))
    db.commit()
    audit_svc.log_view(db, viewer, "invitacion_administrador", entity="platform_user",
                       entity_id=user.id, detail={"email": email})
    # La contraseña temporal se devuelve una sola vez, para entregarla por un
    # canal seguro. No hay envío de correo configurado en este entorno.
    return {"user_id": user.id, "email": email, "temporary_password": temporary,
            "login_url": f"{settings.public_base_url}/entrar"}
