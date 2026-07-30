# -*- coding: utf-8 -*-
"""Análisis de comentarios abiertos y protocolo de comentarios sensibles (§17)."""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import OpenComment
from ..security.deps import Viewer, client_ip, org_viewer, require_perm
from ..security.permissions import P_COMMENTS_MANAGE, P_COMMENTS_SENSITIVE, P_COMMENTS_VIEW
from ..services import audit as audit_svc
from ..services import results as results_svc
from ..services.anonymity import can_display_segment
from . import API_PREFIX
from .common import get_campaign, parse_filters

router = APIRouter(prefix=f"{API_PREFIX}/o/{{org_slug}}/comments", tags=["comentarios"])

PROTOCOL = {
    "titulo": "Protocolo de revisión de comentarios sensibles",
    "pasos": [
        "Revisar el comentario con la contraparte designada, sin difundir el texto.",
        "No intentar identificar a quien lo escribió.",
        "Verificar que la organización tenga activo su canal formal de denuncia.",
        "Recordar en la devolución que la encuesta no reemplaza ese canal.",
        "Registrar la decisión tomada y quién la tomó.",
    ],
    "advertencia": (
        "Una mención en una encuesta anónima es un antecedente para activar los "
        "canales formales, no un hecho probado ni una acusación contra una persona."
    ),
}

# Palabras vacías del español para el agrupamiento temático de apoyo.
STOPWORDS = set("""
a al algo alguna algunas alguno algunos ante antes aqui aquí como con contra cual cuando de del
desde donde dos el ella ellas ellos en entre era eran es esa esas ese eso esos esta estan están
estar este esto estos fue fueron ha hace hacen hacia han hasta hay la las le les lo los mas más me
mi mis mucho muy nada ni no nos nosotros o os otra otras otro otros para pero poco por porque que
qué quien quienes se sea ser si sí sin sobre solo sólo son su sus tambien también tan tanto te
tiene tienen todo todos tu tus un una uno unos y ya
""".split())


class CommentUpdate(BaseModel):
    themes: list[str] | None = None
    sentiment: str | None = None
    is_proposal: bool | None = None
    review_status: str | None = None
    ai_reviewed: bool | None = None


def _decision(db: Session, campaign, viewer: Viewer, filters: dict):
    n = len(results_svc.load_responses(db, campaign, filters))
    return can_display_segment(
        filters, viewer, campaign, organization=viewer.organization, n_responses=n,
        n_universe=results_svc.unit_universe(db, campaign, filters.get("org_unit_id")),
    )


def _dict(c: OpenComment, can_sensitive: bool) -> dict:
    return {
        "id": c.id, "text": c.redacted_text or c.text, "themes": c.themes or [],
        "sentiment": c.sentiment, "is_proposal": c.is_proposal,
        "is_sensitive": c.is_sensitive,
        "sensitive_flags": (c.sensitive_flags or []) if can_sensitive else None,
        "review_status": c.review_status, "org_unit_id": c.org_unit_id,
        "created_at": c.created_at,
    }


@router.get("/{campaign_id}", summary="Comentarios de una campaña")
def list_comments(campaign_id: str, request: Request,
                  viewer: Viewer = Depends(require_perm(P_COMMENTS_VIEW)),
                  db: Session = Depends(get_session),
                  q: str | None = None, theme: str | None = None,
                  only_sensitive: bool = False, limit: int = 100, offset: int = 0):
    """Los comentarios de un segmento bajo el umbral no se entregan: un texto libre
    reidentifica con mucha más facilidad que un promedio."""
    campaign = get_campaign(db, campaign_id)
    filters = parse_filters(request)
    for k in ("q", "theme", "only_sensitive", "limit", "offset"):
        filters.pop(k, None)
    decision = _decision(db, campaign, viewer, filters)
    if not decision.allowed:
        return {"allowed": False, "reason": decision.reason, "message": decision.message}

    can_sensitive = viewer.can(P_COMMENTS_SENSITIVE)
    stmt = select(OpenComment).where(OpenComment.campaign_id == campaign.id)
    if filters.get("org_unit_id"):
        stmt = stmt.where(OpenComment.org_unit_id == filters["org_unit_id"])
    if q:
        stmt = stmt.where(OpenComment.text.ilike(f"%{q}%"))
    rows = db.execute(stmt.order_by(OpenComment.created_at.desc())).scalars().all()
    if theme:
        rows = [c for c in rows if theme in (c.themes or [])]
    if only_sensitive:
        if not can_sensitive:
            raise HTTPException(status_code=403, detail="Sin permiso para ver comentarios sensibles")
        rows = [c for c in rows if c.is_sensitive]
    elif not can_sensitive:
        rows = [c for c in rows if not c.is_sensitive]

    total = len(rows)
    page = rows[offset:offset + limit]
    audit_svc.log_view(db, viewer, "ver_comentarios", entity="survey_campaign",
                       entity_id=campaign.id, detail={"n": len(page), "filtros": filters},
                       ip=client_ip(request))
    if only_sensitive and page:
        # El acceso a comentarios sensibles se audita uno a uno, sin el texto.
        for c in page:
            audit_svc.log_view(db, viewer, "ver_comentario_sensible", entity="open_comment",
                               entity_id=c.id, ip=client_ip(request))
            c.review_count += 1
        db.commit()
    return {
        "allowed": True, "total": total, "items": [_dict(c, can_sensitive) for c in page],
        "sensitive_total": len([c for c in rows if c.is_sensitive]) if can_sensitive else None,
        "protocol": PROTOCOL if can_sensitive else None,
    }


