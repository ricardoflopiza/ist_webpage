# -*- coding: utf-8 -*-
"""Ciclo de vida de una campaña: población, invitaciones, respuesta y cierre.

Invariante central (§11): la invitación identifica a una persona; la respuesta
no. El único momento en que ambas se tocan es al canjear el token, y de ese
cruce sólo queda: `invitation.status = respondida` y una respuesta con la
fotografía de segmentación de esa persona, sin identificador que permita volver.
"""
from __future__ import annotations

import datetime as dt
import secrets

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Answer,
    EmployeePopulation,
    OpenComment,
    OrgUnit,
    SurveyCampaign,
    SurveyInvitation,
    SurveyQuestion,
    SurveyResponse,
)
from ..models.campaign import (
    ACCESS_CODE,
    ACCESS_OPEN,
    ACCESS_QR,
    C_ACTIVE,
    C_ANALYSIS,
    C_CLOSED,
    C_DRAFT,
    C_PUBLISHED,
    C_REVIEW,
    C_SCHEDULED,
    INV_PENDING,
    INV_RESPONDED,
    INV_SENT,
    INV_STARTED,
    OPEN_STATES,
)
from ..models.response import R_PARTIAL, R_STARTED, R_SUBMITTED
from ..models.survey import Q_TEXT
from ..security.tokens import make_response_ticket, new_invitation_token, token_hash
from .anonymity import detect_sensitive, redact_personal_data

# Transiciones permitidas. Cualquier otra es un 409.
TRANSITIONS = {
    C_DRAFT: (C_REVIEW, "archivada"),
    C_REVIEW: (C_DRAFT, C_SCHEDULED, C_ACTIVE),
    C_SCHEDULED: (C_ACTIVE, C_DRAFT, "archivada"),
    C_ACTIVE: ("pausada", C_CLOSED),
    "pausada": (C_ACTIVE, C_CLOSED),
    C_CLOSED: (C_ANALYSIS, "archivada"),
    C_ANALYSIS: (C_PUBLISHED, C_CLOSED),
    C_PUBLISHED: ("en_seguimiento", "archivada"),
    "en_seguimiento": (C_PUBLISHED, "archivada"),
}


def transition(db: Session, campaign: SurveyCampaign, new_status: str) -> SurveyCampaign:
    allowed = TRANSITIONS.get(campaign.status, ())
    if new_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"No se puede pasar de «{campaign.status}» a «{new_status}»",
        )
    campaign.status = new_status
    if new_status == C_CLOSED:
        campaign.closed_at = dt.datetime.now(dt.UTC)
    if new_status == C_PUBLISHED:
        campaign.results_published_at = dt.datetime.now(dt.UTC)
    db.commit()
    return campaign


# ------------------------------------------------------------------ población
def target_population(db: Session, campaign: SurveyCampaign) -> list[EmployeePopulation]:
    stmt = select(EmployeePopulation).where(EmployeePopulation.is_active.is_(True))
    people = list(db.execute(stmt).scalars())
    flt = campaign.population_filter or {}
    if flt.get("org_unit_ids"):
        wanted = set(flt["org_unit_ids"])
        unit_paths = _unit_paths(db)
        people = [
            p for p in people
            if p.org_unit_id and (p.org_unit_id in wanted or wanted & set(unit_paths.get(p.org_unit_id, [])))
        ]
    for key, value in (flt.get("attributes") or {}).items():
        people = [p for p in people if str((p.attributes or {}).get(key)) == str(value)]
    return people


def _unit_paths(db: Session) -> dict[str, list[str]]:
    """Ancestros de cada unidad, para filtrar y agregar por cualquier nivel."""
    units = {u.id: u for u in db.execute(select(OrgUnit)).scalars()}
    paths: dict[str, list[str]] = {}
    for uid, u in units.items():
        chain, cur, guard = [], u, 0
        while cur and guard < 12:
            chain.append(cur.id)
            cur = units.get(cur.parent_id) if cur.parent_id else None
            guard += 1
        paths[uid] = chain
    return paths


