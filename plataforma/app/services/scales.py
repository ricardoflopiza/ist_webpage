# -*- coding: utf-8 -*-
"""Catálogo de escalas (§7).

Cada escala declara sus anclas y qué valores cuentan como favorable / neutral /
desfavorable. El corte no se hardcodea en el cálculo: viene de aquí, porque una
escala de 0 a 10 (recomendación) no se corta igual que una de 5 puntos.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scale:
    key: str
    name: str
    min_value: int
    max_value: int
    labels: tuple[str, ...]
    favorable: tuple[int, ...]
    neutral: tuple[int, ...]
    unfavorable: tuple[int, ...]

    def to_100(self, value: float) -> float:
        """Normaliza a 0-100. Para Likert 1-5: ((v-1)/4)*100."""
        span = self.max_value - self.min_value
        if span <= 0:
            return 0.0
        return (value - self.min_value) / span * 100.0

    def reverse(self, value: float) -> float:
        """Recodifica un ítem invertido ANTES de cualquier cálculo (§13)."""
        return self.max_value + self.min_value - value

    def band(self, value: float) -> str:
        v = int(round(value))
        if v in self.favorable:
            return "favorable"
        if v in self.neutral:
            return "neutral"
        return "desfavorable"


_L5 = lambda a, b, c, d, e: (a, b, c, d, e)  # noqa: E731

SCALES: dict[str, Scale] = {
    "acuerdo": Scale(
        "acuerdo", "Grado de acuerdo", 1, 5,
        _L5("Muy en desacuerdo", "En desacuerdo", "Ni de acuerdo ni en desacuerdo",
            "De acuerdo", "Muy de acuerdo"),
        favorable=(4, 5), neutral=(3,), unfavorable=(1, 2),
    ),
    "frecuencia": Scale(
        "frecuencia", "Frecuencia", 1, 5,
        _L5("Nunca", "Rara vez", "A veces", "Frecuentemente", "Siempre"),
        favorable=(4, 5), neutral=(3,), unfavorable=(1, 2),
    ),
    "satisfaccion": Scale(
        "satisfaccion", "Satisfacción", 1, 5,
        _L5("Muy insatisfecho/a", "Insatisfecho/a", "Ni satisfecho/a ni insatisfecho/a",
            "Satisfecho/a", "Muy satisfecho/a"),
        favorable=(4, 5), neutral=(3,), unfavorable=(1, 2),
    ),
    "calidad": Scale(
        "calidad", "Calidad", 1, 5,
        _L5("Muy mala", "Mala", "Regular", "Buena", "Muy buena"),
        favorable=(4, 5), neutral=(3,), unfavorable=(1, 2),
    ),
    "importancia": Scale(
        "importancia", "Importancia", 1, 5,
        _L5("Nada importante", "Poco importante", "Medianamente importante",
            "Importante", "Muy importante"),
        favorable=(4, 5), neutral=(3,), unfavorable=(1, 2),
    ),
    "esfuerzo": Scale(
        "esfuerzo", "Esfuerzo percibido", 1, 5,
        _L5("Muy alto", "Alto", "Moderado", "Bajo", "Muy bajo"),
        favorable=(4, 5), neutral=(3,), unfavorable=(1, 2),
    ),
    "recomendacion": Scale(
        "recomendacion", "Recomendación (0 a 10)", 0, 10,
        tuple(str(i) for i in range(11)),
        favorable=(9, 10), neutral=(7, 8), unfavorable=(0, 1, 2, 3, 4, 5, 6),
    ),
    "si_no": Scale(
        "si_no", "Sí / No", 0, 1, ("No", "Sí"),
        favorable=(1,), neutral=(), unfavorable=(0,),
    ),
}

DEFAULT_SCALE = "acuerdo"


def get_scale(key: str | None) -> Scale:
    return SCALES.get(key or DEFAULT_SCALE, SCALES[DEFAULT_SCALE])
