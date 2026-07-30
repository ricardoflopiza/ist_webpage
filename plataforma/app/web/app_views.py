# -*- coding: utf-8 -*-
"""Aplicación autenticada: consola de la consultora y espacio de cada cliente."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import (
    ActionItem,
    ActionPlan,
    Benchmark,
    ConsultingService,
    EmployeePopulation,
    Finding,
    OrgUnit,
    PulseSurvey,
    SurveyCampaign,
    SurveyTemplate,
)
from ..models.campaign import RESULT_STATES
from ..security.deps import Viewer, org_viewer, platform_viewer
from ..security.permissions import (
    P_ACTION_VIEW,
    P_AUDIT_VIEW,
    P_CAMPAIGN_VIEW,
    P_COMMENTS_VIEW,
    P_CONSOLE_VIEW,
    P_FINDING_VIEW,
    P_ORG_MANAGE,
    P_ORG_VIEW,
    P_PARTICIPATION_VIEW,
    P_RESULTS_ORG,
    P_RESULTS_UNIT,
    P_TEMPLATE_VIEW,
)
from ..services import audit as audit_svc
from ..services import results as results_svc
from ..templating import templates

router = APIRouter(prefix="/app", tags=["aplicación"], include_in_schema=False)
ALL = {"include_all": True}

MENU = [
    ("inicio", "Inicio", "", None),
    ("resultados", "Resultados", "resultados", P_RESULTS_ORG),
    ("participacion", "Participación", "participacion", P_PARTICIPATION_VIEW),
    ("campanas", "Campañas", "campanas", P_CAMPAIGN_VIEW),
    ("encuestas", "Encuestas", "encuestas", P_TEMPLATE_VIEW),
    ("comentarios", "Comentarios", "comentarios", P_COMMENTS_VIEW),
    ("hallazgos", "Hallazgos", "hallazgos", P_FINDING_VIEW),
    ("acciones", "Planes de acción", "acciones", P_ACTION_VIEW),
    ("pulsos", "Pulsos", "pulsos", P_CAMPAIGN_VIEW),
    ("reportes", "Reportes", "reportes", P_RESULTS_ORG),
    ("estructura", "Estructura y nómina", "estructura", P_ORG_VIEW),
    ("servicios", "Servicios", "servicios", P_ORG_VIEW),
    ("benchmarks", "Benchmarks", "benchmarks", P_ORG_VIEW),
    ("usuarios", "Usuarios", "usuarios", P_ORG_VIEW),
    ("configuracion", "Configuración", "configuracion", P_ORG_MANAGE),
    ("auditoria", "Auditoría", "auditoria", P_ORG_MANAGE),
]


def _menu(viewer: Viewer) -> list[dict]:
    out = []
    for key, label, path, perm in MENU:
        if perm and not viewer.can(perm):
            if key == "resultados" and viewer.can(P_RESULTS_UNIT):
                pass   # una jefatura ve resultados, limitados a su alcance
            else:
                continue
        out.append({"key": key, "label": label, "path": path})
    return out


def _ctx(request: Request, viewer: Viewer, active: str, **extra) -> dict:
    org = viewer.organization
    return {
        "request": request, "viewer": viewer, "org": org, "active": active,
        "menu": _menu(viewer), "base": f"/app/o/{org.slug}" if org else "/app",
        **extra,
    }


def _current_campaign(db: Session, campaign_id: str | None = None) -> SurveyCampaign | None:
    if campaign_id:
        return db.get(SurveyCampaign, campaign_id)
    rows = db.execute(
        select(SurveyCampaign).order_by(SurveyCampaign.created_at.desc())
    ).scalars().all()
    with_results = [c for c in rows if c.status in RESULT_STATES and not c.is_pulse]
    return with_results[0] if with_results else (rows[0] if rows else None)


# ------------------------------------------------------------------ consola
@router.get("")
def console(request: Request, viewer: Viewer = Depends(platform_viewer),
            db: Session = Depends(get_session)):
    if not viewer.can(P_CONSOLE_VIEW):
        # Clientes y jefaturas entran directo a su organización.
        from ..models import Organization, OrganizationMembership

        m = db.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == viewer.user.id,
                OrganizationMembership.is_active.is_(True),
            ).execution_options(**ALL)
        ).scalars().first()
        if not m:
            raise HTTPException(status_code=403, detail="Sin organizaciones asignadas")
        org = db.execute(
            select(Organization).where(Organization.id == m.organization_id)
            .execution_options(**ALL)
        ).scalar_one()
        from fastapi.responses import RedirectResponse
        return RedirectResponse(f"/app/o/{org.slug}", status_code=303)

    from ..api.platform import activity, overview
    data = overview(viewer, db)
    return templates.TemplateResponse("app/console.html", {
        "request": request, "viewer": viewer, "data": data,
        "activity": activity(viewer, db, 15)["items"],
    })


# ------------------------------------------------------------------ cliente
@router.get("/o/{org_slug}")
def org_home(request: Request, viewer: Viewer = Depends(org_viewer),
             db: Session = Depends(get_session), campaign_id: str | None = None):
    viewer.require(P_ORG_VIEW)
    campaign = _current_campaign(db, campaign_id)
    campaigns = db.execute(
        select(SurveyCampaign).order_by(SurveyCampaign.created_at.desc())
    ).scalars().all()
    summary = None
    decision = None
    if campaign:
        decision, payload = results_svc.results_for_viewer(db, campaign, viewer)
        if decision.allowed:
            dims = sorted([d for d in payload["dimensions"] if d["score"] is not None],
                          key=lambda d: d["score"], reverse=True)
            summary = {
                "payload": payload, "strengths": dims[:3], "alerts": dims[-3:][::-1],
                "levers": (payload.get("priority_matrix") or {}).get("points", [])[:3],
            }
    items = db.execute(select(ActionItem)).scalars().all()
    pulses = db.execute(select(PulseSurvey)).scalars().all()
    units = db.execute(select(OrgUnit).where(OrgUnit.is_active.is_(True))).scalars().all()
    return templates.TemplateResponse("app/org_home.html", _ctx(
        request, viewer, "inicio",
        campaign=campaign, campaigns=campaigns, summary=summary, decision=decision,
        actions={"total": len(items),
                 "overdue": len([i for i in items if i.is_overdue]),
                 "done": len([i for i in items if i.status == "completada"])},
        pulses=pulses, n_units=len(units),
        n_people=db.query(EmployeePopulation).count(),
    ))


@router.get("/o/{org_slug}/resultados")
def results_page(request: Request, viewer: Viewer = Depends(org_viewer),
                 db: Session = Depends(get_session), campaign_id: str | None = None):
    if not (viewer.can(P_RESULTS_ORG) or viewer.can(P_RESULTS_UNIT)):
        raise HTTPException(status_code=403, detail="Sin permiso para ver resultados")
    campaign = _current_campaign(db, campaign_id)
    campaigns = [c for c in db.execute(
        select(SurveyCampaign).order_by(SurveyCampaign.created_at.desc())
    ).scalars() if c.status in RESULT_STATES]
    units = db.execute(
        select(OrgUnit).where(OrgUnit.is_active.is_(True)).order_by(OrgUnit.name)
    ).scalars().all()
    keys: dict[str, set] = {}
    for p in db.execute(select(EmployeePopulation).limit(1500)).scalars():
        for k, v in (p.attributes or {}).items():
            keys.setdefault(k, set()).add(str(v))
    allowed_keys = set(campaign.segmentation_keys or []) if campaign else set()
    return templates.TemplateResponse("app/results.html", _ctx(
        request, viewer, "resultados",
        campaign=campaign, campaigns=campaigns, units=units,
        segmentation={k: sorted(v) for k, v in keys.items() if k in allowed_keys},
    ))


@router.get("/o/{org_slug}/participacion")
def participation_page(request: Request, viewer: Viewer = Depends(org_viewer),
                       db: Session = Depends(get_session), campaign_id: str | None = None):
    viewer.require(P_PARTICIPATION_VIEW)
    campaign = _current_campaign(db, campaign_id)
    campaigns = db.execute(
        select(SurveyCampaign).order_by(SurveyCampaign.created_at.desc())
    ).scalars().all()
    data = None
    if campaign:
        from ..api.campaigns import participation
        data = participation(campaign.id, viewer, db)
    return templates.TemplateResponse("app/participation.html", _ctx(
        request, viewer, "participacion", campaign=campaign, campaigns=campaigns, data=data,
    ))


@router.get("/o/{org_slug}/campanas")
def campaigns_page(request: Request, viewer: Viewer = Depends(org_viewer),
                   db: Session = Depends(get_session)):
    viewer.require(P_CAMPAIGN_VIEW)
    rows = db.execute(
        select(SurveyCampaign).order_by(SurveyCampaign.created_at.desc())
    ).scalars().all()
    templates_ = db.execute(select(SurveyTemplate)).scalars().all()
    return templates.TemplateResponse("app/campaigns.html", _ctx(
        request, viewer, "campanas", campaigns=rows, templates_=templates_,
        participation={c.id: results_svc.participation(db, c) for c in rows},
    ))


@router.get("/o/{org_slug}/encuestas")
def surveys_page(request: Request, viewer: Viewer = Depends(org_viewer),
                 db: Session = Depends(get_session)):
    viewer.require(P_TEMPLATE_VIEW)
    rows = db.execute(
        select(SurveyTemplate).where(SurveyTemplate.is_active.is_(True))
    ).scalars().all()
    return templates.TemplateResponse("app/surveys.html", _ctx(
        request, viewer, "encuestas",
        master=[t for t in rows if t.organization_id is None],
        own=[t for t in rows if t.organization_id is not None],
    ))


@router.get("/o/{org_slug}/comentarios")
def comments_page(request: Request, viewer: Viewer = Depends(org_viewer),
                  db: Session = Depends(get_session), campaign_id: str | None = None):
    viewer.require(P_COMMENTS_VIEW)
    campaign = _current_campaign(db, campaign_id)
    campaigns = db.execute(select(SurveyCampaign)).scalars().all()
    return templates.TemplateResponse("app/comments.html", _ctx(
        request, viewer, "comentarios", campaign=campaign, campaigns=campaigns,
    ))


@router.get("/o/{org_slug}/hallazgos")
def findings_page(request: Request, viewer: Viewer = Depends(org_viewer),
                  db: Session = Depends(get_session)):
    viewer.require(P_FINDING_VIEW)
    rows = db.execute(select(Finding).order_by(Finding.created_at.desc())).scalars().all()
    campaigns = {c.id: c.name for c in db.execute(select(SurveyCampaign)).scalars()}
    return templates.TemplateResponse("app/findings.html", _ctx(
        request, viewer, "hallazgos", findings=rows, campaigns=campaigns,
    ))


@router.get("/o/{org_slug}/acciones")
def actions_page(request: Request, viewer: Viewer = Depends(org_viewer),
                 db: Session = Depends(get_session)):
    viewer.require(P_ACTION_VIEW)
    from ..api.actions import dashboard

    plans = db.execute(select(ActionPlan)).scalars().all()
    findings = {f.id: f.title for f in db.execute(select(Finding)).scalars()}
    return templates.TemplateResponse("app/actions.html", _ctx(
        request, viewer, "acciones", plans=plans, data=dashboard(viewer, db), findings=findings,
    ))


@router.get("/o/{org_slug}/pulsos")
def pulses_page(request: Request, viewer: Viewer = Depends(org_viewer),
                db: Session = Depends(get_session)):
    viewer.require(P_CAMPAIGN_VIEW)
    pulses = db.execute(select(PulseSurvey)).scalars().all()
    campaigns = {c.id: c for c in db.execute(select(SurveyCampaign)).scalars()}
    return templates.TemplateResponse("app/pulses.html", _ctx(
        request, viewer, "pulsos", pulses=pulses, campaigns=campaigns,
    ))


@router.get("/o/{org_slug}/reportes")
def reports_page(request: Request, viewer: Viewer = Depends(org_viewer),
                 db: Session = Depends(get_session), campaign_id: str | None = None):
    if not (viewer.can(P_RESULTS_ORG) or viewer.can(P_RESULTS_UNIT)):
        raise HTTPException(status_code=403, detail="Sin permiso")
    campaign = _current_campaign(db, campaign_id)
    campaigns = [c for c in db.execute(select(SurveyCampaign)).scalars()
                 if c.status in RESULT_STATES]
    units = db.execute(select(OrgUnit).where(OrgUnit.is_active.is_(True))).scalars().all()
    return templates.TemplateResponse("app/reports.html", _ctx(
        request, viewer, "reportes", campaign=campaign, campaigns=campaigns, units=units,
    ))


@router.get("/o/{org_slug}/estructura")
def structure_page(request: Request, viewer: Viewer = Depends(org_viewer),
                   db: Session = Depends(get_session)):
    viewer.require(P_ORG_VIEW)
    units = db.execute(select(OrgUnit).order_by(OrgUnit.kind, OrgUnit.name)).scalars().all()
    return templates.TemplateResponse("app/structure.html", _ctx(
        request, viewer, "estructura", units=units,
        n_people=db.query(EmployeePopulation).count(),
    ))


@router.get("/o/{org_slug}/servicios")
def services_page(request: Request, viewer: Viewer = Depends(org_viewer),
                  db: Session = Depends(get_session)):
    viewer.require(P_ORG_VIEW)
    rows = db.execute(
        select(ConsultingService).where(ConsultingService.is_active.is_(True))
        .order_by(ConsultingService.sort_order).execution_options(**ALL)
    ).scalars().all()
    return templates.TemplateResponse("app/services.html", _ctx(
        request, viewer, "servicios",
        paquetes=[s for s in rows if s.family == "paquete"],
        servicios=[s for s in rows if s.family != "paquete"],
    ))


@router.get("/o/{org_slug}/benchmarks")
def benchmarks_page(request: Request, viewer: Viewer = Depends(org_viewer),
                    db: Session = Depends(get_session)):
    viewer.require(P_ORG_VIEW)
    rows = db.execute(
        select(Benchmark).where(Benchmark.is_published.is_(True)).execution_options(**ALL)
    ).scalars().all()
    return templates.TemplateResponse("app/benchmarks.html", _ctx(
        request, viewer, "benchmarks", benchmarks=rows,
    ))


@router.get("/o/{org_slug}/usuarios")
def users_page(request: Request, viewer: Viewer = Depends(org_viewer),
               db: Session = Depends(get_session)):
    viewer.require(P_ORG_VIEW)
    from ..api.users import list_members

    return templates.TemplateResponse("app/users.html", _ctx(
        request, viewer, "usuarios", members=list_members(viewer, db)["items"],
    ))


@router.get("/o/{org_slug}/configuracion")
def settings_page(request: Request, viewer: Viewer = Depends(org_viewer)):
    viewer.require(P_ORG_MANAGE)
    return templates.TemplateResponse("app/settings.html", _ctx(request, viewer, "configuracion"))


@router.get("/o/{org_slug}/auditoria")
def audit_page(request: Request, viewer: Viewer = Depends(org_viewer),
               db: Session = Depends(get_session)):
    if not (viewer.can(P_ORG_MANAGE) or viewer.can(P_AUDIT_VIEW)):
        raise HTTPException(status_code=403, detail="Sin permiso")
    rows = audit_svc.recent(db, viewer.organization.id, 200)
    return templates.TemplateResponse("app/audit.html", _ctx(
        request, viewer, "auditoria", rows=rows,
    ))