# ------------------------------------------------------------------ invitaciones
def generate_invitations(db: Session, campaign: SurveyCampaign) -> list[tuple[SurveyInvitation, str]]:
    """Crea invitaciones y devuelve (invitación, token en claro).

    El token en claro existe sólo en memoria el tiempo de construir el enlace o
    el correo. En la base queda su SHA-256.
    """
    existing = {
        i.employee_id for i in db.execute(
            select(SurveyInvitation).where(SurveyInvitation.campaign_id == campaign.id)
        ).scalars()
    }
    out = []
    for person in target_population(db, campaign):
        if person.id in existing:
            continue
        token = new_invitation_token()
        inv = SurveyInvitation(
            organization_id=campaign.organization_id,
            campaign_id=campaign.id,
            employee_id=person.id,
            token_hash=token_hash(token),
            status=INV_PENDING,
        )
        db.add(inv)
        out.append((inv, token))
    db.flush()
    campaign.invited_count = db.query(SurveyInvitation).filter(
        SurveyInvitation.campaign_id == campaign.id
    ).count()
    db.commit()
    return out


def invitation_link(token: str) -> str:
    return f"{settings.public_base_url}/e/{token}"


def mark_sent(db: Session, campaign: SurveyCampaign) -> int:
    invs = db.execute(
        select(SurveyInvitation).where(
            SurveyInvitation.campaign_id == campaign.id,
            SurveyInvitation.status == INV_PENDING,
        )
    ).scalars().all()
    now = dt.datetime.now(dt.UTC)
    for i in invs:
        i.status, i.sent_at = INV_SENT, now
    db.commit()
    return len(invs)


def ensure_access_code(db: Session, campaign: SurveyCampaign) -> str:
    if campaign.access_method in (ACCESS_CODE, ACCESS_QR, ACCESS_OPEN) and not campaign.access_code:
        campaign.access_code = secrets.token_hex(3).upper()
        db.commit()
    return campaign.access_code or ""


# ------------------------------------------------------------------ respuesta
def _segment_snapshot(db: Session, person: EmployeePopulation | None, campaign: SurveyCampaign) -> dict:
    """Fotografía de segmentación, sin identidad.

    Sólo se copian las claves autorizadas en la campaña: una variable no
    declarada no viaja al lado de las respuestas ni puede usarse para cruzar.
    """
    if person is None:
        return {}
    allowed = set(campaign.segmentation_keys or [])
    attrs = {k: v for k, v in (person.attributes or {}).items() if k in allowed}
    if person.org_unit_id:
        attrs["unit_path"] = _unit_paths(db).get(person.org_unit_id, [person.org_unit_id])
    return attrs


def start_from_token(db: Session, token: str) -> tuple[SurveyCampaign, SurveyResponse, str]:
    """Canjea un token de invitación por una respuesta anónima."""
    inv = db.execute(
        select(SurveyInvitation).where(SurveyInvitation.token_hash == token_hash(token))
        .execution_options(include_all=True)
    ).scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Enlace no válido")
    campaign = db.get(SurveyCampaign, inv.campaign_id)
    if not campaign or campaign.status not in OPEN_STATES:
        raise HTTPException(status_code=409, detail="La encuesta no está abierta")
    if inv.status == INV_RESPONDED:
        raise HTTPException(status_code=409, detail="Esta invitación ya fue utilizada")

    person = db.get(EmployeePopulation, inv.employee_id)
    now = dt.datetime.now(dt.UTC)
    resp = SurveyResponse(
        organization_id=campaign.organization_id,
        campaign_id=campaign.id,
        status=R_STARTED,
        segment=_segment_snapshot(db, person, campaign),
        org_unit_id=person.org_unit_id if person else None,
        started_at=now,
        source=campaign.access_method,
        is_demo=campaign.is_demo,
    )
    db.add(resp)
    db.flush()
    ticket = make_response_ticket(resp.id)
    resp.ticket_hash = token_hash(ticket)
    # A partir de aquí la invitación queda marcada, sin guardar a qué respuesta
    # dio lugar: no existe puente persistido entre persona y respuesta.
    inv.status = INV_STARTED
    inv.first_opened_at = inv.first_opened_at or now
    db.commit()
    return campaign, resp, ticket


def start_anonymous(db: Session, campaign: SurveyCampaign, unit_id: str | None = None) -> tuple[SurveyResponse, str]:
    """Acceso por código, QR o enlace abierto: sin nómina detrás."""
    if campaign.status not in OPEN_STATES:
        raise HTTPException(status_code=409, detail="La encuesta no está abierta")
    now = dt.datetime.now(dt.UTC)
    resp = SurveyResponse(
        organization_id=campaign.organization_id,
        campaign_id=campaign.id,
        status=R_STARTED,
        segment={"unit_path": _unit_paths(db).get(unit_id, [unit_id])} if unit_id else {},
        org_unit_id=unit_id,
        started_at=now,
        source=campaign.access_method,
        is_demo=campaign.is_demo,
    )
    db.add(resp)
    db.flush()
    ticket = make_response_ticket(resp.id)
    resp.ticket_hash = token_hash(ticket)
    db.commit()
    return resp, ticket


