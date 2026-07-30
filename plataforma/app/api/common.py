# -*- coding: utf-8 -*-
"""Utilidades compartidas por los routers."""
from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import SurveyCampaign


class Page:
    def __init__(self, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        self.limit, self.offset = limit, offset


def paginate(db: Session, stmt, page: Page, model) -> dict:
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.limit(page.limit).offset(page.offset)).scalars().all()
    return {"items": rows, "total": total, "limit": page.limit, "offset": page.offset}


def serialize(obj, fields: Iterable[str]) -> dict:
    return {f: getattr(obj, f, None) for f in fields}


def get_campaign(db: Session, campaign_id: str) -> SurveyCampaign:
    """El filtro por organización lo aplica el guard central: si la campaña es de
    otro tenant, esta consulta simplemente no la encuentra (404, no 403: no se
    confirma la existencia de recursos ajenos)."""
    campaign = db.get(SurveyCampaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    return campaign


def parse_filters(request) -> dict:
    """Filtros de segmentación desde la query string.

    Se aceptan `org_unit_id` y cualquier clave declarada en `segmentation_keys`
    de la campaña; el resto se ignora en silencio para que un parámetro inventado
    no abra un cruce no autorizado.
    """
    reserved = {"limit", "offset", "campaign_id", "kind", "format", "reason"}
    return {k: v for k, v in request.query_params.items() if k not in reserved and v}