@router.get("/{campaign_id}/themes", summary="Agrupación temática de apoyo")
def themes(campaign_id: str, request: Request,
           viewer: Viewer = Depends(require_perm(P_COMMENTS_VIEW)),
           db: Session = Depends(get_session)):
    """Frecuencia de términos y de etiquetas asignadas.

    Es un apoyo para orientar la lectura, **no** un análisis cualitativo: la
    interpretación la hace una persona leyendo los comentarios en su contexto.
    """
    campaign = get_campaign(db, campaign_id)
    filters = parse_filters(request)
    decision = _decision(db, campaign, viewer, filters)
    if not decision.allowed:
        return {"allowed": False, "reason": decision.reason, "message": decision.message}

    can_sensitive = viewer.can(P_COMMENTS_SENSITIVE)
    rows = db.execute(
        select(OpenComment).where(OpenComment.campaign_id == campaign.id)
    ).scalars().all()
    if not can_sensitive:
        rows = [c for c in rows if not c.is_sensitive]

    words = Counter()
    for c in rows:
        for w in re.findall(r"[a-záéíóúñü]{4,}", (c.redacted_text or c.text).lower()):
            if w not in STOPWORDS:
                words[w] += 1
    tags = Counter(t for c in rows for t in (c.themes or []))
    return {
        "allowed": True, "n_comments": len(rows),
        "terms": [{"term": w, "n": n} for w, n in words.most_common(40)],
        "tags": [{"tag": t, "n": n} for t, n in tags.most_common()],
        "proposals": len([c for c in rows if c.is_proposal]),
        "sensitive": len([c for c in rows if c.is_sensitive]) if can_sensitive else None,
        "note": ("Frecuencia de términos como apoyo a la lectura. No sustituye el "
                 "análisis cualitativo con revisión humana."),
    }


@router.patch("/{comment_id}", summary="Etiquetar o revisar un comentario")
def update_comment(comment_id: str, payload: CommentUpdate, request: Request,
                   viewer: Viewer = Depends(require_perm(P_COMMENTS_MANAGE)),
                   db: Session = Depends(get_session)):
    c = db.get(OpenComment, comment_id)
    if not c:
        raise HTTPException(status_code=404, detail="Comentario no encontrado")
    if c.is_sensitive and not viewer.can(P_COMMENTS_SENSITIVE):
        raise HTTPException(status_code=403, detail="Comentario bajo protocolo de revisión")
    data = payload.model_dump(exclude_none=True)
    for k, v in data.items():
        setattr(c, k, v)
    if data.get("review_status"):
        c.sensitive_reviewed_by_id = viewer.user.id
        c.sensitive_reviewed_at = dt.datetime.now(dt.UTC)
    db.commit()
    audit_svc.log_view(db, viewer, "comentario_actualizado", entity="open_comment",
                       entity_id=c.id, detail={"campos": list(data)}, ip=client_ip(request))
    return _dict(c, viewer.can(P_COMMENTS_SENSITIVE))


@router.get("/{campaign_id}/protocol", summary="Protocolo de comentarios sensibles")
def protocol(campaign_id: str, viewer: Viewer = Depends(org_viewer)):
    return PROTOCOL