def resume(db: Session, ticket: str) -> SurveyResponse | None:
    from ..security.tokens import read_response_ticket

    rid = read_response_ticket(ticket)
    if not rid:
        return None
    resp = db.execute(
        select(SurveyResponse).where(SurveyResponse.id == rid).execution_options(include_all=True)
    ).scalar_one_or_none()
    if not resp or resp.ticket_hash != token_hash(ticket):
        return None
    return resp if resp.status != R_SUBMITTED else None


def save_answers(db: Session, response: SurveyResponse, values: dict, questions: dict[str, SurveyQuestion]) -> None:
    """Guardado progresivo. Se puede llamar tantas veces como avance la persona."""
    existing = {a.question_id: a for a in response.answers}
    for qid, raw in values.items():
        q = questions.get(qid)
        if q is None:
            continue
        a = existing.get(qid)
        if a is None:
            a = Answer(
                organization_id=response.organization_id,
                response_id=response.id, campaign_id=response.campaign_id, question_id=qid,
            )
            db.add(a)
            response.answers.append(a)
        a.value_num, a.value_text, a.value_json, a.is_na = None, None, None, False
        if raw in ("na", "NA", "no_aplica"):
            a.is_na = True
        elif isinstance(raw, list):
            a.value_json = raw
        elif q.qtype == Q_TEXT:
            a.value_text = str(raw).strip() or None
        else:
            try:
                a.value_num = float(raw)
            except (TypeError, ValueError):
                a.value_text = str(raw)
    total = max(1, len(questions))
    answered = sum(1 for a in response.answers if not a.skipped)
    response.progress = round(min(1.0, answered / total), 3)
    if response.status == R_STARTED:
        response.status = R_PARTIAL
    db.commit()


def submit(db: Session, response: SurveyResponse, consent_version: str | None = None) -> SurveyResponse:
    if response.status == R_SUBMITTED:
        return response
    response.status = R_SUBMITTED
    response.submitted_at = dt.datetime.now(dt.UTC)
    if consent_version:
        response.consent_version = consent_version
        response.consent_at = response.consent_at or response.submitted_at
    _extract_comments(db, response)
    db.commit()
    return response


def _extract_comments(db: Session, response: SurveyResponse) -> None:
    """Materializa los textos abiertos como comentarios analizables.

    Se guardan con los datos personales evidentes ocultos y con las marcas de
    sensibilidad puestas por reglas: el sistema **marca para revisión humana**,
    no concluye ni acusa (§17).
    """
    for a in response.answers:
        if not a.value_text or not a.value_text.strip():
            continue
        q = db.get(SurveyQuestion, a.question_id)
        if q is None or q.qtype != Q_TEXT:
            continue
        flags = detect_sensitive(a.value_text)
        db.add(OpenComment(
            organization_id=response.organization_id,
            campaign_id=response.campaign_id,
            question_id=q.id,
            answer_id=a.id,
            text=a.value_text,
            redacted_text=redact_personal_data(a.value_text),
            segment=dict(response.segment or {}),
            org_unit_id=response.org_unit_id,
            is_sensitive=bool(flags),
            sensitive_flags=flags or None,
            review_status="pendiente_revision" if flags else None,
            is_demo=response.is_demo,
        ))


def close_and_mark(db: Session, campaign: SurveyCampaign) -> None:
    """Cierra la campaña y consolida el estado de las invitaciones."""
    transition(db, campaign, C_CLOSED)
    n_submitted = db.query(SurveyResponse).filter(
        SurveyResponse.campaign_id == campaign.id,
        SurveyResponse.status == R_SUBMITTED,
    ).count()
    invs = db.execute(
        select(SurveyInvitation).where(
            SurveyInvitation.campaign_id == campaign.id,
            SurveyInvitation.status == INV_STARTED,
        )
    ).scalars().all()
    # Se marca como respondida una cantidad equivalente, sin decir cuáles
    # respuestas corresponden a cuáles invitaciones.
    now = dt.datetime.now(dt.UTC)
    for inv in invs[:n_submitted]:
        inv.status, inv.responded_at = INV_RESPONDED, now
    db.commit()
