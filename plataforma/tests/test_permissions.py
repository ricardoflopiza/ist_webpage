# -*- coding: utf-8 -*-
"""Permisos por rol, aplicados en la API (no sólo en la interfaz)."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import tenant_scope
from app.models import EmployeePopulation, OpenComment, SurveyCampaign, SurveyTemplateVersion
from app.models.campaign import C_CLOSED
from app.models.org import (
    ROLE_ANALYST,
    ROLE_CLIENT_ADMIN,
    ROLE_CONSULTANT,
    ROLE_LEADER,
    ROLE_PARTICIPANT,
)
from app.models.response import R_SUBMITTED
from app.security.permissions import (
    P_RAW_RESPONSE,
    ROLE_PERMISSIONS,
    permissions_for,
)


def test_ningun_rol_puede_leer_respuestas_individuales():
    """Ni el superadministrador: es una capacidad excepcional, no un permiso de rol."""
    for rol, permisos in ROLE_PERMISSIONS.items():
        assert P_RAW_RESPONSE not in permisos, rol


def test_administrador_del_cliente_no_ve_comentarios_sensibles():
    from app.security.permissions import P_COMMENTS_SENSITIVE

    assert P_COMMENTS_SENSITIVE not in permissions_for(ROLE_CLIENT_ADMIN)
    assert P_COMMENTS_SENSITIVE in permissions_for(ROLE_CONSULTANT)


def test_participante_no_tiene_permisos_de_gestion():
    assert permissions_for(ROLE_PARTICIPANT) == set()


def test_analista_no_modifica_nada():
    from app.security.permissions import (
        P_ACTION_MANAGE,
        P_CAMPAIGN_MANAGE,
        P_FINDING_MANAGE,
        P_TEMPLATE_MANAGE,
    )
    permisos = permissions_for(ROLE_ANALYST)
    for p in (P_CAMPAIGN_MANAGE, P_TEMPLATE_MANAGE, P_FINDING_MANAGE, P_ACTION_MANAGE):
        assert p not in permisos


@pytest.fixture()
def org_con_resultados(make_org, make_user, make_unit, db, login):
    """Organización con una campaña cerrada y respuestas suficientes."""
    from app.services import campaigns as svc

    org = make_org("Cliente con datos")
    unidad_grande = make_unit(org, "Operaciones", headcount=30)
    unidad_chica = make_unit(org, "Dirección", headcount=4)
    version = db.execute(
        select(SurveyTemplateVersion).join(SurveyTemplateVersion.template)
        .where(SurveyTemplateVersion.status == "publicada")
        .execution_options(include_all=True)
    ).scalars().first()

    with tenant_scope(org.id):
        campaign = SurveyCampaign(
            organization_id=org.id, version_id=version.id, name="Diagnóstico",
            status="activa", segmentation_keys=["antiguedad"],
        )
        db.add(campaign)
        for i in range(34):
            unidad = unidad_grande if i < 30 else unidad_chica
            db.add(EmployeePopulation(
                organization_id=org.id, external_id=f"E{i}", org_unit_id=unidad.id,
                attributes={"antiguedad": "1 a 3 años"},
            ))
        db.commit()

        from app.services import results as results_svc
        questions = results_svc.question_map(db, version.id)
        puntuables = {qid: 4 for qid, q in questions.items() if q.qtype == "likert"}
        for i in range(24):
            unidad = unidad_grande if i < 20 else unidad_chica
            resp, _ = svc.start_anonymous(db, campaign, unidad.id)
            resp.segment = {"antiguedad": "1 a 3 años", "unit_path": [unidad.id]}
            svc.save_answers(db, resp, dict(puntuables), questions)
            svc.submit(db, resp)
        # un comentario sensible para el protocolo
        db.add(OpenComment(
            organization_id=org.id, campaign_id=campaign.id,
            text="Hay acoso de la jefatura hacia el equipo",
            redacted_text="Hay acoso de la jefatura hacia el equipo",
            is_sensitive=True, sensitive_flags=["acoso"], org_unit_id=unidad_grande.id,
        ))
        db.add(OpenComment(
            organization_id=org.id, campaign_id=campaign.id,
            text="Buen ambiente en general", redacted_text="Buen ambiente en general",
            org_unit_id=unidad_grande.id,
        ))
        campaign.status = C_CLOSED
        db.commit()
        campaign_id = campaign.id

    return {"org": org, "campaign_id": campaign_id, "grande": unidad_grande,
            "chica": unidad_chica, "make_user": make_user, "login": login}


def test_jefatura_ve_su_unidad_y_no_el_total(org_con_resultados, login):
    escenario = org_con_resultados
    jefatura = escenario["make_user"](ROLE_LEADER, escenario["org"],
                                      scope_unit_ids=[escenario["grande"].id])
    client = login(jefatura)
    slug, cid = escenario["org"].slug, escenario["campaign_id"]

    propia = client.get(f"/api/v1/o/{slug}/results/{cid}",
                        params={"org_unit_id": escenario["grande"].id}).json()
    assert propia["allowed"] is True
    assert propia["n_responses"] == 20

    total = client.get(f"/api/v1/o/{slug}/results/{cid}").json()
    assert total["allowed"] is False
    assert total["reason"] == "fuera_de_alcance"

    ajena = client.get(f"/api/v1/o/{slug}/results/{cid}",
                       params={"org_unit_id": escenario["chica"].id}).json()
    assert ajena["allowed"] is False


def test_unidad_pequena_se_suprime_para_todos(org_con_resultados, login):
    """La dirección tiene 4 personas: ni el consultor ve su desglose."""
    escenario = org_con_resultados
    consultor = escenario["make_user"](ROLE_CONSULTANT, escenario["org"])
    client = login(consultor)
    r = client.get(
        f"/api/v1/o/{escenario['org'].slug}/results/{escenario['campaign_id']}",
        params={"org_unit_id": escenario["chica"].id},
    ).json()
    assert r["allowed"] is False
    assert r["reason"] == "universo_pequeno"


def test_administrador_del_cliente_no_recibe_comentarios_sensibles(org_con_resultados, login):
    escenario = org_con_resultados
    slug, cid = escenario["org"].slug, escenario["campaign_id"]

    admin = escenario["make_user"](ROLE_CLIENT_ADMIN, escenario["org"])
    client = login(admin)
    r = client.get(f"/api/v1/o/{slug}/comments/{cid}").json()
    assert r["allowed"] is True
    textos = [c["text"] for c in r["items"]]
    assert all("acoso" not in t for t in textos)
    assert r["protocol"] is None
    assert client.get(f"/api/v1/o/{slug}/comments/{cid}",
                      params={"only_sensitive": "true"}).status_code == 403


def test_consultor_ve_los_sensibles_con_protocolo_y_queda_auditado(org_con_resultados, login, db):
    from app.models import AuditLog

    escenario = org_con_resultados
    slug, cid = escenario["org"].slug, escenario["campaign_id"]
    consultor = escenario["make_user"](ROLE_CONSULTANT, escenario["org"])
    client = login(consultor)

    r = client.get(f"/api/v1/o/{slug}/comments/{cid}", params={"only_sensitive": "true"}).json()
    assert r["allowed"] is True
    assert len(r["items"]) == 1
    assert r["protocol"]["pasos"], "se entrega el protocolo de revisión"
    assert "no un hecho probado" in r["protocol"]["advertencia"]

    registros = db.query(AuditLog).filter(
        AuditLog.action == "ver_comentario_sensible",
        AuditLog.actor_email == consultor.email,
    ).all()
    assert registros, "cada lectura de comentario sensible queda registrada"
    assert all(not (a.detail or {}).get("text") for a in registros), \
        "la bitácora nunca guarda el texto"


def test_analista_no_puede_crear_campanas(org_con_resultados, login):
    escenario = org_con_resultados
    analista = escenario["make_user"](ROLE_ANALYST, escenario["org"])
    client = login(analista)
    r = client.post(f"/api/v1/o/{escenario['org'].slug}/campaigns",
                    json={"version_id": "x", "name": "No debería"})
    assert r.status_code == 403


def test_acceso_a_respuesta_individual_esta_cerrado(org_con_resultados, login, db):
    escenario = org_con_resultados
    consultor = escenario["make_user"](ROLE_CONSULTANT, escenario["org"])
    client = login(consultor)
    with tenant_scope(escenario["org"].id):
        from app.models import SurveyResponse
        resp = db.execute(
            select(SurveyResponse).where(SurveyResponse.status == R_SUBMITTED)
        ).scalars().first()
    r = client.post(
        f"/api/v1/o/{escenario['org'].slug}/responses/{resp.id}/raw",
        json={"reason": "Necesito revisar una respuesta puntual por un reclamo interno"},
    )
    assert r.status_code == 403


def test_umbral_no_se_puede_bajar_desde_la_campana(org_con_resultados, login, db):
    escenario = org_con_resultados
    consultor = escenario["make_user"](ROLE_CONSULTANT, escenario["org"])
    client = login(consultor)
    version = db.execute(
        select(SurveyTemplateVersion).where(SurveyTemplateVersion.status == "publicada")
        .execution_options(include_all=True)
    ).scalars().first()
    r = client.post(f"/api/v1/o/{escenario['org'].slug}/campaigns", json={
        "version_id": version.id, "name": "Con umbral bajo", "anonymity_threshold": 3,
    })
    assert r.status_code == 422
    assert "no puede ser menor" in r.json()["detail"]
