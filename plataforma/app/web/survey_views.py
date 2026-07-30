# -*- coding: utf-8 -*-
"""Experiencia de respuesta (§10).

Diseño: una página por dimensión, guardado progresivo en cada avance, barra de
progreso, duración estimada y consentimiento antes de la primera pregunta. Sin
elementos que induzcan respuestas: mismo peso visual para todas las opciones,
sin colores que sugieran cuál es la "buena".
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_session, tenant_scope
from ..models import (
    Organization,
    SurveyCampaign,
    SurveyModule,
    SurveyResponse,
    SurveyTemplateVersion,
)
from ..models.campaign import OPEN_STATES
from ..models.response import R_SUBMITTED
from ..security.sessions import TICKET_COOKIE
from ..security.tokens import token_hash
from ..services import campaigns as svc
from ..services import results as results_svc
from ..services.scales import get_scale
from ..templating import templates

router = APIRouter(tags=["encuesta"], include_in_schema=False)


def _pages(db: Session, campaign: SurveyCampaign) -> list[dict]:
    """Una página por dimensión, en el orden del instrumento."""
    modules = db.execute(
        select(SurveyModule).where(
            SurveyModule.version_id == campaign.version_id, SurveyModule.is_enabled.is_(True)
        ).order_by(SurveyModule.sort_order)
    ).scalars().all()
    pages = []
    for m in modules:
        for d in m.dimensions:
            questions = [{
                "id": q.id, "code": q.code, "text": q.text, "help_text": q.help_text,
                "qtype": q.qtype, "required": q.is_required, "allow_na": q.allow_na,
                "options": q.options,
                "scale": get_scale(q.scale_key) if q.qtype in ("likert", "numeric", "nps") else None,
                "display_logic": q.display_logic,
            } for q in d.questions]
            if questions:
                pages.append({"module": m.name, "dimension": d.name, "questions": questions})
    return pages


def _load_context(db: Session, response_id: str) -> tuple[SurveyResponse, SurveyCampaign, Organization]:
    resp = db.execute(
        select(SurveyResponse).where(SurveyResponse.id == response_id)
        .execution_options(include_all=True)
    ).scalar_one_or_none()
    if not resp:
        raise HTTPException(status_code=404, detail="Respuesta no encontrada")
    campaign = db.execute(
        select(SurveyCampaign).where(SurveyCampaign.id == resp.campaign_id)
        .execution_options(include_all=True)
    ).scalar_one()
    org = db.execute(
        select(Organization).where(Organization.id == resp.organization_id)
        .execution_options(include_all=True)
    ).scalar_one()
    return resp, campaign, org


def _ticket_from(request: Request) -> str | None:
    return request.cookies.get(TICKET_COOKIE)


def _set_ticket(response, ticket: str):
    response.set_cookie(
        TICKET_COOKIE, ticket, max_age=settings.response_ticket_ttl,
        httponly=True, samesite="lax", secure=settings.secure_cookies, path="/",
    )
    return response


# ------------------------------------------------------------------ acceso
@router.get("/e/{token}")
def open_with_token(token: str, request: Request, db: Session = Depends(get_session)):
    """Canjea el enlace personal por una respuesta anónima."""
    ticket = _ticket_from(request)
    if ticket:
        existing = svc.resume(db, ticket)
        if existing:
            return RedirectResponse(f"/responder/{existing.id}", status_code=303)
    campaign, resp, ticket = svc.start_from_token(db, token)
    return _set_ticket(RedirectResponse(f"/responder/{resp.id}", status_code=303), ticket)


@router.get("/e/codigo/{code}")
def open_with_code(code: str, request: Request, db: Session = Depends(get_session)):
    """Acceso por código o QR: sin nómina, para personas sin correo corporativo."""
    campaign = db.execute(
        select(SurveyCampaign).where(SurveyCampaign.access_code == code.upper())
        .execution_options(include_all=True)
    ).scalar_one_or_none()
    if not campaign or campaign.status not in OPEN_STATES:
        raise HTTPException(status_code=404, detail="Encuesta no disponible")
    ticket = _ticket_from(request)
    if ticket:
        existing = svc.resume(db, ticket)
        if existing and existing.campaign_id == campaign.id:
            return RedirectResponse(f"/responder/{existing.id}", status_code=303)
    with tenant_scope(campaign.organization_id):
        resp, ticket = svc.start_anonymous(db, campaign)
    return _set_ticket(RedirectResponse(f"/responder/{resp.id}", status_code=303), ticket)


# ------------------------------------------------------------------ responder
@router.get("/responder/{response_id}")
def survey_page(response_id: str, request: Request, page: int = 0,
                db: Session = Depends(get_session)):
    ticket = _ticket_from(request)
    if not ticket or token_hash(ticket) != _hash_of(db, response_id):
        raise HTTPException(status_code=403, detail="Enlace no válido en este navegador")
    resp, campaign, org = _load_context(db, response_id)
    if resp.status == R_SUBMITTED:
        return templates.TemplateResponse("survey/done.html", {
            "request": request, "campaign": campaign, "org": org,
        })
    if campaign.status not in OPEN_STATES:
        return templates.TemplateResponse("survey/closed.html", {
            "request": request, "campaign": campaign, "org": org,
        })

    with tenant_scope(campaign.organization_id):
        pages = _pages(db, campaign)
        version = db.get(SurveyTemplateVersion, campaign.version_id)
        answers = {a.question_id: a for a in resp.answers}
    page = max(0, min(page, len(pages) - 1))
    if page == 0 and not resp.consent_at:
        return templates.TemplateResponse("survey/consent.html", {
            "request": request, "campaign": campaign, "org": org, "response": resp,
            "minutes": version.estimated_minutes if version else None,
            "n_pages": len(pages),
        })
    return templates.TemplateResponse("survey/page.html", {
        "request": request, "campaign": campaign, "org": org, "response": resp,
        "page": pages[page], "index": page, "n_pages": len(pages),
        "progress": round((page) / max(1, len(pages)) * 100),
        "answers": answers,
    })


def _hash_of(db: Session, response_id: str) -> str | None:
    row = db.execute(
        select(SurveyResponse.ticket_hash).where(SurveyResponse.id == response_id)
        .execution_options(include_all=True)
    ).scalar_one_or_none()
    return row


@router.post("/responder/{response_id}/consentimiento")
def accept_consent(response_id: str, request: Request, db: Session = Depends(get_session)):
    ticket = _ticket_from(request)
    if not ticket or token_hash(ticket) != _hash_of(db, response_id):
        raise HTTPException(status_code=403, detail="Enlace no válido")
    import datetime as dt

    resp, campaign, _org = _load_context(db, response_id)
    resp.consent_at = dt.datetime.now(dt.UTC)
    resp.consent_version = campaign.consent_version
    db.commit()
    return RedirectResponse(f"/responder/{response_id}?page=0", status_code=303)


@router.post("/responder/{response_id}/guardar")
async def save_page(response_id: str, request: Request, db: Session = Depends(get_session)):
    ticket = _ticket_from(request)
    if not ticket or token_hash(ticket) != _hash_of(db, response_id):
        raise HTTPException(status_code=403, detail="Enlace no válido")
    resp, campaign, _org = _load_context(db, response_id)
    if campaign.status not in OPEN_STATES or resp.status == R_SUBMITTED:
        raise HTTPException(status_code=409, detail="La encuesta ya no admite respuestas")

    form = await request.form()
    index = int(form.get("_index", 0))
    action = form.get("_action", "next")
    values = {k[2:]: v for k, v in form.items() if k.startswith("q_") and v != ""}

    with tenant_scope(campaign.organization_id):
        questions = results_svc.question_map(db, campaign.version_id)
        svc.save_answers(db, resp, values, questions)
        pages = _pages(db, campaign)
        if action == "submit" or index >= len(pages) - 1:
            svc.submit(db, resp, consent_version=campaign.consent_version)
            return RedirectResponse(f"/responder/{response_id}", status_code=303)
    target = index - 1 if action == "prev" else index + 1
    return RedirectResponse(f"/responder/{response_id}?page={max(0, target)}", status_code=303)


@router.get("/retomar")
def resume_survey(request: Request, db: Session = Depends(get_session)):
    """Retomar desde el mismo navegador, sin pedir ningún dato personal."""
    ticket = _ticket_from(request)
    resp = svc.resume(db, ticket) if ticket else None
    if not resp:
        return templates.TemplateResponse("survey/not_found.html", {"request": request}, status_code=404)
    return RedirectResponse(f"/responder/{resp.id}", status_code=303)
