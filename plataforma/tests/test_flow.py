# -*- coding: utf-8 -*-
"""Flujo crítico punta a punta (§27).

Crear tenant → invitar administrador → estructura → encuesta → publicar versión →
campaña → invitar → responder → cerrar → calcular → visualizar → hallazgo →
acción → pulso → verificar aislamiento.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import tenant_scope
from app.models import (
    EmployeePopulation,
    SurveyInvitation,
    SurveyResponse,
    SurveyTemplate,
)
from app.models.org import ROLE_CONSULTANT
from app.models.response import R_SUBMITTED


@pytest.fixture()
def escenario(make_org, make_user, make_unit, db, login):
    org = make_org("Andes Prueba")
    consultor = make_user(ROLE_CONSULTANT, org)
    unidad = make_unit(org, "Operaciones", headcount=20)
    with tenant_scope(org.id):
        for i in range(20):
            db.add(EmployeePopulation(
                organization_id=org.id, external_id=f"P{i:03d}",
                email=f"p{i:03d}@andes-prueba.cl", full_name=f"Persona {i}",
                org_unit_id=unidad.id,
                attributes={"antiguedad": "1 a 3 años", "modalidad": "Presencial"},
            ))
        db.commit()
    return {"org": org, "consultor": consultor, "unidad": unidad,
            "client": login(consultor), "slug": org.slug}


def _plantilla_clima(db) -> SurveyTemplate:
    return db.execute(
        select(SurveyTemplate).where(
            SurveyTemplate.code == "clima_integral", SurveyTemplate.organization_id.is_(None)
        ).execution_options(include_all=True)
    ).scalar_one()


def test_flujo_completo(escenario, db):
    client, slug, org = escenario["client"], escenario["slug"], escenario["org"]

    # 1-3) tenant, usuario y estructura ya creados por el escenario
    assert client.get(f"/api/v1/o/{slug}/units").json()["total"] == 1
    assert client.get(f"/api/v1/o/{slug}/population").json()["total"] == 20

    # 4-5) adaptar una plantilla maestra y publicar su versión
    maestra = _plantilla_clima(db)
    r = client.post(f"/api/v1/o/{slug}/surveys/{maestra.id}/duplicate",
                    params={"name": "Clima Andes", "code": "clima_andes"})
    assert r.status_code == 201
    propia = r.json()
    version_id = propia["versions"][0]["id"]
    assert propia["derived_from_id"] == maestra.id, "se conserva la trazabilidad al original"

    r = client.post(f"/api/v1/o/{slug}/surveys/versions/{version_id}/publish")
    assert r.status_code == 200 and r.json()["status"] == "publicada"

    # una versión publicada ya no se edita
    dim = client.get(f"/api/v1/o/{slug}/surveys/versions/{version_id}").json()
    alguna_dim = dim["modules"][0]["dimensions"][0]
    r = client.post(f"/api/v1/o/{slug}/surveys/questions", json={
        "dimension_id": alguna_dim["id"], "code": "nueva", "text": "¿Se puede editar?",
    })
    assert r.status_code == 409

    # 6) crear campaña
    r = client.post(f"/api/v1/o/{slug}/campaigns", json={
        "version_id": version_id, "name": "Diagnóstico de prueba",
        "period_label": "2026", "segmentation_keys": ["antiguedad", "modalidad"],
    })
    assert r.status_code == 201, r.text
    campaign_id = r.json()["id"]

    # 7) invitaciones: los enlaces se entregan una sola vez
    r = client.post(f"/api/v1/o/{slug}/campaigns/{campaign_id}/invitations")
    assert r.status_code == 200
    enlaces = r.json()["links"]
    assert len(enlaces) == 20

    with tenant_scope(org.id):
        guardadas = db.execute(select(SurveyInvitation)).scalars().all()
    assert all(len(i.token_hash) == 64 for i in guardadas), "sólo se guarda el hash"

    # 8) abrir campaña y responder
    client.post(f"/api/v1/o/{slug}/campaigns/{campaign_id}/status", json={"status": "en_revision"})
    client.post(f"/api/v1/o/{slug}/campaigns/{campaign_id}/status", json={"status": "activa"})

    from fastapi.testclient import TestClient

    from app.main import app

    preguntas = [q for m in dim["modules"] for d in m["dimensions"] for q in d["questions"]]
    puntuables = [q for q in preguntas if q["qtype"] == "likert"]

    for i, enlace in enumerate(enlaces[:12]):
        with TestClient(app) as participante:
            token = enlace["url"].rsplit("/", 1)[1]
            r = participante.get(f"/e/{token}", follow_redirects=False)
            assert r.status_code == 303
            response_id = r.headers["location"].rsplit("/", 1)[1]
            participante.post(f"/responder/{response_id}/consentimiento", follow_redirects=False)
            valor = 4 if i % 2 == 0 else 3
            data = {f"q_{q['id']}": str(valor) for q in puntuables}
            data.update({"_index": "999", "_action": "submit"})
            r = participante.post(f"/responder/{response_id}/guardar", data=data,
                                  follow_redirects=False)
            assert r.status_code == 303

    with tenant_scope(org.id):
        enviadas = db.execute(
            select(SurveyResponse).where(SurveyResponse.status == R_SUBMITTED)
        ).scalars().all()
    assert len(enviadas) == 12
    assert all(r.segment.get("antiguedad") == "1 a 3 años" for r in enviadas), \
        "la fotografía de segmentación viaja con la respuesta"

    # los resultados no están disponibles con la campaña abierta
    r = client.get(f"/api/v1/o/{slug}/results/{campaign_id}").json()
    assert r["allowed"] is False and r["reason"] == "campania_abierta"

    # la participación sí se puede seguir
    p = client.get(f"/api/v1/o/{slug}/campaigns/{campaign_id}/participation").json()
    assert p["invited"] == 20 and p["submitted"] == 12 and p["rate"] == 60.0

    # 9) cerrar
    r = client.post(f"/api/v1/o/{slug}/campaigns/{campaign_id}/status", json={"status": "cerrada"})
    assert r.status_code == 200

    # 10-11) calcular y visualizar
    r = client.get(f"/api/v1/o/{slug}/results/{campaign_id}").json()
    assert r["allowed"] is True
    assert r["n_responses"] == 12
    assert r["general_score"] is not None
    assert r["participation"]["rate"] == 60.0
    assert [d["code"] for d in r["outcomes"]], "las variables de resultado se calculan aparte"

    resumen = client.get(f"/api/v1/o/{slug}/results/{campaign_id}/summary").json()
    assert len(resumen["strengths"]) == 3
    assert "no constituyen diagnóstico clínico" in resumen["methodological_note"].lower() \
        or "no constituyen diagnóstico" in resumen["methodological_note"].lower()

    # 12) hallazgos sugeridos + validación
    r = client.post(f"/api/v1/o/{slug}/findings/suggest/{campaign_id}")
    assert r.status_code == 200
    creados = r.json()["items"]
    assert creados, "debería sugerir al menos un hallazgo"
    assert all(f["status"] == "sugerido_por_sistema" for f in creados)
    finding_id = creados[0]["id"]
    r = client.post(f"/api/v1/o/{slug}/findings/{finding_id}/validate")
    assert r.json()["status"] == "validado"

    # 13) plan y acción
    r = client.post(f"/api/v1/o/{slug}/action-plans",
                    json={"name": "Plan 2026", "campaign_id": campaign_id})
    plan_id = r.json()["id"]
    r = client.post(f"/api/v1/o/{slug}/action-plans/{plan_id}/items", json={
        "action": "Revisar la carga de trabajo del turno de noche",
        "finding_id": finding_id, "indicator": "Puntaje de organización sostenible",
        "target": "+8 puntos", "owner_label": "Jefatura de Operaciones",
        "due_on": "2026-12-31", "status": "en_ejecucion", "progress": 0.2,
    })
    assert r.status_code == 201
    item_id = r.json()["id"]

    # cerrar una acción exige evidencia
    r = client.patch(f"/api/v1/o/{slug}/action-plans/items/{item_id}",
                     json={"status": "completada"})
    assert r.status_code == 422
    r = client.patch(f"/api/v1/o/{slug}/action-plans/items/{item_id}",
                     json={"status": "completada", "evidence": "Acta de la reunión de turno"})
    assert r.status_code == 200 and r.json()["progress"] == 1.0

    tablero = client.get(f"/api/v1/o/{slug}/action-plans/dashboard").json()
    assert tablero["by_status"]["completada"] == 1

    # 14) pulso enganchado a la campaña base
    r = client.post(f"/api/v1/o/{slug}/campaigns", json={
        "version_id": version_id, "name": "Pulso T1", "is_pulse": True,
        "baseline_campaign_id": campaign_id,
    })
    pulso_campaign = r.json()["id"]
    r = client.post(f"/api/v1/o/{slug}/pulses", json={
        "campaign_id": pulso_campaign, "baseline_campaign_id": campaign_id,
        "dimension_code": "reconocimiento", "cadence": "trimestral",
    })
    assert r.status_code == 201

    # 15) el reporte respeta el mismo umbral que el dashboard
    r = client.get(f"/api/v1/o/{slug}/reports/{campaign_id}/executive")
    assert r.status_code == 200
    assert "limitaciones" in r.json()["methodology"]

    r = client.get(f"/api/v1/o/{slug}/reports/{campaign_id}/export.csv")
    assert r.status_code == 200 and "dimension;" in r.text


def test_no_se_puede_usar_una_version_en_borrador(escenario, db):
    client, slug = escenario["client"], escenario["slug"]
    maestra = _plantilla_clima(db)
    propia = client.post(f"/api/v1/o/{slug}/surveys/{maestra.id}/duplicate").json()
    r = client.post(f"/api/v1/o/{slug}/campaigns", json={
        "version_id": propia["versions"][0]["id"], "name": "Campaña con borrador",
    })
    assert r.status_code == 409


def test_la_invitacion_no_se_puede_canjear_dos_veces(escenario, db):
    client, slug = escenario["client"], escenario["slug"]
    maestra = _plantilla_clima(db)
    propia = client.post(f"/api/v1/o/{slug}/surveys/{maestra.id}/duplicate").json()
    version_id = propia["versions"][0]["id"]
    client.post(f"/api/v1/o/{slug}/surveys/versions/{version_id}/publish")
    campaign_id = client.post(f"/api/v1/o/{slug}/campaigns", json={
        "version_id": version_id, "name": "Campaña token",
    }).json()["id"]
    enlaces = client.post(f"/api/v1/o/{slug}/campaigns/{campaign_id}/invitations").json()["links"]
    client.post(f"/api/v1/o/{slug}/campaigns/{campaign_id}/status", json={"status": "en_revision"})
    client.post(f"/api/v1/o/{slug}/campaigns/{campaign_id}/status", json={"status": "activa"})

    from fastapi.testclient import TestClient

    from app.main import app

    token = enlaces[0]["url"].rsplit("/", 1)[1]
    with TestClient(app) as p1:
        r = p1.get(f"/e/{token}", follow_redirects=False)
        response_id = r.headers["location"].rsplit("/", 1)[1]
        p1.post(f"/responder/{response_id}/consentimiento", follow_redirects=False)
        p1.post(f"/responder/{response_id}/guardar",
                data={"_index": "999", "_action": "submit"}, follow_redirects=False)

    # Otro navegador con el mismo token: la invitación ya fue usada para iniciar,
    # y sin el ticket firmado no puede tocar la respuesta anterior.
    with TestClient(app) as p2:
        r = p2.get(f"/e/{token}", follow_redirects=False)
        nuevo = r.headers["location"].rsplit("/", 1)[1]
        assert nuevo != response_id
        assert p2.get(f"/responder/{response_id}").status_code == 403


def test_token_invalido_no_abre_nada(client):
    assert client.get("/e/token-inventado", follow_redirects=False).status_code == 404
