# -*- coding: utf-8 -*-
"""Gestión de instrumentos: plantillas, versiones, módulos, dimensiones y preguntas (§7).

Regla estructural: una versión **publicada** es inmutable. Para cambiar algo se
crea una versión nueva. Es lo que permite comparar dos mediciones sabiendo que
las preguntas eran las mismas, y lo que hace honesto el benchmark.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import (
    QuestionBankItem,
    SurveyDimension,
    SurveyModule,
    SurveyQuestion,
    SurveyTemplate,
    SurveyTemplateVersion,
)
from ..models.survey import QUESTION_TYPES, VERSION_DRAFT, VERSION_PUBLISHED
from ..security.deps import Viewer, require_perm
from ..security.permissions import P_TEMPLATE_MANAGE, P_TEMPLATE_PUBLISH, P_TEMPLATE_VIEW
from ..services import audit as audit_svc
from ..services.library import clone_template
from ..services.scales import SCALES
from . import API_PREFIX

router = APIRouter(prefix=f"{API_PREFIX}/o/{{org_slug}}/surveys", tags=["encuestas"])
ALL = {"include_all": True}


# ------------------------------------------------------------------ esquemas
class TemplateIn(BaseModel):
    code: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=2, max_length=200)
    purpose: str | None = None
    kind: str = "clima"


class ModuleIn(BaseModel):
    code: str
    name: str
    description: str | None = None
    is_enabled: bool = True
    sort_order: int = 0


class DimensionIn(BaseModel):
    module_id: str
    code: str
    name: str
    definition: str | None = None
    is_outcome: bool = False
    index_key: str | None = None
    sort_order: int = 0


class QuestionIn(BaseModel):
    dimension_id: str
    code: str
    text: str
    help_text: str | None = None
    qtype: str = "likert"
    scale_key: str | None = "acuerdo"
    options: list | None = None
    is_required: bool = True
    allow_na: bool = False
    is_reverse: bool = False
    tags: list | None = None
    display_logic: dict | None = None
    bank_item_id: str | None = None
    sort_order: int = 0


class ReorderIn(BaseModel):
    ids: list[str]


# ------------------------------------------------------------------ helpers
def _version(db: Session, version_id: str) -> SurveyTemplateVersion:
    v = db.get(SurveyTemplateVersion, version_id)
    if not v:
        raise HTTPException(status_code=404, detail="Versión no encontrada")
    return v


def _editable(v: SurveyTemplateVersion) -> SurveyTemplateVersion:
    if not v.is_editable:
        raise HTTPException(
            status_code=409,
            detail="La versión está publicada y es inmutable. Crea una versión nueva para editarla.",
        )
    return v


def _own_version(v: SurveyTemplateVersion, viewer: Viewer) -> SurveyTemplateVersion:
    if v.organization_id is None:
        raise HTTPException(
            status_code=403,
            detail="Las plantillas maestras se editan desde la administración de plataforma. "
                   "Duplícala para adaptarla a esta organización.",
        )
    return v


def _template_dict(t: SurveyTemplate) -> dict:
    return {
        "id": t.id, "code": t.code, "name": t.name, "kind": t.kind, "purpose": t.purpose,
        "is_master": t.organization_id is None, "derived_from_id": t.derived_from_id,
        "versions": [
            {"id": v.id, "number": v.number, "status": v.status,
             "published_at": v.published_at, "estimated_minutes": v.estimated_minutes}
            for v in sorted(t.versions, key=lambda v: v.number)
        ],
    }


# ------------------------------------------------------------------ plantillas
@router.get("", summary="Plantillas disponibles (maestras + propias)")
def list_templates(viewer: Viewer = Depends(require_perm(P_TEMPLATE_VIEW)),
                   db: Session = Depends(get_session)):
    rows = db.execute(
        select(SurveyTemplate).where(SurveyTemplate.is_active.is_(True))
        .order_by(SurveyTemplate.organization_id.is_(None).desc(), SurveyTemplate.name)
    ).scalars().all()
    return {"items": [_template_dict(t) for t in rows], "total": len(rows)}


@router.post("", status_code=201, summary="Crear plantilla propia desde cero")
def create_template(payload: TemplateIn, viewer: Viewer = Depends(require_perm(P_TEMPLATE_MANAGE)),
                    db: Session = Depends(get_session)):
    tpl = SurveyTemplate(organization_id=viewer.organization.id, **payload.model_dump())
    db.add(tpl)
    db.flush()
    version = SurveyTemplateVersion(
        organization_id=viewer.organization.id, template_id=tpl.id, number=1,
        status=VERSION_DRAFT, changelog="Versión inicial.",
    )
    db.add(version)
    db.commit()
    return {"id": tpl.id, "version_id": version.id}


@router.post("/{template_id}/duplicate", status_code=201, summary="Duplicar/adaptar una plantilla")
def duplicate_template(template_id: str, name: str | None = None, code: str | None = None,
                       viewer: Viewer = Depends(require_perm(P_TEMPLATE_MANAGE)),
                       db: Session = Depends(get_session)):
    src = db.get(SurveyTemplate, template_id)
    if not src:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    tpl = clone_template(db, src, viewer.organization.id, name=name, code=code)
    audit_svc.log_view(db, viewer, "plantilla_adaptada", entity="survey_template",
                       entity_id=tpl.id, detail={"origen": src.code})
    return _template_dict(tpl)


@router.post("/{template_id}/versions", status_code=201, summary="Crear versión nueva")
def create_version(template_id: str, changelog: str | None = None,
                   viewer: Viewer = Depends(require_perm(P_TEMPLATE_MANAGE)),
                   db: Session = Depends(get_session)):
    """Copia la última versión como borrador editable, conservando la publicada."""
    tpl = db.get(SurveyTemplate, template_id)
    if not tpl or tpl.organization_id is None:
        raise HTTPException(status_code=404, detail="Plantilla propia no encontrada")
    last = sorted(tpl.versions, key=lambda v: v.number)[-1]
    new = SurveyTemplateVersion(
        organization_id=tpl.organization_id, template_id=tpl.id, number=last.number + 1,
        status=VERSION_DRAFT, changelog=changelog or f"Derivada de la versión {last.number}.",
        estimated_minutes=last.estimated_minutes,
    )
    db.add(new)
    db.flush()
    for module in last.modules:
        m = SurveyModule(organization_id=tpl.organization_id, version_id=new.id, code=module.code,
                         name=module.name, description=module.description,
                         is_enabled=module.is_enabled, sort_order=module.sort_order)
        db.add(m)
        db.flush()
        for dim in module.dimensions:
            d = SurveyDimension(organization_id=tpl.organization_id, module_id=m.id, code=dim.code,
                                name=dim.name, definition=dim.definition, is_outcome=dim.is_outcome,
                                index_key=dim.index_key, sort_order=dim.sort_order)
            db.add(d)
            db.flush()
            for q in dim.questions:
                db.add(SurveyQuestion(
                    organization_id=tpl.organization_id, dimension_id=d.id, code=q.code,
                    text=q.text, help_text=q.help_text, qtype=q.qtype, scale_key=q.scale_key,
                    options=q.options, is_required=q.is_required, allow_na=q.allow_na,
                    is_reverse=q.is_reverse, tags=q.tags, display_logic=q.display_logic,
                    sort_order=q.sort_order,
                ))
    db.commit()
    return {"id": new.id, "number": new.number, "status": new.status}


@router.get("/versions/{version_id}", summary="Estructura completa de una versión")
def get_version(version_id: str, viewer: Viewer = Depends(require_perm(P_TEMPLATE_VIEW)),
                db: Session = Depends(get_session)):
    v = _version(db, version_id)
    return {
        "id": v.id, "number": v.number, "status": v.status, "editable": v.is_editable,
        "changelog": v.changelog, "estimated_minutes": v.estimated_minutes,
        "template": {"id": v.template.id, "code": v.template.code, "name": v.template.name,
                     "is_master": v.template.organization_id is None},
        "modules": [
            {"id": m.id, "code": m.code, "name": m.name, "description": m.description,
             "is_enabled": m.is_enabled, "sort_order": m.sort_order,
             "dimensions": [
                 {"id": d.id, "code": d.code, "name": d.name, "definition": d.definition,
                  "is_outcome": d.is_outcome, "index_key": d.index_key, "sort_order": d.sort_order,
                  "questions": [
                      {"id": q.id, "code": q.code, "text": q.text, "help_text": q.help_text,
                       "qtype": q.qtype, "scale_key": q.scale_key, "options": q.options,
                       "is_required": q.is_required, "allow_na": q.allow_na,
                       "is_reverse": q.is_reverse, "tags": q.tags,
                       "display_logic": q.display_logic, "sort_order": q.sort_order}
                      for q in d.questions
                  ]}
                 for d in m.dimensions
             ]}
            for m in v.modules
        ],
    }


@router.post("/versions/{version_id}/publish", summary="Publicar versión (queda inmutable)")
def publish_version(version_id: str, viewer: Viewer = Depends(require_perm(P_TEMPLATE_PUBLISH)),
                    db: Session = Depends(get_session)):
    v = _own_version(_version(db, version_id), viewer)
    if v.status == VERSION_PUBLISHED:
        return {"id": v.id, "status": v.status}
    problems = validate_version(v)
    if problems:
        raise HTTPException(status_code=422, detail={"problemas": problems})
    v.status = VERSION_PUBLISHED
    v.published_at = dt.datetime.now(dt.UTC)
    v.published_by_id = viewer.user.id
    db.commit()
    audit_svc.log_view(db, viewer, "publicacion", entity="survey_template_version", entity_id=v.id)
    return {"id": v.id, "status": v.status, "published_at": v.published_at}


def validate_version(v: SurveyTemplateVersion) -> list[str]:
    problems = []
    questions = [q for m in v.modules if m.is_enabled for d in m.dimensions for q in d.questions]
    if not questions:
        problems.append("La versión no tiene preguntas en módulos activos.")
    codes = [q.code for q in questions]
    if len(codes) != len(set(codes)):
        problems.append("Hay códigos de pregunta repetidos.")
    for m in v.modules:
        for d in m.dimensions:
            scorable = [q for q in d.questions if q.qtype in ("likert", "numeric", "nps")]
            if not scorable and d.code != "comentarios":
                problems.append(f"La dimensión «{d.name}» no tiene ítems puntuables.")
            for q in d.questions:
                if q.qtype in ("single_choice", "multi_choice", "ranking") and not q.options:
                    problems.append(f"La pregunta «{q.code}» necesita opciones.")
    return problems


@router.get("/versions/{version_id}/preview", summary="Previsualizar la encuesta")
def preview_version(version_id: str, viewer: Viewer = Depends(require_perm(P_TEMPLATE_VIEW)),
                    db: Session = Depends(get_session)):
    v = _version(db, version_id)
    pages = []
    for m in v.modules:
        if not m.is_enabled:
            continue
        for d in m.dimensions:
            pages.append({
                "module": m.name, "dimension": d.name,
                "questions": [
                    {"code": q.code, "text": q.text, "qtype": q.qtype,
                     "scale": SCALES[q.scale_key].labels if q.scale_key in SCALES else None,
                     "options": q.options, "allow_na": q.allow_na, "required": q.is_required}
                    for q in d.questions
                ],
            })
    return {"estimated_minutes": v.estimated_minutes, "pages": pages,
            "problems": validate_version(v)}


# ------------------------------------------------------------------ módulos / dimensiones / preguntas
@router.post("/versions/{version_id}/modules", status_code=201, summary="Crear módulo")
def create_module(version_id: str, payload: ModuleIn,
                  viewer: Viewer = Depends(require_perm(P_TEMPLATE_MANAGE)),
                  db: Session = Depends(get_session)):
    v = _editable(_own_version(_version(db, version_id), viewer))
    m = SurveyModule(organization_id=v.organization_id, version_id=v.id, **payload.model_dump())
    db.add(m)
    db.commit()
    return {"id": m.id}


@router.patch("/modules/{module_id}", summary="Actualizar módulo (incluye activar/desactivar)")
def update_module(module_id: str, payload: ModuleIn,
                  viewer: Viewer = Depends(require_perm(P_TEMPLATE_MANAGE)),
                  db: Session = Depends(get_session)):
    m = db.get(SurveyModule, module_id)
    if not m:
        raise HTTPException(status_code=404, detail="Módulo no encontrado")
    _editable(_own_version(m.version, viewer))
    for k, val in payload.model_dump(exclude_none=True).items():
        setattr(m, k, val)
    db.commit()
    return {"id": m.id, "is_enabled": m.is_enabled}


@router.post("/dimensions", status_code=201, summary="Crear dimensión")
def create_dimension(payload: DimensionIn, viewer: Viewer = Depends(require_perm(P_TEMPLATE_MANAGE)),
                     db: Session = Depends(get_session)):
    m = db.get(SurveyModule, payload.module_id)
    if not m:
        raise HTTPException(status_code=404, detail="Módulo no encontrado")
    _editable(_own_version(m.version, viewer))
    d = SurveyDimension(organization_id=m.organization_id, **payload.model_dump())
    db.add(d)
    db.commit()
    return {"id": d.id}


@router.post("/questions", status_code=201, summary="Crear pregunta")
def create_question(payload: QuestionIn, viewer: Viewer = Depends(require_perm(P_TEMPLATE_MANAGE)),
                    db: Session = Depends(get_session)):
    d = db.get(SurveyDimension, payload.dimension_id)
    if not d:
        raise HTTPException(status_code=404, detail="Dimensión no encontrada")
    _editable(_own_version(d.module.version, viewer))
    if payload.qtype not in QUESTION_TYPES:
        raise HTTPException(status_code=422, detail=f"Tipo de pregunta inválido: {payload.qtype}")
    if payload.scale_key and payload.scale_key not in SCALES and payload.qtype != "open_text":
        raise HTTPException(status_code=422, detail=f"Escala desconocida: {payload.scale_key}")
    q = SurveyQuestion(organization_id=d.organization_id, **payload.model_dump())
    db.add(q)
    db.commit()
    return {"id": q.id}


@router.patch("/questions/{question_id}", summary="Actualizar pregunta")
def update_question(question_id: str, payload: QuestionIn,
                    viewer: Viewer = Depends(require_perm(P_TEMPLATE_MANAGE)),
                    db: Session = Depends(get_session)):
    q = db.get(SurveyQuestion, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada")
    _editable(_own_version(q.dimension.module.version, viewer))
    for k, val in payload.model_dump(exclude_none=True).items():
        setattr(q, k, val)
    db.commit()
    return {"id": q.id}


@router.delete("/questions/{question_id}", summary="Eliminar pregunta")
def delete_question(question_id: str, viewer: Viewer = Depends(require_perm(P_TEMPLATE_MANAGE)),
                    db: Session = Depends(get_session)):
    q = db.get(SurveyQuestion, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada")
    _editable(_own_version(q.dimension.module.version, viewer))
    db.delete(q)
    db.commit()
    return {"deleted": question_id}


@router.post("/dimensions/{dimension_id}/reorder", summary="Reordenar preguntas")
def reorder_questions(dimension_id: str, payload: ReorderIn,
                      viewer: Viewer = Depends(require_perm(P_TEMPLATE_MANAGE)),
                      db: Session = Depends(get_session)):
    d = db.get(SurveyDimension, dimension_id)
    if not d:
        raise HTTPException(status_code=404, detail="Dimensión no encontrada")
    _editable(_own_version(d.module.version, viewer))
    order = {qid: i for i, qid in enumerate(payload.ids)}
    for q in d.questions:
        if q.id in order:
            q.sort_order = order[q.id]
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ banco y escalas
@router.get("/bank", summary="Banco de preguntas")
def question_bank(viewer: Viewer = Depends(require_perm(P_TEMPLATE_VIEW)),
                  db: Session = Depends(get_session), q: str | None = None,
                  dimension_code: str | None = None, limit: int = 100):
    stmt = select(QuestionBankItem)
    if dimension_code:
        stmt = stmt.where(QuestionBankItem.dimension_code == dimension_code)
    if q:
        stmt = stmt.where(QuestionBankItem.text.ilike(f"%{q}%"))
    rows = db.execute(stmt.limit(limit)).scalars().all()
    return {"items": [
        {"id": i.id, "code": i.code, "text": i.text, "qtype": i.qtype, "scale_key": i.scale_key,
         "dimension_code": i.dimension_code, "is_reverse": i.is_reverse, "tags": i.tags}
        for i in rows
    ], "total": len(rows)}


@router.get("/scales", summary="Escalas disponibles")
def list_scales(viewer: Viewer = Depends(require_perm(P_TEMPLATE_VIEW))):
    return {"items": [
        {"key": s.key, "name": s.name, "min": s.min_value, "max": s.max_value,
         "labels": list(s.labels), "favorable": list(s.favorable),
         "neutral": list(s.neutral), "unfavorable": list(s.unfavorable)}
        for s in SCALES.values()
    ]}
