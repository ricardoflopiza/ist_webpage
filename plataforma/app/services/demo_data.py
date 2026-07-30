# -*- coding: utf-8 -*-
"""Datos de demostración (§25).

Empresa ficticia «Andes Servicios Integrados». TODO lo que se crea aquí lleva
`is_demo=True` y la organización se muestra siempre con el distintivo
«datos de demostración» en la interfaz. No se usa ningún dato real de ningún
cliente, ni siquiera anonimizado.

Las respuestas se generan con una semilla fija (`random.Random(20260729)`), así
la demo es idéntica en cada máquina y los tests pueden apoyarse en ella.
"""
from __future__ import annotations

import datetime as dt
import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal, tenant_scope
from ..models import (
    ActionItem,
    ActionPlan,
    Benchmark,
    EmployeePopulation,
    Finding,
    Organization,
    OrganizationMembership,
    OrgUnit,
    PlatformUser,
    PulseSurvey,
    SurveyCampaign,
    SurveyTemplate,
    SurveyTemplateVersion,
)
from ..models.action import AI_BLOCKED, AI_DONE, AI_PROPOSED, AI_RUNNING
from ..models.analysis import F_ALERT, F_LEVER, F_STRENGTH, FS_VALIDATED
from ..models.campaign import ACCESS_TOKEN_LINK, C_ACTIVE, C_PUBLISHED
from ..models.org import (
    ROLE_CLIENT_ADMIN,
    ROLE_CONSULTANT,
    ROLE_LEADER,
    UNIT_BUSINESS,
    UNIT_DEPARTMENT,
    UNIT_WORKPLACE,
)
from ..models.survey import VERSION_PUBLISHED
from ..security.passwords import hash_password
from . import campaigns as campaigns_svc
from . import results as results_svc

DEMO_SLUG = "andes-demo"
DEMO_PASSWORD = "demo1234"      # sólo para la organización de demostración

RNG = random.Random(20260729)

STRUCTURE = [
    ("casa_matriz", "Casa Matriz", UNIT_WORKPLACE, None, [
        ("operaciones", "Operaciones", UNIT_DEPARTMENT, 62),
        ("comercial", "Comercial", UNIT_DEPARTMENT, 38),
        ("administracion", "Administración", UNIT_DEPARTMENT, 24),
        ("tecnologia", "Tecnología", UNIT_DEPARTMENT, 26),
    ]),
]

# Perfil de respuesta por área: media (0-100) y dispersión. Operaciones más
# tensionada, Tecnología mejor evaluada: da un heatmap con contraste real.
AREA_PROFILE = {
    "operaciones": (52, 20),
    "comercial": (63, 16),
    "administracion": (66, 14),
    "tecnologia": (72, 13),
}
DIMENSION_BIAS = {
    "liderazgo": -3, "comunicacion": -6, "claridad_coordinacion": -4,
    "autonomia_participacion": +2, "reconocimiento": -9, "desarrollo": -7,
    "justicia_confianza": -2, "colaboracion": +8, "seguridad_psicologica": +1,
    "inclusion_respeto": +9, "organizacion_sostenible": -11, "sentido_alineamiento": +6,
    "compromiso": +4, "permanencia": -1, "satisfaccion": 0, "recomendacion": -2,
    "calidad_trabajo": +3,
}

COMENTARIOS = [
    ("La coordinación entre turnos se pierde y terminamos repitiendo trabajo.", "operaciones"),
    ("Me gusta el equipo, hay muy buena disposición a ayudarse.", "operaciones"),
    ("Falta reconocimiento cuando sacamos adelante un mes difícil.", "operaciones"),
    ("Las jefaturas cambian las prioridades sin avisar y eso desgasta.", "operaciones"),
    ("Se necesita más personal, la carga no da para el equipo que somos.", "operaciones"),
    ("La comunicación de los cambios llega tarde y por pasillo.", "comercial"),
    ("Las metas son claras, eso ayuda a organizarse.", "comercial"),
    ("Propuse una mejora hace meses y nunca supe en qué quedó.", "comercial"),
    ("Buen ambiente, pero poca claridad sobre cómo crecer aquí.", "administracion"),
    ("Los procesos internos son lentos y hay que insistir mucho.", "administracion"),
    ("Se agradece la flexibilidad para compatibilizar con la vida personal.", "tecnologia"),
    ("Faltan instancias para discutir técnicamente sin que se tome a mal.", "tecnologia"),
    ("El onboarding fue desordenado, tardé semanas en tener accesos.", "tecnologia"),
    ("Valoro que se pueda plantear un desacuerdo sin problemas en mi equipo.", "tecnologia"),
    ("Hay comentarios fuera de lugar que nadie corrige y eso incomoda.", "operaciones"),
]


