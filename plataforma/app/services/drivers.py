# -*- coding: utf-8 -*-
"""Análisis de impulsores (§15).

Qué hace: estima **asociación** entre las dimensiones de clima y una variable de
resultado (compromiso, satisfacción, recomendación, permanencia, calidad del
trabajo), con correlaciones de Pearson y una regresión lineal múltiple con
coeficientes estandarizados (beta).

Qué NO hace, y por qué el vocabulario importa: no establece causalidad. Un dato
transversal, autoinformado y con variables omitidas no permite afirmar que
mejorar una dimensión *produzca* una mejora del resultado. Todos los textos que
salen de aquí usan "factor asociado", "posible palanca" o "prioridad sugerida".

Advertencias automáticas: muestra insuficiente (regla práctica de 10 casos por
predictor), multicolinealidad alta (VIF > 5) y modelos con R² muy bajo.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

MIN_CASES_PER_PREDICTOR = 10
MIN_CASES_ABSOLUTE = 30
VIF_WARNING = 5.0
VIF_SEVERE = 10.0


@dataclass
class DriverResult:
    outcome_code: str
    outcome_name: str
    n: int
    r2: float | None = None
    adj_r2: float | None = None
    drivers: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reliable: bool = True
    method: str = "correlacion + regresion_multiple_ols"

    def to_dict(self) -> dict:
        return {
            "outcome_code": self.outcome_code,
            "outcome_name": self.outcome_name,
            "n": self.n,
            "r2": self.r2,
            "adj_r2": self.adj_r2,
            "drivers": self.drivers,
            "warnings": self.warnings,
            "reliable": self.reliable,
            "method": self.method,
            "disclaimer": (
                "Relaciones estadísticas de asociación, no de causalidad. "
                "Los datos son transversales y autoinformados: el orden sugerido "
                "es un insumo para la conversación consultiva, no una garantía "
                "de que intervenir esa dimensión mueva el resultado."
            ),
        }


def _build_matrix(
    person_scores: dict[str, dict[str, float]],
    predictors: list[str],
    outcome: str,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Casos completos: sólo respuestas con puntaje en todos los predictores y el
    resultado. No se imputa nada — imputar en n pequeños inventa señal."""
    outcome_map = person_scores.get(outcome, {})
    ids = [
        rid for rid in outcome_map
        if all(rid in person_scores.get(p, {}) for p in predictors)
    ]
    X = np.array([[person_scores[p][rid] for p in predictors] for rid in ids], dtype=float)
    y = np.array([outcome_map[rid] for rid in ids], dtype=float)
    return X, y, ids


