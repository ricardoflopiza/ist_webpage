# -*- coding: utf-8 -*-
"""Matriz de permisos granulares (§3).

El frontend puede ocultar botones, pero la decisión vive **aquí** y la aplica la
API en cada endpoint. Un permiso ausente es un 403, no un elemento invisible.

Nota sobre respuestas individuales: NINGÚN rol tiene `response.raw.read` en su
conjunto por defecto — ni el superadministrador. Es una capacidad técnica
excepcional que exige justificación escrita y queda auditada
(`services/audit.py::log_raw_access`).
"""
from __future__ import annotations

from ..models.org import (
    ROLE_ANALYST,
    ROLE_CLIENT_ADMIN,
    ROLE_CONSULTANT,
    ROLE_LEADER,
    ROLE_PARTICIPANT,
    ROLE_SUPERADMIN,
)

# --------------------------------------------------------------- plataforma
P_ORG_CREATE = "platform.org.create"
P_PLAN_MANAGE = "platform.plan.manage"
P_GLOBAL_USERS = "platform.users.manage"
P_MASTER_TEMPLATES = "platform.templates.manage"
P_USAGE_METRICS = "platform.metrics.view"
P_BENCHMARK_MANAGE = "platform.benchmarks.manage"
P_AUDIT_VIEW = "platform.audit.view"
P_SERVICES_MANAGE = "platform.services.manage"
P_CONSOLE_VIEW = "platform.console.view"          # panel de la consultora
P_LEADS_VIEW = "platform.leads.view"

# --------------------------------------------------------------- organización
P_ORG_VIEW = "org.view"
P_ORG_MANAGE = "org.manage"
P_ORG_USERS = "org.users.manage"
P_STRUCTURE_MANAGE = "org.structure.manage"
P_POPULATION_MANAGE = "org.population.manage"

# --------------------------------------------------------------- instrumentos
P_TEMPLATE_VIEW = "template.view"
P_TEMPLATE_MANAGE = "template.manage"
P_TEMPLATE_PUBLISH = "template.publish"

# --------------------------------------------------------------- campañas
P_CAMPAIGN_VIEW = "campaign.view"
P_CAMPAIGN_MANAGE = "campaign.manage"
P_CAMPAIGN_PUBLISH = "campaign.publish"
P_CAMPAIGN_CLOSE = "campaign.close"
P_INVITATION_MANAGE = "campaign.invitations.manage"
P_PARTICIPATION_VIEW = "campaign.participation.view"

# --------------------------------------------------------------- resultados
P_RESULTS_ORG = "results.view.org"        # toda la organización
P_RESULTS_UNIT = "results.view.unit"      # sólo unidades del propio alcance
P_RESULTS_PUBLISH = "results.publish"
P_COMMENTS_VIEW = "comments.view"
P_COMMENTS_MANAGE = "comments.manage"
P_COMMENTS_SENSITIVE = "comments.sensitive.view"
P_DRIVERS_VIEW = "results.drivers.view"

# --------------------------------------------------------------- consultoría
P_FINDING_VIEW = "finding.view"
P_FINDING_MANAGE = "finding.manage"
P_FINDING_VALIDATE = "finding.validate"
P_ACTION_VIEW = "action.view"
P_ACTION_MANAGE = "action.manage"
P_ACTION_UPDATE = "action.update"         # avance/evidencia de las propias acciones
P_PULSE_MANAGE = "pulse.manage"
P_REPORT_VIEW = "report.view"
P_REPORT_GENERATE = "report.generate"
P_REPORT_EXPORT = "report.export"
P_BENCHMARK_VIEW = "benchmark.view"
P_ENGAGEMENT_MANAGE = "engagement.manage"

# --------------------------------------------------------------- excepcional
P_RAW_RESPONSE = "response.raw.read"      # no asignado a ningún rol

_CLIENT_ADMIN = {
    P_ORG_VIEW, P_ORG_USERS, P_STRUCTURE_MANAGE, P_POPULATION_MANAGE,
    P_TEMPLATE_VIEW, P_CAMPAIGN_VIEW, P_CAMPAIGN_MANAGE, P_INVITATION_MANAGE,
    P_PARTICIPATION_VIEW, P_RESULTS_ORG, P_COMMENTS_VIEW, P_DRIVERS_VIEW,
    P_FINDING_VIEW, P_ACTION_VIEW, P_ACTION_MANAGE, P_ACTION_UPDATE,
    P_REPORT_VIEW, P_REPORT_EXPORT, P_BENCHMARK_VIEW,
}

_CONSULTANT = _CLIENT_ADMIN | {
    P_ORG_MANAGE, P_TEMPLATE_MANAGE, P_TEMPLATE_PUBLISH, P_CAMPAIGN_PUBLISH,
    P_CAMPAIGN_CLOSE, P_RESULTS_PUBLISH, P_COMMENTS_MANAGE, P_COMMENTS_SENSITIVE,
    P_FINDING_MANAGE, P_FINDING_VALIDATE, P_PULSE_MANAGE, P_REPORT_GENERATE,
    P_ENGAGEMENT_MANAGE, P_CONSOLE_VIEW,
}

_LEADER = {
    P_ORG_VIEW, P_CAMPAIGN_VIEW, P_PARTICIPATION_VIEW, P_RESULTS_UNIT,
    P_FINDING_VIEW, P_ACTION_VIEW, P_ACTION_UPDATE, P_REPORT_VIEW,
}

_ANALYST = {
    P_ORG_VIEW, P_CAMPAIGN_VIEW, P_PARTICIPATION_VIEW, P_RESULTS_ORG,
    P_COMMENTS_VIEW, P_DRIVERS_VIEW, P_FINDING_VIEW, P_ACTION_VIEW,
    P_REPORT_VIEW, P_BENCHMARK_VIEW,
}

_PARTICIPANT: set[str] = set()   # responde encuestas; sólo ve resultados publicados

_SUPERADMIN = (
    _CONSULTANT
    | {
        P_ORG_CREATE, P_PLAN_MANAGE, P_GLOBAL_USERS, P_MASTER_TEMPLATES,
        P_USAGE_METRICS, P_BENCHMARK_MANAGE, P_AUDIT_VIEW, P_SERVICES_MANAGE,
        P_CONSOLE_VIEW, P_LEADS_VIEW,
    }
)

ROLE_PERMISSIONS: dict[str, set[str]] = {
    ROLE_SUPERADMIN: _SUPERADMIN,
    ROLE_CONSULTANT: _CONSULTANT,
    ROLE_CLIENT_ADMIN: _CLIENT_ADMIN,
    ROLE_LEADER: _LEADER,
    ROLE_ANALYST: _ANALYST,
    ROLE_PARTICIPANT: _PARTICIPANT,
}

# Roles que pueden ver resultados sin restricción de unidad propia.
WHOLE_ORG_VIEWERS = (ROLE_SUPERADMIN, ROLE_CONSULTANT, ROLE_CLIENT_ADMIN, ROLE_ANALYST)


def permissions_for(role: str) -> set[str]:
    return set(ROLE_PERMISSIONS.get(role, set()))


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())
