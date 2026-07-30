# -*- coding: utf-8 -*-
"""Motor, sesión y guardas de aislamiento multitenant.

El filtrado por organización NO depende de que cada desarrollador se acuerde de
agregar `.where(organization_id == ...)`: se aplica de forma central mediante
`do_orm_execute` + `with_loader_criteria` (patrón oficial de SQLAlchemy) a toda
consulta ORM sobre entidades marcadas como `TenantScoped`, y se valida además en
escritura con un hook `before_flush`.

Escapar del filtro es explícito y visible: `.execution_options(include_all=True)`.
Sólo servicios de plataforma (benchmarks anonimizados, panel de la consultora,
auditoría) tienen derecho a usarlo.
"""
from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker, with_loader_criteria

from .config import settings

# ------------------------------------------------------------------ engine
_connect_args = {}
if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)

if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _rec):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

# ------------------------------------------------------------------ contexto de tenant
_current_org: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_org", default=None
)


def current_org_id() -> str | None:
    return _current_org.get()


@contextlib.contextmanager
def tenant_scope(organization_id: str | None) -> Iterator[None]:
    """Activa (o desactiva, con None) el aislamiento por organización.

    Se usa desde las dependencias HTTP, desde tareas asíncronas y desde los seeds.
    Al salir restaura el valor previo, así que anida sin sorpresas.
    """
    token = _current_org.set(organization_id)
    try:
        yield
    finally:
        _current_org.reset(token)


class TenantIsolationError(RuntimeError):
    """Se intentó escribir una fila de otra organización que la del contexto."""


# ------------------------------------------------------------------ guardas
def install_guards() -> None:
    """Registra los listeners. Se llama una vez al importar `app.models`."""
    from .models.base import PlatformOrTenantScoped, TenantScoped

    @event.listens_for(Session, "do_orm_execute")
    def _apply_tenant_filter(execute_state):  # pragma: no cover - cubierto vía API
        if execute_state.is_column_load or execute_state.is_relationship_load:
            return
        if execute_state.execution_options.get("include_all", False):
            return
        org_id = current_org_id()
        if org_id is None:
            return
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                TenantScoped,
                lambda cls: cls.organization_id == org_id,
                include_aliases=True,
            ),
            with_loader_criteria(
                PlatformOrTenantScoped,
                lambda cls: (cls.organization_id == org_id)
                | (cls.organization_id.is_(None)),
                include_aliases=True,
            ),
        )

    @event.listens_for(Session, "before_flush")
    def _guard_writes(session, _ctx, _instances):  # pragma: no cover - cubierto vía tests
        org_id = current_org_id()
        if org_id is None:
            return
        for obj in list(session.new) + list(session.dirty):
            if isinstance(obj, TenantScoped):
                if obj.organization_id is None:
                    obj.organization_id = org_id
                elif obj.organization_id != org_id:
                    raise TenantIsolationError(
                        f"{type(obj).__name__} pertenece a {obj.organization_id} "
                        f"pero el contexto activo es {org_id}"
                    )


def get_session() -> Iterator[Session]:
    """Dependencia FastAPI: una sesión por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