def seed_demo() -> Organization | None:
    db = SessionLocal()
    try:
        existing = db.execute(
            select(Organization).where(Organization.slug == DEMO_SLUG)
            .execution_options(include_all=True)
        ).scalar_one_or_none()
        if existing:
            return existing
        return _build(db)
    finally:
        db.close()


def _build(db: Session) -> Organization:
    org = Organization(
        slug=DEMO_SLUG, name="Andes Servicios Integrados",
        legal_name="Andes Servicios Integrados SpA (organización ficticia)",
        sector="Servicios", org_type="Empresa privada", region="Metropolitana",
        size_bucket="151-300", plan="gestion_continua", is_demo=True,
        anonymity_threshold=7, min_item_completion=0.6, benchmark_consent=True,
        notes="Organización de demostración. Todos sus datos son simulados.",
    )
    db.add(org)
    db.flush()

    users = _demo_users(db, org)
    units = _demo_structure(db, org)
    _demo_population(db, org, units)

    # La jefatura de demostración sólo ve Operaciones: sin alcance no vería nada,
    # y la demo debe mostrar el comportamiento real del rol.
    membresia = db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == org.id,
            OrganizationMembership.user_id == users["jefatura"].id,
        ).execution_options(include_all=True)
    ).scalar_one()
    membresia.scope_unit_ids = [units["operaciones"].id]
    db.flush()

    with tenant_scope(org.id):
        template, version = _demo_template(db)
        closed = _demo_closed_campaign(db, org, version, units)
        _demo_active_campaign(db, org, version, closed)
        _demo_findings_and_actions(db, org, closed, users, units)
    _demo_benchmark(db, template)
    db.commit()
    return org


# ------------------------------------------------------------------ usuarios
def _demo_users(db: Session, org: Organization) -> dict[str, PlatformUser]:
    people = {
        "consultora": ("consultora@istendencia.demo", "Consultora istendencia (demo)", ROLE_CONSULTANT),
        "rrhh": ("rrhh@andes.demo", "Jefatura de Personas Andes (demo)", ROLE_CLIENT_ADMIN),
        "jefatura": ("jefatura.operaciones@andes.demo", "Jefatura de Operaciones (demo)", ROLE_LEADER),
    }
    out = {}
    for key, (email, name, role) in people.items():
        user = db.execute(
            select(PlatformUser).where(PlatformUser.email == email)
        ).scalar_one_or_none()
        if not user:
            user = PlatformUser(
                email=email, full_name=name,
                password_hash=hash_password(DEMO_PASSWORD), is_demo=True,
            )
            db.add(user)
            db.flush()
        db.add(OrganizationMembership(
            organization_id=org.id, user_id=user.id, role=role,
        ))
        out[key] = user
    db.flush()
    return out


# ------------------------------------------------------------------ estructura
def _demo_structure(db: Session, org: Organization) -> dict[str, OrgUnit]:
    units: dict[str, OrgUnit] = {}
    holding = OrgUnit(organization_id=org.id, kind=UNIT_BUSINESS, code="andes",
                      name="Andes Servicios Integrados", headcount=150)
    db.add(holding)
    db.flush()
    units["andes"] = holding
    for code, name, kind, _parent, children in STRUCTURE:
        sede = OrgUnit(organization_id=org.id, kind=kind, code=code, name=name,
                       parent_id=holding.id, headcount=150)
        db.add(sede)
        db.flush()
        units[code] = sede
        for ccode, cname, ckind, headcount in children:
            child = OrgUnit(organization_id=org.id, kind=ckind, code=ccode, name=cname,
                            parent_id=sede.id, headcount=headcount)
            db.add(child)
            db.flush()
            units[ccode] = child
    db.flush()
    return units


