# -*- coding: utf-8 -*-
"""Aislamiento entre organizaciones.

Estos tests intentan activamente robar datos de otro tenant: manipulan la URL,
pasan identificadores ajenos en el cuerpo y consultan sin contexto.
"""
from __future__ import annotations

import pytest

from app.db import TenantIsolationError, tenant_scope
from app.models import Finding, OrgUnit, SurveyCampaign
from app.models.org import ROLE_CLIENT_ADMIN, ROLE_CONSULTANT


@pytest.fixture()
def dos_orgs(make_org, make_user, make_unit, db):
    a, b = make_org("Empresa A"), make_org("Empresa B")
    user_a = make_user(ROLE_CONSULTANT, a)
    user_b = make_user(ROLE_CONSULTANT, b)
    unit_a = make_unit(a, "Área A")
    unit_b = make_unit(b, "Área B")
    with tenant_scope(a.id):
        db.add(Finding(organization_id=a.id, title="Hallazgo interno de A"))
        db.commit()
    with tenant_scope(b.id):
        db.add(Finding(organization_id=b.id, title="Hallazgo interno de B"))
        db.commit()
    return {"a": a, "b": b, "user_a": user_a, "user_b": user_b,
            "unit_a": unit_a, "unit_b": unit_b}


def test_el_filtro_se_aplica_sin_pedirlo(db, dos_orgs):
    """Una consulta sin `where` explícito ya viene filtrada por el guard central."""
    with tenant_scope(dos_orgs["a"].id):
        titulos = [f.title for f in db.query(Finding).all()]
    assert titulos == ["Hallazgo interno de A"]

    with tenant_scope(dos_orgs["b"].id):
        titulos = [f.title for f in db.query(Finding).all()]
    assert titulos == ["Hallazgo interno de B"]


def test_get_por_id_ajeno_devuelve_nada(db, dos_orgs):
    ajena = dos_orgs["unit_b"].id
    with tenant_scope(dos_orgs["a"].id):
        assert db.query(OrgUnit).filter(OrgUnit.id == ajena).one_or_none() is None


def test_escribir_para_otra_organizacion_falla(db, dos_orgs):
    with tenant_scope(dos_orgs["a"].id):
        db.add(Finding(organization_id=dos_orgs["b"].id, title="Inyectado"))
        with pytest.raises(TenantIsolationError):
            db.commit()
    db.rollback()


def test_api_de_otra_organizacion_responde_404(login, dos_orgs):
    """Cambiar el slug en la URL no abre la puerta (404, no 403: no se confirma
    la existencia de recursos ajenos)."""
    client = login(dos_orgs["user_a"])
    r = client.get(f"/api/v1/o/{dos_orgs['b'].slug}")
    assert r.status_code == 404


def test_listado_de_organizaciones_solo_muestra_las_propias(login, dos_orgs):
    client = login(dos_orgs["user_a"])
    slugs = [o["slug"] for o in client.get("/api/v1/organizations").json()["items"]]
    assert dos_orgs["a"].slug in slugs
    assert dos_orgs["b"].slug not in slugs


def test_hallazgos_de_otra_organizacion_no_aparecen(login, dos_orgs):
    client = login(dos_orgs["user_a"])
    r = client.get(f"/api/v1/o/{dos_orgs['a'].slug}/findings")
    titulos = [f["title"] for f in r.json()["items"]]
    assert "Hallazgo interno de B" not in titulos


def test_no_se_puede_asociar_una_unidad_ajena(login, dos_orgs):
    client = login(dos_orgs["user_a"])
    r = client.post(
        f"/api/v1/o/{dos_orgs['a'].slug}/units",
        json={"kind": "team", "name": "Equipo colado", "parent_id": dos_orgs["unit_b"].id},
    )
    assert r.status_code == 422


def test_campania_de_otro_tenant_no_es_alcanzable(login, dos_orgs, db):
    with tenant_scope(dos_orgs["b"].id):
        from app.models import SurveyTemplateVersion
        version = db.query(SurveyTemplateVersion).first()
        campaign = SurveyCampaign(organization_id=dos_orgs["b"].id, version_id=version.id,
                                  name="Campaña de B")
        db.add(campaign)
        db.commit()
        campaign_id = campaign.id

    client = login(dos_orgs["user_a"])
    slug = dos_orgs["a"].slug
    for url in (
        f"/api/v1/o/{slug}/campaigns/{campaign_id}",
        f"/api/v1/o/{slug}/results/{campaign_id}",
        f"/api/v1/o/{slug}/reports/{campaign_id}/executive",
        f"/api/v1/o/{slug}/comments/{campaign_id}",
    ):
        assert client.get(url).status_code == 404, url


def test_usuario_sin_membresia_no_entra(login, make_user, dos_orgs):
    extranio = make_user(ROLE_CLIENT_ADMIN, None)
    client = login(extranio)
    assert client.get(f"/api/v1/o/{dos_orgs['a'].slug}").status_code == 404


def test_superadministrador_ve_todo_pero_queda_registrado(login, make_user, dos_orgs, db):
    from app.models import AuditLog

    sa = make_user(superadmin=True)
    client = login(sa)
    assert client.get(f"/api/v1/o/{dos_orgs['a'].slug}").status_code == 200
    assert client.get(f"/api/v1/o/{dos_orgs['b'].slug}").status_code == 200
    logins = db.query(AuditLog).filter(AuditLog.actor_email == sa.email).all()
    assert logins, "el ingreso del superadministrador queda en la bitácora"
