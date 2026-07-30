# -*- coding: utf-8 -*-
"""Motor de plantillas y filtros compartidos por todas las vistas."""
from __future__ import annotations

import datetime as dt
import pathlib

from fastapi.templating import Jinja2Templates

ROOT = pathlib.Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))


def clp(value) -> str:
    if value in (None, ""):
        return "Cotizar"
    return "$" + f"{int(value):,}".replace(",", ".")


def pct(value, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}%".replace(".", ",")


def num(value, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}".replace(".", ",")


def fecha(value) -> str:
    if not value:
        return "—"
    if isinstance(value, dt.datetime):
        return value.strftime("%d-%m-%Y %H:%M")
    return value.strftime("%d-%m-%Y")


def band_class(score) -> str:
    """Clase CSS por tramo. El significado de cada tramo se explica siempre en la
    interfaz: un semáforo sin criterio declarado induce a error (§12)."""
    if score is None:
        return "band-na"
    if score >= 75:
        return "band-alto"
    if score >= 60:
        return "band-medio"
    if score >= 45:
        return "band-bajo"
    return "band-critico"


templates.env.filters.update(
    clp=clp, pct=pct, num=num, fecha=fecha, band_class=band_class,
)
templates.env.globals.update(
    marca={"nombre": "istendencia", "producto": "Clima", "anio": dt.date.today().year},
)