def _demo_population(db: Session, org: Organization, units: dict[str, OrgUnit]) -> None:
    antiguedades = ["Menos de 1 año", "1 a 3 años", "3 a 5 años", "Más de 5 años"]
    modalidades = ["Presencial", "Híbrido", "Remoto"]
    estamentos = ["Operativo", "Profesional", "Jefatura"]
    contratos = ["Indefinido", "Plazo fijo"]
    n = 0
    for code in AREA_PROFILE:
        unit = units[code]
        for _ in range(unit.headcount or 20):
            n += 1
            db.add(EmployeePopulation(
                organization_id=org.id,
                external_id=f"AND-{n:04d}",
                email=f"persona{n:04d}@andes.demo",
                full_name=f"Persona demo {n:04d}",
                org_unit_id=unit.id,
                attributes={
                    "antiguedad": RNG.choice(antiguedades),
                    "modalidad": RNG.choice(modalidades) if code == "tecnologia" else
                                 RNG.choice(["Presencial", "Presencial", "Híbrido"]),
                    "estamento": RNG.choices(estamentos, weights=[6, 3, 1])[0],
                    "contrato": RNG.choices(contratos, weights=[8, 2])[0],
                },
                is_demo=True,
            ))
    db.flush()


# ------------------------------------------------------------------ instrumento
def _demo_template(db: Session) -> tuple[SurveyTemplate, SurveyTemplateVersion]:
    tpl = db.execute(
        select(SurveyTemplate).where(
            SurveyTemplate.code == "clima_integral", SurveyTemplate.organization_id.is_(None)
        ).execution_options(include_all=True)
    ).scalar_one()
    version = db.execute(
        select(SurveyTemplateVersion).where(
            SurveyTemplateVersion.template_id == tpl.id,
            SurveyTemplateVersion.status == VERSION_PUBLISHED,
        ).execution_options(include_all=True)
    ).scalars().first()
    return tpl, version


# ------------------------------------------------------------------ campañas
SEGMENTATION = ["antiguedad", "modalidad", "estamento", "contrato"]


def _new_campaign(org: Organization, version, **kwargs) -> SurveyCampaign:
    return SurveyCampaign(
        organization_id=org.id, version_id=version.id,
        access_method=ACCESS_TOKEN_LINK, segmentation_keys=SEGMENTATION,
        consent_version="1.0",
        consent_text=(
            "Tu participación es voluntaria y anónima. Las respuestas se analizan "
            "de forma agregada y nunca se entregan resultados de grupos con menos "
            "de 7 respuestas. La organización no puede saber quién respondió qué."
        ),
        is_demo=True, **kwargs,
    )


def _demo_closed_campaign(db: Session, org, version, units) -> SurveyCampaign:
    today = dt.date.today()
    campaign = _new_campaign(
        org, version, name="Diagnóstico de clima 2026", period_label="2026 · S1",
        starts_on=today - dt.timedelta(days=120), ends_on=today - dt.timedelta(days=95),
        status="borrador", welcome_text="Gracias por participar en el diagnóstico anual.",
    )
    db.add(campaign)
    db.flush()
    campaigns_svc.generate_invitations(db, campaign)
    campaign.status = C_ACTIVE
    db.commit()

    _simulate_responses(db, campaign, units, participation=0.74)
    campaigns_svc.close_and_mark(db, campaign)
    campaign.status = C_PUBLISHED
    campaign.results_published_at = dt.datetime.now(dt.UTC)
    db.commit()
    results_svc.save_snapshot(db, campaign, org)
    return campaign


def _demo_active_campaign(db: Session, org, version, baseline: SurveyCampaign) -> SurveyCampaign:
    today = dt.date.today()
    campaign = _new_campaign(
        org, version, name="Pulso de seguimiento · trimestre 3", period_label="2026 · T3",
        starts_on=today - dt.timedelta(days=5), ends_on=today + dt.timedelta(days=9),
        status="borrador", is_pulse=True, baseline_campaign_id=baseline.id,
    )
    db.add(campaign)
    db.flush()
    campaigns_svc.generate_invitations(db, campaign)
    campaign.status = C_ACTIVE
    db.add(PulseSurvey(
        organization_id=org.id, campaign_id=campaign.id, baseline_campaign_id=baseline.id,
        dimension_code="reconocimiento", cadence="trimestral",
        scheduled_for=today + dt.timedelta(days=9),
        notes="Pulso de demostración asociado al plan de acción de reconocimiento.",
    ))
    db.commit()
    _simulate_responses(db, campaign, None, participation=0.31, keep_open=True)
    return campaign


