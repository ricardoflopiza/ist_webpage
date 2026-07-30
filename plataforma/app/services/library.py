# -*- coding: utf-8 -*-
"""Biblioteca maestra de instrumentos (§8).

Definición declarativa: cada plantilla es un diccionario que `build_library()`
materializa como plantilla de plataforma (organization_id NULL) con su versión 1
publicada. Adaptar una plantilla para un cliente crea una copia con
`derived_from_id`, así la trazabilidad al original nunca se pierde.

Nota metodológica: estos instrumentos miden clima y experiencia organizacional.
Los módulos de condiciones psicosociales son complementarios y **no sustituyen**
los instrumentos regulatorios oficiales (en Chile, CEAL-SM/SUSESO), que tienen su
propio protocolo de aplicación y reporte.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    QuestionBankItem,
    SurveyDimension,
    SurveyModule,
    SurveyQuestion,
    SurveyTemplate,
    SurveyTemplateVersion,
)
from ..models.survey import Q_LIKERT, Q_SINGLE, Q_TEXT, VERSION_PUBLISHED

A = "acuerdo"
F = "frecuencia"
S = "satisfaccion"
R = "recomendacion"


def _q(code, text, scale=A, reverse=False, qtype=Q_LIKERT, options=None, required=True, allow_na=False):
    return {"code": code, "text": text, "scale": scale, "reverse": reverse,
            "qtype": qtype, "options": options, "required": required, "allow_na": allow_na}


def _open(code, text):
    return _q(code, text, scale=None, qtype=Q_TEXT, required=False)


# ==================================================================== CLIMA INTEGRAL
CLIMA_DIMENSIONS = [
    ("liderazgo", "Liderazgo", "gestion_organizacional", [
        _q("lid_1", "Mi jefatura directa me entrega orientaciones claras sobre lo que se espera de mi trabajo."),
        _q("lid_2", "Mi jefatura directa está disponible cuando necesito apoyo."),
        _q("lid_3", "Mi jefatura directa reconoce el trabajo bien hecho.", F),
        _q("lid_4", "Mi jefatura directa toma decisiones de manera coherente con lo que dice."),
    ]),
    ("comunicacion", "Comunicación", "gestion_organizacional", [
        _q("com_1", "Recibo a tiempo la información que necesito para hacer mi trabajo."),
        _q("com_2", "La organización comunica con claridad sus decisiones importantes."),
        _q("com_3", "Me entero de las cosas relevantes por canales formales y no por rumores."),
    ]),
    ("claridad_coordinacion", "Claridad y coordinación", "gestion_organizacional", [
        _q("cla_1", "Tengo claro cuáles son mis responsabilidades."),
        _q("cla_2", "Las áreas con las que trabajo coordinan bien entre sí."),
        _q("cla_3", "Con frecuencia recibo instrucciones contradictorias.", F, reverse=True),
    ]),
    ("autonomia_participacion", "Autonomía y participación", "gestion_organizacional", [
        _q("aut_1", "Puedo decidir cómo organizar mi trabajo diario."),
        _q("aut_2", "Se me consulta en las decisiones que afectan mi trabajo.", F),
        _q("aut_3", "Mis propuestas de mejora son tomadas en cuenta.", F),
    ]),
    ("reconocimiento", "Reconocimiento", "gestion_organizacional", [
        _q("rec_1", "Mi trabajo es valorado en la organización."),
        _q("rec_2", "Cuando hago un buen trabajo, alguien lo nota.", F),
        _q("rec_3", "El reconocimiento se distribuye de manera justa entre las personas."),
    ]),
    ("desarrollo", "Desarrollo", "gestion_organizacional", [
        _q("des_1", "Tengo oportunidades reales de aprender y crecer aquí."),
        _q("des_2", "La organización invierte en la formación de las personas."),
        _q("des_3", "Sé qué necesito para avanzar en mi trayectoria laboral."),
    ]),
    ("justicia_confianza", "Justicia y confianza", "confianza_relaciones", [
        _q("jus_1", "Las decisiones sobre las personas se toman con criterios claros."),
        _q("jus_2", "Confío en lo que comunica la dirección de la organización."),
        _q("jus_3", "Aquí se aplican las mismas reglas para todas las personas."),
    ]),
    ("colaboracion", "Colaboración", "confianza_relaciones", [
        _q("col_1", "En mi equipo nos ayudamos cuando alguien lo necesita.", F),
        _q("col_2", "Existe buena disposición a colaborar entre áreas."),
        _q("col_3", "Los conflictos de trabajo se resuelven de manera constructiva."),
    ]),
    ("seguridad_psicologica", "Seguridad psicológica", "confianza_relaciones", [
        _q("seg_1", "En mi equipo puedo plantear un problema difícil sin temor."),
        _q("seg_2", "Si cometo un error, puedo reconocerlo sin que se use en mi contra."),
        _q("seg_3", "Puedo estar en desacuerdo con mi jefatura sin consecuencias negativas."),
        _q("seg_4", "Pedir ayuda aquí se ve como algo normal."),
    ]),
    ("inclusion_respeto", "Inclusión y respeto", "confianza_relaciones", [
        _q("inc_1", "Recibo un trato respetuoso en mi trabajo cotidiano.", F),
        _q("inc_2", "Personas de distintos perfiles tienen las mismas oportunidades aquí."),
        _q("inc_3", "Puedo ser yo mismo/a en mi lugar de trabajo."),
        _q("inc_4", "He presenciado situaciones de trato discriminatorio.", F, reverse=True),
    ]),
    ("organizacion_sostenible", "Organización sostenible del trabajo", "sostenibilidad_sentido", [
        _q("sos_1", "La carga de trabajo que tengo es manejable."),
        _q("sos_2", "Puedo desconectarme del trabajo fuera de mi jornada.", F),
        _q("sos_3", "Cuento con los recursos necesarios para hacer bien mi trabajo."),
        _q("sos_4", "Termino la jornada agotado/a de forma habitual.", F, reverse=True),
    ]),
    ("sentido_alineamiento", "Sentido y alineamiento", "sostenibilidad_sentido", [
        _q("sen_1", "Entiendo cómo mi trabajo aporta a los objetivos de la organización."),
        _q("sen_2", "El trabajo que hago tiene sentido para mí."),
        _q("sen_3", "Me identifico con los valores que declara la organización."),
    ]),
]

CLIMA_OUTCOMES = [
    ("compromiso", "Compromiso", [
        _q("cmp_1", "Estoy dispuesto/a a esforzarme más allá de lo mínimo por esta organización."),
        _q("cmp_2", "Me siento parte de esta organización."),
    ]),
    ("permanencia", "Intención de permanencia", [
        _q("per_1", "Me veo trabajando aquí dentro de dos años."),
        _q("per_2", "En los últimos meses he pensado seriamente en irme.", F, reverse=True),
    ]),
    ("satisfaccion", "Satisfacción general", [
        _q("sat_1", "En general, ¿qué tan satisfecho/a estás trabajando aquí?", S),
    ]),
    ("recomendacion", "Recomendación", [
        _q("nps_1", "¿Qué tan probable es que recomiendes esta organización como lugar para trabajar? (0 a 10)", R),
    ]),
    ("calidad_trabajo", "Capacidad de hacer un trabajo de calidad", [
        _q("cal_1", "Las condiciones en que trabajo me permiten hacer un trabajo de calidad."),
    ]),
]

CLIMA_OPEN = [
    _open("ab_1", "¿Qué es lo que más valoras de trabajar aquí?"),
    _open("ab_2", "¿Qué cambiarías para mejorar tu experiencia de trabajo?"),
    _open("ab_3", "¿Hay algo más que quieras comentar?"),
]


def _clima_template() -> dict:
    return {
        "code": "clima_integral",
        "name": "Encuesta integral de clima laboral",
        "kind": "clima",
        "estimated_minutes": 12,
        "purpose": (
            "Diagnóstico completo de clima y experiencia organizacional: mide doce "
            "dimensiones de clima y cinco variables de resultado que permiten el "
            "análisis de impulsores."
        ),
        "modules": [
            {"code": "clima", "name": "Clima organizacional",
             "dimensions": [
                 {"code": c, "name": n, "index_key": ik, "questions": qs}
                 for c, n, ik, qs in CLIMA_DIMENSIONS
             ]},
            {"code": "resultados", "name": "Variables de resultado",
             "description": ("Se analizan por separado de las dimensiones de clima: "
                             "son el criterio del análisis de impulsores, no una dimensión más."),
             "dimensions": [
                 {"code": c, "name": n, "is_outcome": True, "questions": qs}
                 for c, n, qs in CLIMA_OUTCOMES
             ]},
            {"code": "abiertas", "name": "Comentarios abiertos",
             "dimensions": [{"code": "comentarios", "name": "Comentarios", "questions": CLIMA_OPEN}]},
        ],
    }


# ==================================================================== OTRAS PLANTILLAS
def _simple(code, name, kind, purpose, minutes, dims, with_open=True) -> dict:
    modules = [{"code": "principal", "name": name,
                "dimensions": [{"code": c, "name": n, "questions": qs} for c, n, qs in dims]}]
    if with_open:
        modules.append({
            "code": "abiertas", "name": "Comentarios abiertos",
            "dimensions": [{"code": "comentarios", "name": "Comentarios", "questions": [
                _open(f"{code}_ab1", "¿Qué está funcionando bien?"),
                _open(f"{code}_ab2", "¿Qué debería mejorar?"),
            ]}],
        })
    return {"code": code, "name": name, "kind": kind, "purpose": purpose,
            "estimated_minutes": minutes, "modules": modules}


TEMPLATES: list[dict] = [
    _clima_template(),
    _simple("pulso_seguimiento", "Encuesta pulso de seguimiento", "pulso",
            "Medición breve (6 a 12 preguntas) para seguir compromisos y avances entre diagnósticos.",
            3, [
                ("seguimiento", "Seguimiento de compromisos", [
                    _q("pul_1", "He observado avances concretos después de la última encuesta."),
                    _q("pul_2", "Las acciones comprometidas han sido comunicadas."),
                    _q("pul_3", "La coordinación en mi área ha mejorado."),
                    _q("pul_4", "La carga de trabajo se ha vuelto más manejable."),
                    _q("pul_5", "Confío en que la organización continuará este proceso."),
                    _q("pul_6", "Mi jefatura ha involucrado al equipo en las mejoras.", F),
                ]),
            ]),
    _simple("liderazgo_360", "Evaluación de liderazgo", "liderazgo",
            "Percepción del equipo sobre las prácticas de su jefatura directa. Resultado siempre grupal.",
            8, [
                ("claridad", "Claridad", [
                    _q("lid_cla_1", "Mi jefatura define con claridad las prioridades del equipo."),
                    _q("lid_cla_2", "Sé qué se espera de mí en cada período."),
                ]),
                ("apoyo", "Apoyo", [
                    _q("lid_apo_1", "Mi jefatura me apoya cuando enfrento dificultades.", F),
                    _q("lid_apo_2", "Puedo contar con mi jefatura ante un problema personal que afecta mi trabajo."),
                ]),
                ("escucha", "Escucha", [
                    _q("lid_esc_1", "Mi jefatura escucha antes de decidir.", F),
                    _q("lid_esc_2", "Puedo plantearle desacuerdos con tranquilidad."),
                ]),
                ("retroalimentacion", "Retroalimentación", [
                    _q("lid_ret_1", "Recibo retroalimentación útil sobre mi desempeño.", F),
                    _q("lid_ret_2", "La retroalimentación que recibo es oportuna."),
                ]),
                ("justicia_lid", "Justicia", [
                    _q("lid_jus_1", "Mi jefatura trata a todo el equipo con los mismos criterios."),
                ]),
                ("conflictos", "Gestión de conflictos", [
                    _q("lid_con_1", "Mi jefatura aborda los conflictos en lugar de evitarlos.", F),
                ]),
                ("desarrollo_personas", "Desarrollo de personas", [
                    _q("lid_dev_1", "Mi jefatura se preocupa de mi desarrollo profesional."),
                ]),
                ("coherencia", "Coherencia", [
                    _q("lid_coh_1", "Lo que mi jefatura dice y lo que hace son coherentes."),
                ]),
                ("priorizacion", "Capacidad de priorización", [
                    _q("lid_pri_1", "Mi jefatura ayuda al equipo a priorizar cuando hay sobrecarga."),
                ]),
            ]),
    _simple("seguridad_psicologica", "Seguridad psicológica de equipos", "equipos",
            "Mide la percepción de riesgo interpersonal en el equipo: hablar, equivocarse, pedir ayuda y disentir.",
            5, [
                ("hablar", "Capacidad de hablar", [
                    _q("sp_hab_1", "En este equipo puedo plantear problemas y temas difíciles."),
                ]),
                ("errores", "Reconocimiento de errores", [
                    _q("sp_err_1", "En este equipo los errores se usan para aprender, no para castigar."),
                    _q("sp_err_2", "Reconocer un error aquí se paga caro.", A, reverse=True),
                ]),
                ("ayuda", "Solicitud de ayuda", [
                    _q("sp_ayu_1", "Es fácil pedir ayuda a las personas de este equipo."),
                ]),
                ("disenso", "Disenso", [
                    _q("sp_dis_1", "Se puede estar en desacuerdo abiertamente en este equipo."),
                ]),
                ("aprendizaje", "Aprendizaje", [
                    _q("sp_apr_1", "Este equipo dedica tiempo a revisar cómo mejorar su forma de trabajar.", F),
                ]),
                ("respeto", "Respeto interpersonal", [
                    _q("sp_res_1", "Las personas de este equipo se tratan con respeto.", F),
                ]),
            ]),
    _simple("trabajo_hibrido", "Trabajo remoto o híbrido", "modalidad",
            "Evalúa cómo funciona la modalidad de trabajo: coordinación, recursos, desconexión y equidad.",
            6, [
                ("comunicacion_h", "Comunicación", [
                    _q("hib_com_1", "La comunicación funciona bien en mi modalidad de trabajo."),
                ]),
                ("coordinacion_h", "Coordinación", [
                    _q("hib_coo_1", "Coordinamos bien el trabajo entre quienes están presentes y remotos."),
                ]),
                ("recursos_h", "Recursos", [
                    _q("hib_rec_1", "Cuento con las herramientas necesarias para trabajar en esta modalidad."),
                ]),
                ("autonomia_h", "Autonomía", [
                    _q("hib_aut_1", "Puedo organizar mi jornada con la flexibilidad que necesito."),
                ]),
                ("desconexion_h", "Desconexión", [
                    _q("hib_des_1", "Logro desconectarme al terminar mi jornada.", F),
                    _q("hib_des_2", "Recibo solicitudes de trabajo fuera de mi horario.", F, reverse=True),
                ]),
                ("pertenencia_h", "Pertenencia", [
                    _q("hib_per_1", "Me siento parte del equipo aunque no coincidamos presencialmente."),
                ]),
                ("acceso_info", "Acceso a información", [
                    _q("hib_inf_1", "Accedo a la misma información que quienes trabajan presencialmente."),
                ]),
                ("equidad_modalidad", "Equidad entre modalidades", [
                    _q("hib_equ_1", "Las oportunidades son las mismas para quienes trabajan presencial y remotamente."),
                ]),
            ]),
    _simple("gestion_cambio", "Gestión del cambio", "cambio",
            "Mide comprensión, confianza, preparación y adopción durante un proceso de transformación.",
            7, [
                ("comprension", "Comprensión del cambio", [
                    _q("cam_com_1", "Entiendo por qué se está haciendo este cambio."),
                ]),
                ("confianza_cambio", "Confianza", [
                    _q("cam_con_1", "Confío en cómo se está conduciendo este proceso."),
                ]),
                ("participacion_cambio", "Participación", [
                    _q("cam_par_1", "He tenido oportunidad de aportar durante el proceso.", F),
                ]),
                ("preparacion", "Preparación", [
                    _q("cam_pre_1", "Me siento preparado/a para trabajar con la nueva forma de hacer las cosas."),
                ]),
                ("capacidades", "Capacidades", [
                    _q("cam_cap_1", "He recibido la formación necesaria para este cambio."),
                ]),
                ("carga_transicion", "Carga de transición", [
                    _q("cam_car_1", "La carga de trabajo durante la transición es manejable."),
                ]),
                ("comunicacion_cambio", "Comunicación", [
                    _q("cam_cmn_1", "La información sobre el cambio llega a tiempo."),
                ]),
                ("adopcion", "Adopción", [
                    _q("cam_ado_1", "En mi equipo ya estamos trabajando con la nueva forma.", F),
                ]),
            ]),
    _simple("onboarding", "Experiencia de incorporación (onboarding)", "ciclo",
            "Experiencia de las personas durante sus primeros meses en la organización.",
            6, [
                ("claridad_rol", "Claridad del rol", [
                    _q("onb_rol_1", "Desde el inicio tuve claro qué se esperaba de mí."),
                ]),
                ("herramientas", "Acceso a herramientas", [
                    _q("onb_her_1", "Tuve a tiempo los accesos y herramientas para trabajar."),
                ]),
                ("integracion", "Integración", [
                    _q("onb_int_1", "Me sentí bien recibido/a por el equipo."),
                ]),
                ("acompanamiento", "Acompañamiento", [
                    _q("onb_aco_1", "Tuve a alguien a quien recurrir durante mis primeras semanas."),
                ]),
                ("formacion", "Formación", [
                    _q("onb_for_1", "La inducción me preparó para hacer mi trabajo."),
                ]),
                ("cultura", "Comprensión cultural", [
                    _q("onb_cul_1", "Entendí rápido cómo funcionan las cosas aquí."),
                ]),
            ]),
    _simple("salida", "Encuesta de salida", "ciclo",
            "Recoge motivos de desvinculación y experiencia final. Se analiza siempre agregada por período.",
            8, [
                ("motivo_salida", "Motivos de salida", [
                    _q("sal_mot_1", "¿Cuál es el motivo principal de tu salida?", None, qtype=Q_SINGLE,
                       options=["Nueva oportunidad laboral", "Remuneración", "Desarrollo profesional",
                                "Relación con la jefatura", "Carga de trabajo", "Clima del equipo",
                                "Motivos personales", "Término de contrato", "Otro"]),
                ]),
                ("liderazgo_salida", "Liderazgo", [
                    _q("sal_lid_1", "Mi jefatura directa contribuyó positivamente a mi experiencia."),
                ]),
                ("desarrollo_salida", "Desarrollo", [
                    _q("sal_des_1", "Tuve oportunidades de desarrollo durante mi permanencia."),
                ]),
                ("compensaciones", "Compensaciones", [
                    _q("sal_com_1", "Considero que mi compensación era acorde a mi aporte."),
                ]),
                ("carga_salida", "Carga", [
                    _q("sal_car_1", "La carga de trabajo era sostenible."),
                ]),
                ("cultura_salida", "Cultura", [
                    _q("sal_cul_1", "La cultura de la organización coincidió con lo que me ofrecieron al entrar."),
                ]),
                ("recomendacion_salida", "Intención de recomendar", [
                    _q("sal_nps_1", "¿Recomendarías esta organización como lugar para trabajar? (0 a 10)", R),
                ]),
            ]),
    _simple("convivencia", "Convivencia, respeto e inclusión", "convivencia",
            ("Evalúa trato, equidad y confianza en los canales. Complementa —y no reemplaza— los "
             "procedimientos formales de denuncia de la organización."),
            7, [
                ("trato", "Trato respetuoso", [
                    _q("conv_tra_1", "El trato cotidiano en mi entorno de trabajo es respetuoso.", F),
                ]),
                ("canales", "Confianza en los canales", [
                    _q("conv_can_1", "Sé dónde acudir si presencio una situación de maltrato."),
                    _q("conv_can_2", "Confío en que una denuncia sería tratada con seriedad."),
                ]),
                ("equidad", "Equidad", [
                    _q("conv_equ_1", "Las oportunidades se distribuyen con equidad."),
                ]),
                ("discriminacion", "Discriminación percibida", [
                    _q("conv_dis_1", "He presenciado tratos discriminatorios en el último año.", F, reverse=True),
                ]),
                ("inclusion_conv", "Inclusión", [
                    _q("conv_inc_1", "Las diferencias entre personas se respetan aquí."),
                ]),
                ("expresion", "Seguridad para expresar preocupaciones", [
                    _q("conv_exp_1", "Puedo expresar una preocupación sin temor a represalias."),
                ]),
            ]),
    _simple("experiencia_trabajador", "Experiencia del trabajador", "experiencia",
            "Recorre los momentos relevantes del ciclo laboral y los factores que definen la experiencia.",
            9, [
                ("momentos", "Momentos del ciclo laboral", [
                    _q("exp_mom_1", "Mi experiencia al ingresar a la organización fue buena."),
                    _q("exp_mom_2", "Los procesos internos que me afectan (permisos, cambios, evaluaciones) funcionan bien."),
                ]),
                ("herramientas_exp", "Herramientas", [
                    _q("exp_her_1", "Las herramientas de trabajo me facilitan la tarea en lugar de complicarla."),
                ]),
                ("procesos", "Procesos", [
                    _q("exp_pro_1", "Los trámites internos se resuelven en plazos razonables."),
                ]),
                ("cultura_exp", "Cultura", [
                    _q("exp_cul_1", "La forma de trabajar aquí calza con lo que valoro."),
                ]),
                ("liderazgo_exp", "Liderazgo", [
                    _q("exp_lid_1", "Mi jefatura contribuye positivamente a mi experiencia de trabajo."),
                ]),
                ("desarrollo_exp", "Desarrollo", [
                    _q("exp_des_1", "Veo un camino de crecimiento posible aquí."),
                ]),
                ("bienestar", "Bienestar", [
                    _q("exp_bie_1", "Mi trabajo me permite mantener un equilibrio razonable con mi vida personal."),
                ]),
                ("permanencia_exp", "Permanencia", [
                    _q("exp_per_1", "Me proyecto en esta organización a mediano plazo."),
                ]),
            ]),
]


# ==================================================================== materialización
def build_library(db: Session, published_by_id: str | None = None) -> list[SurveyTemplate]:
    """Crea (idempotente) las plantillas maestras de plataforma."""
    created = []
    for spec in TEMPLATES:
        existing = db.execute(
            select(SurveyTemplate).where(
                SurveyTemplate.code == spec["code"], SurveyTemplate.organization_id.is_(None)
            ).execution_options(include_all=True)
        ).scalar_one_or_none()
        if existing:
            created.append(existing)
            continue
        created.append(_materialize(db, spec, published_by_id))
    db.commit()
    _fill_question_bank(db)
    return created


def _materialize(db: Session, spec: dict, published_by_id: str | None) -> SurveyTemplate:
    tpl = SurveyTemplate(
        organization_id=None, code=spec["code"], name=spec["name"],
        purpose=spec.get("purpose"), kind=spec.get("kind", "clima"),
    )
    db.add(tpl)
    db.flush()
    version = SurveyTemplateVersion(
        organization_id=None, template_id=tpl.id, number=1, status=VERSION_PUBLISHED,
        changelog="Versión inicial de la biblioteca istendencia.",
        published_at=dt.datetime.now(dt.UTC), published_by_id=published_by_id,
        estimated_minutes=spec.get("estimated_minutes"),
    )
    db.add(version)
    db.flush()
    for mi, mspec in enumerate(spec["modules"]):
        module = SurveyModule(
            organization_id=None, version_id=version.id, code=mspec["code"],
            name=mspec["name"], description=mspec.get("description"), sort_order=mi,
        )
        db.add(module)
        db.flush()
        for di, dspec in enumerate(mspec["dimensions"]):
            dim = SurveyDimension(
                organization_id=None, module_id=module.id, code=dspec["code"],
                name=dspec["name"], is_outcome=dspec.get("is_outcome", False),
                index_key=dspec.get("index_key"), sort_order=di,
                definition=dspec.get("definition"),
            )
            db.add(dim)
            db.flush()
            for qi, q in enumerate(dspec["questions"]):
                db.add(SurveyQuestion(
                    organization_id=None, dimension_id=dim.id, code=q["code"], text=q["text"],
                    qtype=q["qtype"], scale_key=q["scale"], options=q.get("options"),
                    is_required=q.get("required", True), allow_na=q.get("allow_na", False),
                    is_reverse=q.get("reverse", False), sort_order=qi,
                ))
    return tpl


def _fill_question_bank(db: Session) -> None:
    """Alimenta el banco de preguntas con los ítems de la biblioteca."""
    have = {
        i.code for i in db.execute(
            select(QuestionBankItem).execution_options(include_all=True)
        ).scalars()
    }
    for spec in TEMPLATES:
        for mspec in spec["modules"]:
            for dspec in mspec["dimensions"]:
                for q in dspec["questions"]:
                    if q["code"] in have:
                        continue
                    db.add(QuestionBankItem(
                        organization_id=None, code=q["code"], text=q["text"], qtype=q["qtype"],
                        scale_key=q["scale"], dimension_code=dspec["code"],
                        options=q.get("options"), is_reverse=q.get("reverse", False),
                        tags=[spec["code"]],
                    ))
                    have.add(q["code"])
    db.commit()


def clone_template(
    db: Session, source: SurveyTemplate, organization_id: str, *,
    name: str | None = None, code: str | None = None,
) -> SurveyTemplate:
    """Adapta una plantilla para un cliente conservando la trazabilidad (§8)."""
    tpl = SurveyTemplate(
        organization_id=organization_id,
        code=code or f"{source.code}_adaptada",
        name=name or f"{source.name} (adaptada)",
        purpose=source.purpose, kind=source.kind, derived_from_id=source.id,
    )
    db.add(tpl)
    db.flush()
    src_version = sorted(
        [v for v in source.versions if v.status == VERSION_PUBLISHED] or source.versions,
        key=lambda v: v.number,
    )[-1]
    version = SurveyTemplateVersion(
        organization_id=organization_id, template_id=tpl.id, number=1,
        changelog=f"Adaptada desde {source.code} v{src_version.number}.",
        estimated_minutes=src_version.estimated_minutes,
    )
    db.add(version)
    db.flush()
    for module in src_version.modules:
        m = SurveyModule(
            organization_id=organization_id, version_id=version.id, code=module.code,
            name=module.name, description=module.description, is_enabled=module.is_enabled,
            sort_order=module.sort_order,
        )
        db.add(m)
        db.flush()
        for dim in module.dimensions:
            d = SurveyDimension(
                organization_id=organization_id, module_id=m.id, code=dim.code, name=dim.name,
                definition=dim.definition, is_outcome=dim.is_outcome, index_key=dim.index_key,
                sort_order=dim.sort_order,
            )
            db.add(d)
            db.flush()
            for q in dim.questions:
                db.add(SurveyQuestion(
                    organization_id=organization_id, dimension_id=d.id, code=q.code, text=q.text,
                    help_text=q.help_text, qtype=q.qtype, scale_key=q.scale_key, options=q.options,
                    is_required=q.is_required, allow_na=q.allow_na, is_reverse=q.is_reverse,
                    tags=q.tags, display_logic=q.display_logic, sort_order=q.sort_order,
                ))
    db.commit()
    return tpl
