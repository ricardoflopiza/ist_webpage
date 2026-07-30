# -*- coding: utf-8 -*-
"""Configuración de pruebas.

Las variables de entorno se fijan ANTES de importar `app`, porque la
configuración se resuelve al importar el paquete.
"""
from __future__ import annotations

import os
import pathlib
import tempfile

_TMP = tempfile.mkdtemp(prefix="clima-tests-")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_TMP}/test.db",
    "SESSION_SECRET": "secreto-de-pruebas-no-usar-en-produccion",
    "SECURE_COOKIES": "0",
    "SEED_DEMO": "0",
    "ENVIRONMENT": "development",
    "PUBLIC_BASE_URL": "http://testserver",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, engine, tenant_scope  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Base, Organization, OrganizationMembership, OrgUnit, PlatformUser,
)
from app.models.org import ROLE_CONSULTANT, UNIT_DEPARTMENT  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402
from app.security.sessions import reset_rate_limit  # noqa: E402
from app.services.catalog import seed_services  # noqa: E402
from app.services.library import build_library  # noqa: E402

PASSWORD = "clave-de-prueba-123"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        build_library(db)
        seed_services(db)
    finally:
        db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _clean_rate_limit():
    reset_rate_limit()
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------------ fábricas
_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


@pytest.fixture()
def make_org(db):
    def _make(name: str | None = None, **kwargs) -> Organization:
        n = _next()
        org = Organization(
            slug=kwargs.pop("slug", f"org-{n}"), name=name or f"Organización {n}",
            sector=kwargs.pop("sector", "Servicios"), **kwargs,
        )
        db.add(org)
        db.commit()
        return org
    return _make


@pytest.fixture()
def make_user(db):
    def _make(role: str = ROLE_CONSULTANT, org: Organization | None = None,
              superadmin: bool = False, scope_unit_ids=None) -> PlatformUser:
        n = _next()
        user = PlatformUser(
            email=f"user{n}@test.cl", full_name=f"Persona {n}",
            password_hash=hash_password(PASSWORD), is_superadmin=superadmin,
        )
        db.add(user)
        db.flush()
        if org is not None:
            db.add(OrganizationMembership(
                organization_id=org.id, user_id=user.id, role=role,
                scope_unit_ids=scope_unit_ids,
            ))
        db.commit()
        return user
    return _make


@pytest.fixture()
def make_unit(db):
    def _make(org: Organization, name: str = "Área", kind: str = UNIT_DEPARTMENT,
              headcount: int = 30, parent_id: str | None = None) -> OrgUnit:
        with tenant_scope(org.id):
            unit = OrgUnit(organization_id=org.id, kind=kind, name=name,
                           code=f"u{_next()}", headcount=headcount, parent_id=parent_id)
            db.add(unit)
            db.commit()
        return unit
    return _make


@pytest.fixture()
def login(client):
    def _login(user: PlatformUser):
        r = client.post("/entrar", data={"email": user.email, "password": PASSWORD,
                                         "next": "/app"}, follow_redirects=False)
        assert r.status_code == 303, r.text
        return client
    return _login


@pytest.fixture()
def tmpdir_path() -> pathlib.Path:
    return pathlib.Path(_TMP)