def pearson(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def variance_inflation(X: np.ndarray) -> list[float]:
    """VIF por predictor: cuánto se infla su varianza por colinealidad."""
    vifs = []
    n_cols = X.shape[1]
    for j in range(n_cols):
        others = np.delete(X, j, axis=1)
        if others.shape[1] == 0:
            vifs.append(1.0)
            continue
        A = np.column_stack([np.ones(len(others)), others])
        try:
            # `rcond` explícito: con predictores casi colineales la solución de
            # norma mínima evita coeficientes desbordados (y los avisos de numpy).
            with np.errstate(all="ignore"):
                coef, *_ = np.linalg.lstsq(A, X[:, j], rcond=1e-10)
                pred = A @ coef
            ss_res = float(np.sum((X[:, j] - pred) ** 2))
            ss_tot = float(np.sum((X[:, j] - np.mean(X[:, j])) ** 2))
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
            if not np.isfinite(r2):
                vifs.append(999.0)
            else:
                vifs.append(float(1 / (1 - r2)) if r2 < 0.999 else 999.0)
        except np.linalg.LinAlgError:
            vifs.append(999.0)
    return vifs


def analyze_outcome(
    person_scores: dict[str, dict[str, float]],
    predictors: list[str],
    outcome_code: str,
    outcome_name: str,
    labels: dict[str, str] | None = None,
) -> DriverResult:
    labels = labels or {}
    X, y, ids = _build_matrix(person_scores, predictors, outcome_code)
    n = len(y)
    res = DriverResult(outcome_code=outcome_code, outcome_name=outcome_name, n=n)

    if n < MIN_CASES_ABSOLUTE:
        res.reliable = False
        res.warnings.append(
            f"Sólo {n} casos completos. Bajo {MIN_CASES_ABSOLUTE} no se estima el modelo: "
            "el resultado sería inestable. Se muestran únicamente correlaciones simples."
        )
    if n < len(predictors) * MIN_CASES_PER_PREDICTOR:
        res.reliable = False
        res.warnings.append(
            f"{n} casos para {len(predictors)} dimensiones. La regla práctica pide al menos "
            f"{len(predictors) * MIN_CASES_PER_PREDICTOR}. Interpretar con cautela."
        )

    # Correlaciones simples: siempre se pueden reportar (con su n).
    correlations = {}
    for j, code in enumerate(predictors):
        correlations[code] = pearson(X[:, j], y) if n >= 3 else None

    betas: dict[str, float | None] = {c: None for c in predictors}
    vifs: dict[str, float | None] = {c: None for c in predictors}

    if n >= MIN_CASES_ABSOLUTE and X.shape[1] > 0 and np.std(y) > 0:
        # Estandarizar para que los coeficientes sean comparables entre sí.
        sx = X.std(axis=0)
        sx_safe = np.where(sx == 0, 1.0, sx)
        Z = (X - X.mean(axis=0)) / sx_safe
        zy = (y - y.mean()) / (y.std() or 1.0)
        A = np.column_stack([np.ones(len(Z)), Z])
        with np.errstate(all="ignore"):
            coef, *_ = np.linalg.lstsq(A, zy, rcond=1e-10)
            pred = A @ coef
        coef = np.nan_to_num(coef, nan=0.0, posinf=0.0, neginf=0.0)
        ss_res = float(np.sum((zy - pred) ** 2))
        ss_tot = float(np.sum((zy - zy.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None
        if r2 is not None and not np.isfinite(r2):
            r2 = None
        res.r2 = round(r2, 3) if r2 is not None else None
        if r2 is not None and n - X.shape[1] - 1 > 0:
            adj = 1 - (1 - r2) * (n - 1) / (n - X.shape[1] - 1)
            res.adj_r2 = round(adj, 3)
        for j, code in enumerate(predictors):
            betas[code] = float(coef[j + 1])
        for code, v in zip(predictors, variance_inflation(X), strict=False):
            vifs[code] = round(v, 2)
        high = [labels.get(c, c) for c, v in vifs.items() if v and v >= VIF_SEVERE]
        med = [labels.get(c, c) for c, v in vifs.items()
               if v and VIF_WARNING <= v < VIF_SEVERE]
        if high:
            res.warnings.append(
                "Multicolinealidad severa (VIF ≥ 10) en: " + ", ".join(high) +
                ". Esas dimensiones miden algo muy parecido; sus coeficientes se reparten "
                "de forma arbitraria y no deben leerse por separado."
            )
        elif med:
            res.warnings.append(
                "Colinealidad moderada (VIF ≥ 5) en: " + ", ".join(med) +
                ". Conviene priorizar mirando también la correlación simple."
            )
        if res.r2 is not None and res.r2 < 0.2:
            res.warnings.append(
                f"El modelo explica poco de la variación del resultado (R²={res.r2}). "
                "Probablemente pesan factores no medidos por esta encuesta."
            )

    for code in predictors:
        r = correlations.get(code)
        beta = betas.get(code)
        res.drivers.append({
            "code": code,
            "name": labels.get(code, code),
            "r": round(r, 3) if r is not None else None,
            "beta": round(beta, 3) if beta is not None else None,
            "vif": vifs.get(code),
            "strength": _strength_label(beta if beta is not None else r),
            "n": n,
        })
    res.drivers.sort(
        key=lambda d: abs(d["beta"] if d["beta"] is not None else (d["r"] or 0)), reverse=True
    )
    return res


def _strength_label(value: float | None) -> str:
    """Lenguaje deliberadamente no causal (§15)."""
    if value is None:
        return "sin estimación"
    a = abs(value)
    if a >= 0.35:
        return "factor fuertemente asociado"
    if a >= 0.20:
        return "factor asociado"
    if a >= 0.10:
        return "asociación débil"
    return "sin asociación relevante"


def analyze(
    person_scores: dict[str, dict[str, float]],
    climate_codes: list[str],
    outcomes: list[tuple[str, str]],
    labels: dict[str, str] | None = None,
) -> list[dict]:
    """Corre el análisis para cada variable de resultado disponible."""
    out = []
    for code, name in outcomes:
        if code not in person_scores or not person_scores[code]:
            continue
        preds = [c for c in climate_codes if person_scores.get(c)]
        if not preds:
            continue
        out.append(analyze_outcome(person_scores, preds, code, name, labels).to_dict())
    return out


# ------------------------------------------------------------------ matriz de prioridad (§16)
def priority_matrix(
    dimensions: list[dict], driver_result: dict | None, *, score_pivot: float = 65.0
) -> dict:
    """Cruza nivel actual (eje X) con asociación al resultado (eje Y).

    El cuadrante es una **sugerencia**. La priorización final la ajusta el
    consultor con criterios que ningún modelo captura: gravedad ética, riesgo
    legal, seguridad, factibilidad, costo, urgencia y contexto. Por eso las
    alertas de acoso, violencia o discriminación entran con prioridad crítica
    aunque su correlación con el compromiso sea baja (§16).
    """
    assoc: dict[str, float] = {}
    if driver_result:
        for d in driver_result.get("drivers", []):
            v = d["beta"] if d.get("beta") is not None else d.get("r")
            if v is not None:
                assoc[d["code"]] = abs(v)
    pivot_y = (sum(assoc.values()) / len(assoc)) if assoc else 0.2

    points = []
    for d in dimensions:
        if d.get("is_outcome") or d.get("score") is None:
            continue
        a = assoc.get(d["code"])
        if a is None:
            quadrant = "sin_datos"
        elif d["score"] < score_pivot and a >= pivot_y:
            quadrant = "prioridad_critica"
        elif d["score"] >= score_pivot and a >= pivot_y:
            quadrant = "fortaleza_estrategica"
        elif d["score"] < score_pivot and a < pivot_y:
            quadrant = "mejora_secundaria"
        else:
            quadrant = "mantener"
        points.append({
            "code": d["code"], "name": d["name"],
            "score": d["score"], "association": round(a, 3) if a is not None else None,
            "quadrant": quadrant, "n": d.get("n"),
        })
    order = {"prioridad_critica": 0, "fortaleza_estrategica": 1,
             "mejora_secundaria": 2, "mantener": 3, "sin_datos": 4}
    points.sort(key=lambda p: (order[p["quadrant"]], p["score"] if p["score"] is not None else 999))
    return {
        "pivot_x": score_pivot,
        "pivot_y": round(pivot_y, 3),
        "points": points,
        "quadrants": {
            "prioridad_critica": "Resultado bajo y asociación alta: prioridad sugerida.",
            "fortaleza_estrategica": "Resultado alto y asociación alta: fortaleza a sostener.",
            "mejora_secundaria": "Resultado bajo y asociación baja: mejora secundaria.",
            "mantener": "Resultado alto y asociación baja: mantener.",
        },
        "note": ("Ubicación sugerida por el modelo. Debe ajustarse con criterios de "
                 "gravedad ética, riesgo legal, seguridad, factibilidad y urgencia."),
    }
