# -*- coding: utf-8 -*-
"""Motor de cálculo de resultados (§13 y §14).

Vive **en el servidor**: el navegador recibe agregados ya calculados y nunca la
lógica ni las respuestas crudas. Es determinista y sin dependencias de la base de
datos en su núcleo (`aggregate()` opera sobre estructuras planas), de modo que se
puede testear ítem a ítem.

Reglas de negocio implementadas
-------------------------------
* Normalización a 0-100 según la escala de cada ítem (Likert 1-5 → (v-1)/4·100).
* Ítems invertidos: se recodifican ANTES de cualquier promedio.
* Una dimensión no se calcula para una persona que respondió menos del
  `min_item_completion` de sus ítems (por defecto 60 %, parametrizable).
* Las respuestas "No aplica" no cuentan ni en el numerador ni en el denominador.
* Las variables de resultado (`is_outcome`) se calculan aparte: no se promedian
  con las dimensiones de clima.
* Los índices agregados (§14) son **hipótesis de agrupación** y viajan marcados
  como tales (`is_hypothesis: True`) para que la interfaz lo advierta.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .scales import Scale

ENGINE_VERSION = "1.0"


# ------------------------------------------------------------------ estructuras
@dataclass
class ItemDef:
    id: str
    code: str
    text: str
    dimension_code: str
    scale: Scale
    is_reverse: bool = False
    qtype: str = "likert"


@dataclass
class DimensionDef:
    code: str
    name: str
    is_outcome: bool = False
    index_key: str | None = None
    items: list[ItemDef] = field(default_factory=list)


@dataclass
class Instrument:
    dimensions: list[DimensionDef] = field(default_factory=list)

    @property
    def items(self) -> list[ItemDef]:
        return [i for d in self.dimensions for i in d.items]

    def by_code(self, code: str) -> DimensionDef | None:
        return next((d for d in self.dimensions if d.code == code), None)


@dataclass
class ResponseData:
    """Una respuesta enviada: {question_id: valor} más su segmento."""

    id: str
    values: dict[str, float]
    segment: dict = field(default_factory=dict)
    org_unit_id: str | None = None


# ------------------------------------------------------------------ estadística
def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def stdev(xs: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def confidence_interval(xs: list[float], z: float = 1.96) -> tuple[float, float] | None:
    """IC 95 % de la media (aproximación normal). Con n<5 no se reporta:
    el intervalo sería tan ancho que induce a error."""
    if len(xs) < 5:
        return None
    m = sum(xs) / len(xs)
    sd = stdev(xs) or 0.0
    half = z * sd / math.sqrt(len(xs))
    return (round(max(0.0, m - half), 1), round(min(100.0, m + half), 1))


def polarization(distribution: dict[str, int]) -> float | None:
    """Cuánto se reparte la opinión entre extremos (0 = consenso, 1 = polarizada).

    Se reporta junto al promedio porque un 50 % muy de acuerdo y 50 % muy en
    desacuerdo produce el mismo promedio que un 100 % neutral, y no significan
    lo mismo.
    """
    total = sum(distribution.values())
    if not total:
        return None
    fav = distribution.get("favorable", 0) / total
    unf = distribution.get("desfavorable", 0) / total
    return round(4 * fav * unf, 3)


# ------------------------------------------------------------------ cálculo
def item_scores(item: ItemDef, responses: list[ResponseData]) -> list[float]:
    """Puntajes 0-100 del ítem, ya recodificado si es invertido."""
    out = []
    for r in responses:
        raw = r.values.get(item.id)
        if raw is None:
            continue
        value = item.scale.reverse(raw) if item.is_reverse else raw
        out.append(item.scale.to_100(value))
    return out


def item_bands(item: ItemDef, responses: list[ResponseData]) -> dict[str, int]:
    bands = {"favorable": 0, "neutral": 0, "desfavorable": 0}
    for r in responses:
        raw = r.values.get(item.id)
        if raw is None:
            continue
        value = item.scale.reverse(raw) if item.is_reverse else raw
        bands[item.scale.band(value)] += 1
    return bands


def item_distribution(item: ItemDef, responses: list[ResponseData]) -> dict[str, int]:
    """Distribución completa por punto de la escala (no sólo fav/neu/desf)."""
    dist = {str(v): 0 for v in range(item.scale.min_value, item.scale.max_value + 1)}
    for r in responses:
        raw = r.values.get(item.id)
        if raw is None:
            continue
        value = item.scale.reverse(raw) if item.is_reverse else raw
        key = str(int(round(value)))
        if key in dist:
            dist[key] += 1
    return dist


def person_dimension_map(
    dimension: DimensionDef, responses: list[ResponseData], min_completion: float
) -> dict[str, float]:
    """Puntaje 0-100 de la dimensión **por persona**, indexado por respuesta.

    Se promedia primero dentro de la persona y después entre personas: así una
    persona que respondió 8 ítems no pesa el doble que otra que respondió 4.
    Quien no alcanzó `min_completion` de ítems no aparece: no se le imputa nada.
    """
    scorable = [i for i in dimension.items if i.qtype in ("likert", "numeric", "nps")]
    if not scorable:
        return {}
    needed = max(1, math.ceil(len(scorable) * min_completion))
    out: dict[str, float] = {}
    for r in responses:
        vals = []
        for item in scorable:
            raw = r.values.get(item.id)
            if raw is None:
                continue
            value = item.scale.reverse(raw) if item.is_reverse else raw
            vals.append(item.scale.to_100(value))
        if len(vals) >= needed:
            out[r.id] = sum(vals) / len(vals)
    return out


def person_dimension_scores(
    dimension: DimensionDef, responses: list[ResponseData], min_completion: float
) -> list[float]:
    return list(person_dimension_map(dimension, responses, min_completion).values())


def aggregate(
    instrument: Instrument,
    responses: list[ResponseData],
    *,
    min_completion: float = 0.6,
    baseline: dict | None = None,
    benchmark: dict | None = None,
) -> dict:
    """Agrega una lista de respuestas en el payload de resultados.

    `baseline` y `benchmark` son diccionarios {codigo_dimension: puntaje} para
    calcular variación y comparación. Nunca se comparan versiones distintas del
    instrumento: eso lo controla quien llama (`results.py`).
    """
    dimensions, outcomes = [], []
    person_scores: dict[str, dict[str, float]] = {}

    for d in instrument.dimensions:
        per_person = person_dimension_map(d, responses, min_completion)
        person_scores[d.code] = per_person
        scores = list(per_person.values())

        bands = {"favorable": 0, "neutral": 0, "desfavorable": 0}
        items_payload = []
        for item in d.items:
            if item.qtype not in ("likert", "numeric", "nps"):
                continue
            ib = item_bands(item, responses)
            for k in bands:
                bands[k] += ib[k]
            iscores = item_scores(item, responses)
            items_payload.append({
                "code": item.code,
                "text": item.text,
                "score": round(mean(iscores), 1) if iscores else None,
                "n": len(iscores),
                "favorable_pct": _pct(ib["favorable"], sum(ib.values())),
                "distribution": item_distribution(item, responses),
                "is_reverse": item.is_reverse,
            })

        total_bands = sum(bands.values())
        score = mean(scores)
        payload = {
            "code": d.code,
            "name": d.name,
            "is_outcome": d.is_outcome,
            "index_key": d.index_key,
            "n": len(scores),
            "score": round(score, 1) if score is not None else None,
            "sd": round(stdev(scores), 1) if stdev(scores) is not None else None,
            "ci95": confidence_interval(scores),
            "favorable_pct": _pct(bands["favorable"], total_bands),
            "neutral_pct": _pct(bands["neutral"], total_bands),
            "unfavorable_pct": _pct(bands["desfavorable"], total_bands),
            "distribution": bands,
            "polarization": polarization(bands),
            "items": sorted(
                items_payload, key=lambda i: (i["score"] is None, i["score"])
            ),
            "best_item": _extreme(items_payload, best=True),
            "worst_item": _extreme(items_payload, best=False),
        }
        if baseline and d.code in baseline and payload["score"] is not None:
            prev = baseline[d.code]
            payload["baseline"] = prev
            payload["delta"] = round(payload["score"] - prev, 1) if prev is not None else None
        if benchmark and d.code in benchmark and payload["score"] is not None:
            bm = benchmark[d.code]
            payload["benchmark"] = bm
            payload["benchmark_delta"] = round(payload["score"] - bm, 1) if bm is not None else None

        (outcomes if d.is_outcome else dimensions).append(payload)

    climate = [d for d in dimensions if d["score"] is not None]
    general = round(sum(d["score"] for d in climate) / len(climate), 1) if climate else None

    return {
        "engine_version": ENGINE_VERSION,
        "n_responses": len(responses),
        "min_item_completion": min_completion,
        "general_score": general,
        "dimensions": dimensions,
        "outcomes": outcomes,
        "indices": _indices(dimensions),
        "person_scores": person_scores,   # insumo del análisis de impulsores
    }


def _pct(part: int, total: int) -> float | None:
    return round(part / total * 100, 1) if total else None


def _extreme(items: list[dict], best: bool) -> dict | None:
    scored = [i for i in items if i["score"] is not None]
    if not scored:
        return None
    return (max if best else min)(scored, key=lambda i: i["score"])


# Agrupaciones hipotéticas del §14. Se marcan como hipótesis: requieren
# validación psicométrica (análisis factorial / alfa) antes de tratarlas como
# constructos. La interfaz lo advierte de forma explícita.
INDEX_DEFINITIONS = {
    "gestion_organizacional": {
        "name": "Gestión organizacional",
        "dimensions": ["liderazgo", "comunicacion", "claridad_coordinacion",
                       "autonomia_participacion", "reconocimiento", "desarrollo"],
    },
    "confianza_relaciones": {
        "name": "Confianza y relaciones",
        "dimensions": ["justicia_confianza", "colaboracion", "seguridad_psicologica",
                       "inclusion_respeto"],
    },
    "sostenibilidad_sentido": {
        "name": "Sostenibilidad y sentido",
        "dimensions": ["organizacion_sostenible", "sentido_alineamiento"],
    },
}


def _indices(dimensions: list[dict]) -> list[dict]:
    by_code = {d["code"]: d for d in dimensions}
    out = []
    for key, spec in INDEX_DEFINITIONS.items():
        parts = [by_code[c] for c in spec["dimensions"] if c in by_code and by_code[c]["score"] is not None]
        if not parts:
            continue
        out.append({
            "key": key,
            "name": spec["name"],
            "score": round(sum(p["score"] for p in parts) / len(parts), 1),
            "dimensions": [p["code"] for p in parts],
            "n_dimensions": len(parts),
            "is_hypothesis": True,
            "note": ("Agrupación propuesta, pendiente de validación psicométrica. "
                     "No debe leerse como un constructo validado."),
        })
    return out
