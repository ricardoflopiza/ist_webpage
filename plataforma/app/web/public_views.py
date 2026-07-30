# -*- coding: utf-8 -*-
"""Página pública comercial (§4)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import ConsultingService, Lead
from ..security.deps import client_ip
from ..security.sessions import is_locked, record_fail
from ..templating import templates

router = APIRouter(tags=["público"], include_in_schema=False)

CAPACIDADES = [
    ("Encuestas configurables", "Instrumentos adaptables por módulo, dimensión y pregunta, con versiones inmutables al publicar."),
    ("Diagnósticos multicliente", "Cada organización es un espacio separado, con su propia estructura, nómina y resultados."),
    ("Segmentación segura", "Filtros por sede, área, equipo, antigüedad o modalidad, siempre sujetos al umbral de confidencialidad."),
    ("Dashboards ejecutivos", "Una lectura para gerencia, otra para RR. HH. y otra para cada equipo."),
    ("Análisis de impulsores", "Qué factores se asocian con el compromiso, la permanencia y la recomendación."),
    ("Comentarios cualitativos", "Lectura de comentarios abiertos con protocolo para menciones sensibles."),
    ("Planes de acción", "Compromisos con responsable, indicador, plazo y evidencia verificable."),
    ("Encuestas pulso", "Mediciones breves para saber si las acciones se están notando."),
    ("Benchmarks", "Referencias por sector, tamaño y modalidad, construidas con datos anonimizados."),
    ("Reportes por audiencia", "Ejecutivo, organizacional y de equipo, respetando permisos y anonimato."),
]

PROBLEMAS = [
    ("Encuestas que no llevan a nada", "Se aplica el instrumento, se presenta un informe y seis meses después nadie recuerda qué se decidió."),
    ("Conceptos mezclados", "Satisfacción, clima, compromiso y riesgo psicosocial no son lo mismo y no se miden ni se gestionan igual."),
    ("Informes sin prioridades", "Ochenta páginas de gráficos no dicen por dónde partir."),
    ("Credibilidad que se erosiona", "Preguntar sin actuar enseña a las personas que responder no sirve."),
    ("Confidencialidad mal resuelta", "Cruces que dejan celdas de tres personas expuestas ante su jefatura."),
    ("Equipos pequeños comparados a la ligera", "Un equipo de cinco personas no se compara con uno de doscientos."),
    ("Promedios que esconden", "Un 50 % muy de acuerdo y un 50 % muy en desacuerdo promedian igual que un consenso tibio."),
]

CICLO = [
    ("Escuchar", "Diseño y aplicación del instrumento con reglas de confidencialidad explícitas."),
    ("Analizar", "Cálculo en el servidor, comparación con la medición anterior y con el benchmark."),
    ("Priorizar", "Matriz de prioridad ajustada con criterio consultivo, no sólo estadístico."),
    ("Actuar", "Planes con responsable, indicador y plazo, no listas de buenas intenciones."),
    ("Hacer seguimiento", "Pulsos que verifican si los compromisos se están notando."),
]

METODOLOGIA = [
    ("Encuadre", "Definición de objetivos, alcance, gobernanza del proceso y reglas de confidencialidad."),
    ("Adaptación", "Ajuste del instrumento al lenguaje y realidad de la organización, sin perder comparabilidad."),
    ("Comunicación", "Plan de comunicación interna: qué se pregunta, para qué y qué pasará con las respuestas."),
    ("Aplicación", "Levantamiento con seguimiento de participación por unidad."),
    ("Análisis", "Resultados por dimensión, segmentos, impulsores y comentarios."),
    ("Devolución", "Sesiones diferenciadas para dirección, RR. HH. y equipos."),
    ("Plan de acción", "Compromisos priorizados con responsables e indicadores."),
    ("Seguimiento", "Pulsos y revisión periódica del avance."),
]

ORGANIZACIONES = [
    ("Empresas privadas", "Diagnóstico de clima con foco en compromiso, permanencia y desempeño."),
    ("Instituciones públicas", "Medición compatible con procesos internos y reportes institucionales."),
    ("Municipalidades", "Múltiples direcciones y departamentos, con estructuras heterogéneas."),
    ("Fundaciones y ONG", "Equipos pequeños: instrumentos y umbrales adaptados a esa escala."),
    ("Instituciones educativas", "Estamentos diferenciados: docentes, administrativos y directivos."),
    ("Empresas industriales", "Turnos, faenas y personal sin correo corporativo (acceso por código o QR)."),
    ("Retail", "Alta rotación y muchas sucursales pequeñas."),
    ("Salud", "Turnos críticos, carga emocional y equipos multidisciplinarios."),
    ("Tecnología", "Trabajo remoto, alta movilidad y expectativas de desarrollo."),
    ("Organizaciones distribuidas", "Comparación entre sedes cuidando el tamaño de cada una."),
    ("Trabajo remoto o híbrido", "Módulo específico de modalidad, desconexión y equidad."),
]

CONFIDENCIALIDAD = [
    ("Nómina separada de las respuestas", "No existe en la base ningún vínculo entre una persona y lo que respondió."),
    ("Umbral mínimo configurable", "Por defecto, 7 respuestas para mostrar cualquier resultado."),
    ("Grupos pequeños ocultos", "Incluye supresión complementaria: si un grupo se deduciría por diferencia, también se oculta."),
    ("Control de accesos", "Permisos granulares por rol, aplicados en la API y no sólo en la interfaz."),
    ("Auditoría", "Queda registro de quién vio qué resultado, qué exportó y qué se le denegó."),
    ("Comentarios con protocolo", "Datos personales ocultos y revisión humana para menciones sensibles."),
]


@router.get("/")
def home(request: Request, db: Session = Depends(get_session)):
    services = db.execute(
        select(ConsultingService).where(
            ConsultingService.is_active.is_(True), ConsultingService.organization_id.is_(None)
        ).order_by(ConsultingService.sort_order).execution_options(include_all=True)
    ).scalars().all()
    return templates.TemplateResponse("public/home.html", {
        "request": request,
        "paquetes": [s for s in services if s.family == "paquete"],
        "servicios": [s for s in services if s.family != "paquete"],
        "capacidades": CAPACIDADES, "problemas": PROBLEMAS, "ciclo": CICLO,
        "metodologia": METODOLOGIA, "organizaciones": ORGANIZACIONES,
        "confidencialidad": CONFIDENCIALIDAD,
        "enviado": request.query_params.get("enviado") == "1",
    })


@router.post("/contacto")
def contacto(
    request: Request,
    nombre: str = Form(...), organizacion: str = Form(""), cargo: str = Form(""),
    correo: str = Form(...), tamano: str = Form(""), necesidad: str = Form(""),
    mensaje: str = Form(""), db: Session = Depends(get_session),
):
    from fastapi.responses import RedirectResponse

    ip = client_ip(request)
    if is_locked(f"lead:{ip}"):
        return RedirectResponse("/?enviado=espera#contacto", status_code=303)
    record_fail(f"lead:{ip}")
    db.add(Lead(
        name=nombre.strip(), organization=organizacion.strip() or None,
        role=cargo.strip() or None, email=correo.strip().lower(),
        size_bucket=tamano or None, need=necesidad or None,
        message=mensaje.strip() or None, source_ip=ip,
    ))
    db.commit()
    return RedirectResponse("/?enviado=1#contacto", status_code=303)
