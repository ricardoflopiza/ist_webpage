# -*- coding: utf-8 -*-
"""Confidencialidad: umbrales, supresión y datos personales."""
from __future__ import annotations

from app.models.campaign import C_ACTIVE, C_CLOSED
from app.models.org import ROLE_CLIENT_ADMIN, ROLE_LEADER, ROLE_PARTICIPANT
from app.security.deps import Viewer
from app.security.permissions import permissions_for
from app.services.anonymity import (
    can_display_segment,
    detect_sensitive,
    effective_threshold,
    redact_personal_data,
    suppress_small_groups,
)


class FakeOrg:
    def __init__(self, threshold=7):
        self.anonymity_threshold = threshold
        self.min_item_completion = 0.6


class FakeCampaign:
    def __init__(self, status=C_CLOSED, threshold=None):
        self.status = status
        self.anonymity_threshold = threshold


def viewer(role=ROLE_CLIENT_ADMIN, org=None, scope=None):
    v = Viewer(user=object(), organization=org or FakeOrg(), role=role,
               permissions=permissions_for(role), scope_unit_ids=scope or [])
    return v


def test_segmento_bajo_el_umbral_no_se_muestra():
    d = can_display_segment({}, viewer(), FakeCampaign(), n_responses=6)
    assert d.allowed is False
    assert d.reason == "bajo_umbral"
    assert "7" in d.message


def test_segmento_sobre_el_umbral_se_muestra():
    assert can_display_segment({}, viewer(), FakeCampaign(), n_responses=7).allowed is True


def test_la_campania_puede_endurecer_el_umbral_pero_no_relajarlo():
    org = FakeOrg(7)
    assert effective_threshold(org, FakeCampaign(threshold=12)) == 12
    assert effective_threshold(org, FakeCampaign(threshold=3)) == 7


def test_cruzar_muchas_variables_sube_el_umbral():
    org = FakeOrg(8)
    filtros = {"org_unit_id": "u", "antiguedad": "1-3", "modalidad": "Remoto"}
    assert effective_threshold(org, None, n_filters=3) == 12   # 8 × 1,5
    d = can_display_segment(filtros, viewer(org=org), FakeCampaign(), organization=org,
                            n_responses=10)
    assert d.allowed is False
    assert d.reason == "cruce_riesgoso"


def test_universo_pequeno_bloquea_aunque_respondan_todos():
    """Cuatro respuestas de un equipo de cuatro identifican a las cuatro personas."""
    d = can_display_segment({"org_unit_id": "u"}, viewer(), FakeCampaign(),
                            n_responses=30, n_universe=4)
    assert d.allowed is False
    assert d.reason == "universo_pequeno"


def test_no_hay_resultados_con_la_campania_abierta():
    d = can_display_segment({}, viewer(), FakeCampaign(status=C_ACTIVE), n_responses=500)
    assert d.allowed is False
    assert d.reason == "campania_abierta"


def test_participante_nunca_ve_segmentos():
    d = can_display_segment({}, viewer(role=ROLE_PARTICIPANT), FakeCampaign(), n_responses=999)
    assert d.allowed is False
    assert d.reason == "sin_permiso"


def test_jefatura_solo_ve_sus_unidades():
    v = viewer(role=ROLE_LEADER, scope=["unidad-a"])
    assert can_display_segment({"org_unit_id": "unidad-a"}, v, FakeCampaign(),
                               n_responses=20).allowed is True
    fuera = can_display_segment({"org_unit_id": "unidad-b"}, v, FakeCampaign(), n_responses=20)
    assert fuera.allowed is False
    assert fuera.reason == "fuera_de_alcance"
    global_ = can_display_segment({}, v, FakeCampaign(), n_responses=500)
    assert global_.allowed is False, "una jefatura no ve el total de la organización"


def test_supresion_de_grupos_pequenos_borra_los_valores():
    grupos = [{"label": "A", "n": 20, "score": 70}, {"label": "B", "n": 3, "score": 40},
              {"label": "C", "n": 15, "score": 65}]
    out = suppress_small_groups(grupos, 7)
    b = next(g for g in out if g["label"] == "B")
    assert b["suppressed"] is True
    assert b["score"] is None and b["n"] is None, "no basta con no dibujarlo: no se entrega"
    assert next(g for g in out if g["label"] == "A")["score"] == 70


def test_supresion_complementaria_evita_deducir_por_diferencia():
    """Si queda un solo grupo visible y lo oculto es pequeño, se deduce restando."""
    grupos = [{"label": "A", "n": 20, "score": 70}, {"label": "B", "n": 4, "score": 40}]
    out = suppress_small_groups(grupos, 7)
    assert all(g["suppressed"] for g in out)


def test_ocultamiento_de_datos_personales():
    texto = ("Hablar con juan@empresa.cl o al +56 9 8765 4321, rut 12.345.678-9, "
             "ver https://interno.cl/doc")
    limpio = redact_personal_data(texto)
    assert "juan@empresa.cl" not in limpio
    assert "8765" not in limpio
    assert "12.345.678-9" not in limpio
    assert "interno.cl" not in limpio


def test_deteccion_de_menciones_sensibles():
    assert "acoso" in detect_sensitive("Hay acoso permanente en el área")
    assert "discriminacion" in detect_sensitive("Existe trato discriminatorio")
    assert "violencia" in detect_sensitive("Hubo una agresión en la faena")
    assert detect_sensitive("Falta café en la cocina") == []