def _simulate_responses(db: Session, campaign: SurveyCampaign, units, participation: float,
                        keep_open: bool = False) -> None:
    """Genera respuestas sintéticas coherentes con el perfil de cada área."""
    instrument = results_svc.load_instrument(db, campaign.version_id)
    questions = results_svc.question_map(db, campaign.version_id)
    people = db.execute(
        select(EmployeePopulation).where(EmployeePopulation.is_active.is_(True))
    ).scalars().all()
    unit_names = {u.id: u.code for u in db.execute(select(OrgUnit)).scalars()}

    comentarios_por_area: dict[str, list[str]] = {}
    for texto, area in COMENTARIOS:
        comentarios_por_area.setdefault(area, []).append(texto)

    for person in people:
        if RNG.random() > participation:
            continue
        area = unit_names.get(person.org_unit_id, "operaciones")
        base_mean, sd = AREA_PROFILE.get(area, (60, 15))
        persona_offset = RNG.gauss(0, 8)
        resp, _ticket = campaigns_svc.start_anonymous(db, campaign, person.org_unit_id)
        resp.segment = {
            **{k: v for k, v in (person.attributes or {}).items() if k in SEGMENTATION},
            "unit_path": campaigns_svc._unit_paths(db).get(person.org_unit_id, []),
        }
        values: dict[str, object] = {}
        for dim in instrument.dimensions:
            # Ruido propio de la dimensión dentro de la persona: sin él, todas las
            # dimensiones quedarían casi idénticas y el análisis de impulsores no
            # tendría nada que distinguir (colinealidad perfecta artificial).
            bias = DIMENSION_BIAS.get(dim.code, 0) + RNG.gauss(0, 9)
            for item in dim.items:
                q = questions[item.id]
                if q.qtype == "open_text":
                    continue
                target = base_mean + bias + persona_offset + RNG.gauss(0, sd / 2)
                target = max(0.0, min(100.0, target))
                scale = item.scale
                raw = scale.min_value + target / 100 * (scale.max_value - scale.min_value)
                value = int(round(max(scale.min_value, min(scale.max_value, raw))))
                if item.is_reverse:
                    value = int(scale.reverse(value))
                values[item.id] = value
        # Comentarios abiertos en ~1 de cada 5 respuestas.
        if RNG.random() < 0.2 and comentarios_por_area.get(area):
            open_items = [i for d in instrument.dimensions for i in d.items
                          if questions[i.id].qtype == "open_text"]
            if open_items:
                values[RNG.choice(open_items).id] = RNG.choice(comentarios_por_area[area])
        campaigns_svc.save_answers(db, resp, values, questions)
        if not keep_open or RNG.random() < 0.85:
            campaigns_svc.submit(db, resp, consent_version=campaign.consent_version)
    db.commit()


