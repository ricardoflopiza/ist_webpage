# -*- coding: utf-8 -*-
"""Catálogo inicial de servicios y paquetes (§21).

Los precios quedan **administrables**: se cargan en CLP o como "Cotizar"
(`price_clp = None`). No se fija ningún precio definitivo desde el código.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ConsultingService

PACKAGES = [
    {
        "code": "diagnostico_esencial", "family": "paquete", "name": "Diagnóstico Esencial",
        "summary": "Medición de clima con instrumento estándar, dashboard e informe automático.",
        "includes": ["Encuesta estándar de clima", "Dashboard de resultados",
                     "Informe ejecutivo automático", "Una sesión de devolución"],
        "price_clp": None, "price_note": "Según tamaño de la organización",
    },
    {
        "code": "diagnostico_estrategico", "family": "paquete", "name": "Diagnóstico Estratégico",
        "summary": "Diagnóstico adaptado, análisis de impulsores y plan de acción facilitado.",
        "includes": ["Entrevistas iniciales", "Adaptación del instrumento",
                     "Análisis de impulsores", "Taller de priorización",
                     "Plan de acción con responsables e indicadores"],
        "price_clp": None, "price_note": "Cotizar",
    },
    {
        "code": "gestion_continua", "family": "paquete", "name": "Gestión Continua",
        "summary": "Ciclo anual con pulsos trimestrales y acompañamiento a líderes.",
        "includes": ["Diagnóstico anual", "Pulsos trimestrales", "Seguimiento de compromisos",
                     "Benchmark histórico propio", "Acompañamiento a jefaturas"],
        "price_clp": None, "price_note": "Plan anual",
    },
    {
        "code": "enterprise", "family": "paquete", "name": "Enterprise",
        "summary": "Múltiples empresas, integraciones y roles avanzados.",
        "includes": ["Varias organizaciones bajo un mismo holding", "SSO", "API",
                     "Integraciones con sistemas de RR. HH.", "Roles avanzados",
                     "Personalización", "Soporte especializado", "Benchmarks particulares"],
        "price_clp": None, "price_note": "Cotizar",
    },
]

SERVICES = [
    ("diseno_instrumentos", "Diseño y validación de instrumentos",
     "Construcción de encuestas a medida y revisión psicométrica de las existentes."),
    ("taller_interpretacion", "Talleres de interpretación de resultados",
     "Sesión de trabajo para leer los resultados con criterio metodológico y evitar conclusiones apresuradas."),
    ("devolucion_equipos", "Devolución a equipos",
     "Conversaciones estructuradas equipo por equipo, respetando el umbral de confidencialidad."),
    ("desarrollo_liderazgos", "Desarrollo de liderazgos",
     "Programa de fortalecimiento de prácticas de jefatura a partir de los resultados."),
    ("facilitacion_planes", "Facilitación de planes de acción",
     "Diseño de compromisos con responsables, indicadores y plazos verificables."),
    ("gestion_cambio", "Gestión del cambio",
     "Acompañamiento en procesos de transformación organizacional."),
    ("seguridad_psicologica", "Evaluación de seguridad psicológica",
     "Medición específica de riesgo interpersonal en equipos."),
    ("seguimiento_trimestral", "Seguimiento trimestral",
     "Revisión periódica del avance de los compromisos con la contraparte."),
    ("encuestas_pulso", "Encuestas pulso",
     "Mediciones breves para verificar avances entre diagnósticos."),
    ("experiencia_trabajador", "Estudios de experiencia del trabajador",
     "Análisis del ciclo laboral completo y sus momentos críticos."),
    ("evaluacion_transformacion", "Evaluación de procesos de transformación",
     "Medición antes, durante y después de un cambio organizacional."),
    ("convivencia_inclusion", "Análisis de convivencia, colaboración e inclusión",
     "Diagnóstico específico de trato, equidad y confianza en los canales internos."),
    ("benchmarks_sectoriales", "Construcción de benchmarks sectoriales",
     "Referencias comparativas por sector, tamaño y modalidad, siempre anonimizadas."),
]


def seed_services(db: Session) -> None:
    existing = {
        s.code for s in db.execute(
            select(ConsultingService).execution_options(include_all=True)
        ).scalars()
    }
    order = 0
    for p in PACKAGES:
        if p["code"] not in existing:
            db.add(ConsultingService(organization_id=None, sort_order=order, **p))
        order += 1
    for code, name, summary in SERVICES:
        if code not in existing:
            db.add(ConsultingService(
                organization_id=None, code=code, name=name, summary=summary,
                family="servicio", price_clp=None, price_note="Cotizar", sort_order=order,
            ))
        order += 1
    db.commit()
