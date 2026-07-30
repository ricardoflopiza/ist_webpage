# -*- coding: utf-8 -*-
"""Cálculo de resultados: la parte que no puede estar mal."""
from __future__ import annotations

import pytest

from app.services.scales import get_scale
from app.services.scoring import (
    DimensionDef,
    Instrument,
    ItemDef,
    ResponseData,
    aggregate,
    confidence_interval,
    item_scores,
    person_dimension_map,
    polarization,
)

ACUERDO = get_scale("acuerdo")


def item(code, reverse=False, scale="acuerdo"):
    return ItemDef(id=code, code=code, text=code, dimension_code="d",
                   scale=get_scale(scale), is_reverse=reverse)


def resp(rid, values):
    return ResponseData(id=rid, values=values)


def test_normalizacion_likert_1_a_5():
    """((valor - 1) / 4) * 100, tal como exige la especificación."""
    assert ACUERDO.to_100(1) == 0.0
    assert ACUERDO.to_100(3) == 50.0
    assert ACUERDO.to_100(4) == 75.0
    assert ACUERDO.to_100(5) == 100.0


def test_normalizacion_escala_0_a_10():
    nps = get_scale("recomendacion")
    assert nps.to_100(0) == 0.0
    assert nps.to_100(5) == 50.0
    assert nps.to_100(10) == 100.0


def test_bandas_de_favorabilidad():
    assert ACUERDO.band(5) == "favorable"
    assert ACUERDO.band(4) == "favorable"
    assert ACUERDO.band(3) == "neutral"
    assert ACUERDO.band(2) == "desfavorable"
    assert ACUERDO.band(1) == "desfavorable"
    nps = get_scale("recomendacion")
    assert nps.band(9) == "favorable"
    assert nps.band(7) == "neutral"
    assert nps.band(6) == "desfavorable"


def test_item_invertido_se_recodifica_antes_de_calcular():
    directo = item("a")
    inverso = item("b", reverse=True)
    r = [resp("1", {"a": 2, "b": 2})]
    assert item_scores(directo, r) == [25.0]
    # 2 invertido = 4 → 75
    assert item_scores(inverso, r) == [75.0]


def test_dimension_no_se_calcula_bajo_la_cobertura_minima():
    d = DimensionDef(code="d", name="D", items=[item("a"), item("b"), item("c"), item("d4")])
    completa = resp("1", {"a": 4, "b": 4, "c": 4})       # 3/4 = 75 % ≥ 60 %
    incompleta = resp("2", {"a": 5})                      # 1/4 = 25 % < 60 %
    scores = person_dimension_map(d, [completa, incompleta], 0.6)
    assert list(scores) == ["1"]
    assert scores["1"] == 75.0


def test_cobertura_minima_es_parametrizable():
    d = DimensionDef(code="d", name="D", items=[item("a"), item("b"), item("c"), item("d4")])
    parcial = resp("2", {"a": 5})
    assert person_dimension_map(d, [parcial], 0.6) == {}
    assert person_dimension_map(d, [parcial], 0.2) == {"2": 100.0}


def test_promedio_por_persona_antes_que_entre_personas():
    """Quien responde más ítems no debe pesar más en el promedio de la dimensión."""
    d = DimensionDef(code="d", name="D", items=[item("a"), item("b")])
    r = [resp("1", {"a": 5, "b": 5}), resp("2", {"a": 1, "b": 1})]
    scores = person_dimension_map(d, r, 0.6)
    assert sorted(scores.values()) == [0.0, 100.0]


def test_na_no_entra_al_calculo():
    """Un 'No aplica' llega como ausencia de valor: ni numerador ni denominador."""
    d = DimensionDef(code="d", name="D", items=[item("a"), item("b")])
    r = [resp("1", {"a": 5})]                     # 'b' respondida como No aplica
    assert person_dimension_map(d, r, 0.5) == {"1": 100.0}


def test_intervalo_de_confianza_requiere_muestra_minima():
    assert confidence_interval([50.0] * 4) is None
    ic = confidence_interval([40.0, 50.0, 60.0, 55.0, 45.0])
    assert ic is not None and ic[0] < 50.0 < ic[1]


def test_polarizacion_distingue_consenso_de_opiniones_divididas():
    consenso = polarization({"favorable": 0, "neutral": 100, "desfavorable": 0})
    dividido = polarization({"favorable": 50, "neutral": 0, "desfavorable": 50})
    assert consenso == 0.0
    assert dividido == 1.0


def test_variables_de_resultado_no_se_promedian_con_el_clima():
    clima = DimensionDef(code="liderazgo", name="Liderazgo", items=[item("a")])
    outcome = DimensionDef(code="compromiso", name="Compromiso", is_outcome=True,
                           items=[item("b")])
    instrument = Instrument(dimensions=[clima, outcome])
    r = [resp("1", {"a": 1, "b": 5})]          # clima 0, resultado 100
    out = aggregate(instrument, r, min_completion=0.5)
    assert out["general_score"] == 0.0          # sólo dimensiones de clima
    assert [o["code"] for o in out["outcomes"]] == ["compromiso"]
    assert [d["code"] for d in out["dimensions"]] == ["liderazgo"]


def test_porcentajes_de_favorabilidad_suman_cien():
    d = DimensionDef(code="d", name="D", items=[item("a")])
    r = [resp("1", {"a": 5}), resp("2", {"a": 3}), resp("3", {"a": 1}), resp("4", {"a": 4})]
    out = aggregate(Instrument(dimensions=[d]), r, min_completion=0.5)
    dim = out["dimensions"][0]
    assert dim["favorable_pct"] == 50.0
    assert dim["neutral_pct"] == 25.0
    assert dim["unfavorable_pct"] == 25.0


def test_indices_agregados_van_marcados_como_hipotesis():
    dims = [
        DimensionDef(code=c, name=c, index_key="gestion_organizacional", items=[item(f"i{c}")])
        for c in ("liderazgo", "comunicacion")
    ]
    r = [resp("1", {"iliderazgo": 4, "icomunicacion": 4})]
    out = aggregate(Instrument(dimensions=dims), r, min_completion=0.5)
    assert out["indices"], "debería calcularse el índice de gestión organizacional"
    for i in out["indices"]:
        assert i["is_hypothesis"] is True
        assert "validación psicométrica" in i["note"]


@pytest.mark.parametrize("valor,esperado", [(1, 5), (2, 4), (3, 3), (4, 2), (5, 1)])
def test_recodificacion_es_simetrica(valor, esperado):
    assert ACUERDO.reverse(valor) == esperado