# ------------------------------------------------------------------ hallazgos y acciones
def _demo_findings_and_actions(db: Session, org, campaign, users, units) -> None:
    payload = results_svc.compute_payload(db, campaign, organization=org)
    by_code = {d["code"]: d for d in payload["dimensions"]}

    def ev(code):
        d = by_code.get(code, {})
        return {"score": d.get("score"), "favorable_pct": d.get("favorable_pct"), "n": d.get("n")}

    findings = [
        Finding(
            organization_id=org.id, campaign_id=campaign.id, ftype=F_ALERT,
            dimension_code="organizacion_sostenible", priority="alta", status=FS_VALIDATED,
            title="Carga de trabajo percibida como insostenible en Operaciones",
            quant_evidence=ev("organizacion_sostenible"),
            qual_evidence="Los comentarios abiertos mencionan repetidamente falta de dotación y turnos.",
            segments=["operaciones"],
            interpretation=("La dimensión de organización sostenible del trabajo es la más baja "
                            "del diagnóstico y concentra los comentarios críticos."),
            limitations="Datos autoinformados y transversales; no permite establecer causas.",
            recommendation="Revisar dotación y distribución de turnos en Operaciones antes del próximo ciclo.",
            is_demo=True,
        ),
        Finding(
            organization_id=org.id, campaign_id=campaign.id, ftype=F_ALERT,
            dimension_code="reconocimiento", priority="alta", status=FS_VALIDATED,
            title="Reconocimiento insuficiente y percibido como poco equitativo",
            quant_evidence=ev("reconocimiento"), segments=["operaciones", "comercial"],
            interpretation="El reconocimiento aparece bajo en todas las áreas y con mayor brecha en Operaciones.",
            limitations="La medición no distingue entre reconocimiento formal e informal.",
            recommendation="Instalar una práctica simple y visible de reconocimiento por equipo.",
            is_demo=True,
        ),
        Finding(
            organization_id=org.id, campaign_id=campaign.id, ftype=F_ALERT,
            dimension_code="comunicacion", priority="media", status=FS_VALIDATED,
            title="La información relevante llega tarde y por canales informales",
            quant_evidence=ev("comunicacion"),
            interpretation="Comunicación es la segunda dimensión más baja; los comentarios lo confirman.",
            recommendation="Definir un canal único y una cadencia fija de comunicación de decisiones.",
            is_demo=True,
        ),
        Finding(
            organization_id=org.id, campaign_id=campaign.id, ftype=F_STRENGTH,
            dimension_code="colaboracion", priority="baja", status=FS_VALIDATED,
            title="Colaboración entre pares como principal fortaleza",
            quant_evidence=ev("colaboracion"),
            interpretation="La disposición a ayudarse aparece alta y consistente entre áreas.",
            is_demo=True,
        ),
        Finding(
            organization_id=org.id, campaign_id=campaign.id, ftype=F_STRENGTH,
            dimension_code="inclusion_respeto", priority="baja", status=FS_VALIDATED,
            title="Trato respetuoso e inclusión bien evaluados",
            quant_evidence=ev("inclusion_respeto"), is_demo=True,
        ),
        Finding(
            organization_id=org.id, campaign_id=campaign.id, ftype=F_STRENGTH,
            dimension_code="sentido_alineamiento", priority="baja", status=FS_VALIDATED,
            title="Las personas encuentran sentido en su trabajo",
            quant_evidence=ev("sentido_alineamiento"), is_demo=True,
        ),
        Finding(
            organization_id=org.id, campaign_id=campaign.id, ftype=F_LEVER,
            dimension_code="reconocimiento", priority="alta", status=FS_VALIDATED,
            title="Posible palanca: reconocimiento sobre el compromiso",
            quant_evidence={"nota": "Ver módulo de impulsores de la campaña."},
            interpretation="Reconocimiento aparece entre los factores más asociados al compromiso.",
            limitations="Asociación estadística, no causalidad.",
            is_demo=True,
        ),
        Finding(
            organization_id=org.id, campaign_id=campaign.id, ftype=F_LEVER,
            dimension_code="comunicacion", priority="media", status=FS_VALIDATED,
            title="Posible palanca: comunicación sobre la confianza",
            interpretation="La comunicación se asocia con justicia y confianza en la dirección.",
            limitations="Asociación estadística, no causalidad.", is_demo=True,
        ),
        Finding(
            organization_id=org.id, campaign_id=campaign.id, ftype=F_LEVER,
            dimension_code="organizacion_sostenible", priority="alta", status=FS_VALIDATED,
            title="Posible palanca: carga de trabajo sobre la intención de permanencia",
            interpretation="La organización del trabajo se asocia con la intención de permanecer.",
            limitations="Asociación estadística, no causalidad.", is_demo=True,
        ),
    ]
    for f in findings:
        db.add(f)
    db.flush()

    plan = ActionPlan(
        organization_id=org.id, campaign_id=campaign.id, name="Plan de mejora 2026",
        description="Compromisos derivados de la devolución de resultados.",
        owner_user_id=users["rrhh"].id, status="activo",
        starts_on=dt.date.today() - dt.timedelta(days=80),
        ends_on=dt.date.today() + dt.timedelta(days=100), is_demo=True,
    )
    db.add(plan)
    db.flush()

    items = [
        ActionItem(
            organization_id=org.id, plan_id=plan.id, finding_id=findings[0].id,
            problem="Carga de trabajo percibida como insostenible en Operaciones.",
            objective="Reducir la percepción de sobrecarga en Operaciones.",
            action="Revisar la malla de turnos y evaluar refuerzo de dotación en los procesos críticos.",
            owner_label="Gerencia de Operaciones", org_unit_id=units["operaciones"].id,
            starts_on=dt.date.today() - dt.timedelta(days=70),
            due_on=dt.date.today() + dt.timedelta(days=20),
            indicator="Puntaje de organización sostenible del trabajo",
            target="+8 puntos en el próximo diagnóstico", status=AI_RUNNING, progress=0.45,
            priority="alta", next_review_on=dt.date.today() + dt.timedelta(days=10), is_demo=True,
        ),
        ActionItem(
            organization_id=org.id, plan_id=plan.id, finding_id=findings[1].id,
            problem="El reconocimiento es bajo y percibido como poco equitativo.",
            objective="Instalar una práctica de reconocimiento sostenida.",
            action="Ritual mensual de reconocimiento por equipo, con criterios conocidos.",
            owner_user_id=users["rrhh"].id,
            starts_on=dt.date.today() - dt.timedelta(days=60),
            due_on=dt.date.today() - dt.timedelta(days=10),
            indicator="Puntaje de reconocimiento", target="+10 puntos",
            status=AI_RUNNING, progress=0.6, priority="alta", is_demo=True,
        ),
        ActionItem(
            organization_id=org.id, plan_id=plan.id, finding_id=findings[2].id,
            problem="La información llega tarde y por canales informales.",
            objective="Ordenar la comunicación de decisiones.",
            action="Boletín quincenal con decisiones y su fundamento, más espacio de preguntas.",
            owner_label="Comunicaciones internas",
            due_on=dt.date.today() + dt.timedelta(days=45),
            indicator="Puntaje de comunicación", target="+6 puntos",
            status=AI_DONE, progress=1.0, priority="media",
            evidence="Tres boletines publicados y sesión de preguntas realizada.",
            completed_at=dt.datetime.now(dt.UTC), is_demo=True,
        ),
        ActionItem(
            organization_id=org.id, plan_id=plan.id, finding_id=findings[0].id,
            problem="Las jefaturas no cuentan con herramientas para conversar los resultados.",
            objective="Habilitar a las jefaturas para la devolución a sus equipos.",
            action="Taller de interpretación de resultados y conversación de equipo.",
            owner_label="Sin responsable asignado",
            due_on=dt.date.today() + dt.timedelta(days=30),
            indicator="Cobertura de equipos con devolución realizada", target="100% de los equipos",
            status=AI_BLOCKED, progress=0.1, priority="media",
            risks="Depende de la disponibilidad de las jefaturas de turno.", is_demo=True,
        ),
        ActionItem(
            organization_id=org.id, plan_id=plan.id,
            problem="Falta de claridad sobre trayectorias de desarrollo.",
            objective="Explicitar rutas de desarrollo por familia de cargos.",
            action="Levantar y publicar rutas de desarrollo para los cargos operativos.",
            owner_label="Desarrollo Organizacional",
            due_on=dt.date.today() + dt.timedelta(days=90),
            indicator="Puntaje de desarrollo", target="+5 puntos",
            status=AI_PROPOSED, progress=0.0, priority="media", is_demo=True,
        ),
    ]
    for it in items:
        db.add(it)
    db.commit()


