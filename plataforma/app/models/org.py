# -*- coding: utf-8 -*-
"""Usuarios de plataforma, organizaciones, estructura organizacional y nómina."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, PlatformOrTenantScoped, TenantScoped, Timestamps, UUIDPk

# --------------------------------------------------------------- roles
ROLE_SUPERADMIN = "superadmin"        # plataforma
ROLE_CONSULTANT = "consultant"        # consultora, sobre clientes asignados
ROLE_CLIENT_ADMIN = "client_admin"    # administrador del cliente
ROLE_LEADER = "leader"                # jefatura / líder de equipo
ROLE_PARTICIPANT = "participant"      # persona que responde
ROLE_ANALYST = "analyst"              # lector de reportes

ORG_ROLES = (ROLE_CONSULTANT, ROLE_CLIENT_ADMIN, ROLE_LEADER, ROLE_ANALYST, ROLE_PARTICIPANT)

# --------------------------------------------------------------- tipos de unidad
UNIT_BUSINESS = "business_unit"   # BusinessUnit
UNIT_WORKPLACE = "workplace"      # Workplace / sede
UNIT_DEPARTMENT = "department"    # Department
UNIT_TEAM = "team"                # Team
UNIT_KINDS = (UNIT_BUSINESS, UNIT_WORKPLACE, UNIT_DEPARTMENT, UNIT_TEAM)


class PlatformUser(UUIDPk, Timestamps, Base):
    """Persona con credenciales en la plataforma (consultora o cliente)."""

    __tablename__ = "platform_users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list[OrganizationMembership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Organization(UUIDPk, Timestamps, Base):
    """Tenant. Toda entidad de negocio cuelga de aquí."""

    __tablename__ = "organizations"

    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(200))
    sector: Mapped[str | None] = mapped_column(String(80))          # para benchmarks
    org_type: Mapped[str | None] = mapped_column(String(80))        # privada, pública, ONG…
    region: Mapped[str | None] = mapped_column(String(80))
    size_bucket: Mapped[str | None] = mapped_column(String(40))     # 1-50, 51-200, …
    logo_url: Mapped[str | None] = mapped_column(String(400))
    plan: Mapped[str] = mapped_column(String(40), default="esencial", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Confidencialidad: parametrizable por tenant, nunca por debajo del mínimo legal interno.
    anonymity_threshold: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    min_item_completion: Mapped[float] = mapped_column(default=0.6, nullable=False)
    benchmark_consent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text)


class OrganizationMembership(UUIDPk, Timestamps, TenantScoped, Base):
    """Vínculo usuario ↔ organización con un rol. Un usuario puede servir a varias."""

    __tablename__ = "organization_memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_membership"),)

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    # Para jefaturas: unidades cuyos resultados puede ver (lista de org_unit_id).
    scope_unit_ids: Mapped[list | None] = mapped_column(default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[PlatformUser] = relationship(back_populates="memberships")


class OrgUnit(UUIDPk, Timestamps, TenantScoped, Base):
    """Unidad organizacional jerárquica.

    Decisión de diseño: en lugar de cuatro tablas (BusinessUnit, Workplace,
    Department, Team) se usa **una** tabla auto-referenciada con el campo `kind`.
    Motivo: los cuatro niveles comparten exactamente el mismo comportamiento
    (filtros, agregación de resultados, umbral de anonimato, permisos de jefatura)
    y la profundidad real varía por cliente — hay organizaciones sin sedes y otras
    con dos niveles de gerencia. Cuatro tablas obligarían a cuadruplicar cada
    consulta de agregación y romperían el umbral al cruzar niveles. Los cuatro
    nombres del encargo se conservan como `kind` (UNIT_BUSINESS, UNIT_WORKPLACE,
    UNIT_DEPARTMENT, UNIT_TEAM) y se exponen así en la API y la interfaz.
    """

    __tablename__ = "org_units"

    kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    code: Mapped[str | None] = mapped_column(String(60), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("org_units.id", ondelete="SET NULL"), index=True
    )
    leader_user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("platform_users.id", ondelete="SET NULL")
    )
    headcount: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    parent: Mapped[OrgUnit | None] = relationship(remote_side="OrgUnit.id")


class EmployeePopulation(UUIDPk, Timestamps, TenantScoped, Base):
    """Nómina: universo invitable.

    Vive **separada** de las respuestas. Ninguna tabla de respuestas apunta aquí:
    ver `docs/flujos/03-aplicacion-anonima.md`. Los atributos de segmentación se
    copian a la respuesta como fotografía sin identidad al momento de iniciarla.
    """

    __tablename__ = "employee_population"
    __table_args__ = (
        UniqueConstraint("organization_id", "external_id", name="uq_population_external"),
    )

    external_id: Mapped[str | None] = mapped_column(String(80), index=True)  # id de RR.HH.
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    full_name: Mapped[str | None] = mapped_column(String(200))
    org_unit_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("org_units.id", ondelete="SET NULL"), index=True
    )
    # Variables de segmentación. Claves controladas en `segmentation_keys` de la campaña.
    attributes: Mapped[dict | None] = mapped_column(default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ConsultingService(UUIDPk, Timestamps, PlatformOrTenantScoped, Base):
    """Catálogo administrable de servicios (§21). Precios en CLP, o 'Cotizar'."""

    __tablename__ = "consulting_services"

    code: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    includes: Mapped[list | None] = mapped_column(default=None)
    price_clp: Mapped[int | None] = mapped_column(Integer)   # None ⇒ "Cotizar"
    price_note: Mapped[str | None] = mapped_column(String(160))
    family: Mapped[str | None] = mapped_column(String(60))   # paquete | servicio
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ConsultingEngagement(UUIDPk, Timestamps, TenantScoped, Base):
    """Contratación concreta de un servicio por una organización."""

    __tablename__ = "consulting_engagements"

    service_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("consulting_services.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="propuesta", nullable=False)
    stage: Mapped[str] = mapped_column(String(40), default="configurado", nullable=False)
    lead_consultant_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("platform_users.id", ondelete="SET NULL")
    )
    starts_on: Mapped[dt.date | None] = mapped_column()
    ends_on: Mapped[dt.date | None] = mapped_column()
    amount_clp: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)


class Lead(UUIDPk, Timestamps, Base):
    """Solicitud de contacto desde la página pública (§4). No es de ningún tenant."""

    __tablename__ = "leads"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    organization: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bucket: Mapped[str | None] = mapped_column(String(60))
    need: Mapped[str | None] = mapped_column(String(120))
    message: Mapped[str | None] = mapped_column(Text)
    source_ip: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40), default="nuevo", nullable=False)