# ------------------------------------------------------------------ benchmark demo
def _demo_benchmark(db: Session, template: SurveyTemplate) -> None:
    existing = db.execute(
        select(Benchmark).where(Benchmark.code == "demo_servicios_2026")
        .execution_options(include_all=True)
    ).scalar_one_or_none()
    if existing:
        return
    stats = {
        code: {"mean": mean_, "median": mean_, "sd": 9.0,
               "p25": mean_ - 7, "p50": mean_, "p75": mean_ + 7, "n": 4200}
        for code, mean_ in {
            "liderazgo": 64.0, "comunicacion": 58.0, "claridad_coordinacion": 63.0,
            "autonomia_participacion": 65.0, "reconocimiento": 55.0, "desarrollo": 57.0,
            "justicia_confianza": 60.0, "colaboracion": 71.0, "seguridad_psicologica": 66.0,
            "inclusion_respeto": 72.0, "organizacion_sostenible": 56.0,
            "sentido_alineamiento": 70.0,
        }.items()
    }
    db.add(Benchmark(
        organization_id=None, code="demo_servicios_2026",
        name="Referencia sectorial · Servicios (demostración)",
        scope_kind="sector", sector="Servicios", period_label="2026",
        template_code=template.code, version_number=1,
        n_organizations=18, n_responses=4200,
        period_from=dt.date(2026, 1, 1), period_to=dt.date(2026, 6, 30),
        inclusion_criteria=("Organizaciones de servicios con al menos 50 respuestas válidas "
                            "y consentimiento explícito de inclusión."),
        limitations=("Datos de demostración. Un benchmark real exige misma versión del "
                     "instrumento y composición sectorial comparable."),
        stats=stats, is_published=True, is_demo=True,
    ))
    db.commit()
