# -*- coding: utf-8 -*-
"""Confidencialidad: la única puerta por la que pasa cualquier resultado (§11).

`can_display_segment()` es la función central que exige el encargo. La usan la
API, los dashboards, los reportes y las exportaciones — no existe camino que
muestre un agregado sin pasar por aquí.

Reglas implementadas
--------------------
1. Umbral efectivo = máximo entre el umbral del tenant y el de la campaña.
   Una campaña puede endurecerlo, nunca relajarlo por debajo del tenant.
2. El segmento debe tener al menos `umbral` respuestas.
3. El *universo* del segmento (personas de la nómina) también debe alcanzar el
   umbral: 4 respuestas de un equipo de 4 identifican a las 4 personas.
4. Cruzar muchas variables reidentifica aunque cada celda parezca grande: a
   partir de 3 variables cruzadas el umbral se incrementa en un 50 %.
5. Supresión complementaria: si al ocultar los grupos pequeños queda uno solo
   visible, ese también se oculta (se deduciría por diferencia).
6. El rol manda: una jefatura sólo ve sus unidades; un participante no ve nada
   que no esté publicado por la organización.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from ..models import Organization, SurveyCampaign
from ..models.org import ROLE_LEADER, ROLE_PARTICIPANT
from ..security.deps import Viewer

CROSS_FILTER_LIMIT = 2          # variables cruzadas sin penalización
CROSS_FILTER_FACTOR = 1.5       # penalización sobre el umbral al superarlo


@dataclass
class SegmentDecision:
    """Resultado de la evaluación. `allowed=False` ⇒ no se entrega ningún número."""

    allowed: bool
    reason: str
    threshold: int
    n_responses: int
    n_universe: int | None = None
    detail: dict = field(default_factory=dict)

    @property
    def message(self) -> str:
        if self.allowed:
            return ""
        return {
            "bajo_umbral": (
                f"Segmento con menos de {self.threshold} respuestas. "
                "No se muestra para proteger la confidencialidad."
            ),
            "universo_pequeno": (
                f"El grupo tiene menos de {self.threshold} personas. "
                "No se muestran resultados de grupos de ese tamaño."
            ),
            "cruce_riesgoso": (
                "La combinación de filtros permitiría reconocer a personas. "
                f"Se requieren al menos {self.threshold} respuestas para este cruce."
            ),
            "sin_permiso": "Tu rol no permite ver este segmento.",
            "fuera_de_alcance": "Sólo puedes ver resultados de las unidades a tu cargo.",
            "campania_abierta": (
                "La campaña sigue abierta: los resultados se publican al cerrarla."
            ),
        }.get(self.reason, "Resultado no disponible.")


def effective_threshold(
    organization: Organization,
    campaign: SurveyCampaign | None = None,
    n_filters: int = 0,
) -> int:
    base = int(organization.anonymity_threshold or 7)
    if campaign is not None and campaign.anonymity_threshold:
        base = max(base, int(campaign.anonymity_threshold))
    if n_filters > CROSS_FILTER_LIMIT:
        base = int(math.ceil(base * CROSS_FILTER_FACTOR))
    return base


def can_display_segment(
    filters: dict | None,
    viewer: Viewer,
    campaign: SurveyCampaign | None,
    *,
    organization: Organization | None = None,
    n_responses: int = 0,
    n_universe: int | None = None,
    allow_open_campaign: bool = False,
) -> SegmentDecision:
    """Decide si un agregado puede mostrarse. Firma pedida en §11.

    `filters` son las variables de segmentación aplicadas (unidad, antigüedad…).
    `n_responses` es el conteo real del segmento y `n_universe` el tamaño del
    grupo en la nómina (si se conoce).
    """
    org = organization or viewer.organization
    filters = {k: v for k, v in (filters or {}).items() if v not in (None, "", [])}
    n_filters = len(filters)
    threshold = effective_threshold(org, campaign, n_filters) if org else 7

    # 1) Rol
    if viewer.role == ROLE_PARTICIPANT:
        return SegmentDecision(False, "sin_permiso", threshold, n_responses, n_universe)
    if viewer.role == ROLE_LEADER:
        unit = filters.get("org_unit_id") or filters.get("unidad")
        allowed_units = set(viewer.scope_unit_ids or [])
        if not unit or unit not in allowed_units:
            return SegmentDecision(False, "fuera_de_alcance", threshold, n_responses, n_universe)

    # 2) Campaña abierta: no se entregan resultados mientras se responde (§10)
    if campaign is not None and not allow_open_campaign:
        from ..models.campaign import RESULT_STATES
        if campaign.status not in RESULT_STATES:
            return SegmentDecision(False, "campania_abierta", threshold, n_responses, n_universe)

    # 3) Universo
    if n_universe is not None and n_universe < threshold:
        return SegmentDecision(False, "universo_pequeno", threshold, n_responses, n_universe)

    # 4) Respuestas
    if n_responses < threshold:
        reason = "cruce_riesgoso" if n_filters > CROSS_FILTER_LIMIT else "bajo_umbral"
        return SegmentDecision(False, reason, threshold, n_responses, n_universe)

    return SegmentDecision(True, "ok", threshold, n_responses, n_universe)


def suppress_small_groups(
    groups: list[dict], threshold: int, count_key: str = "n"
) -> list[dict]:
    """Aplica supresión primaria y complementaria a una lista de grupos.

    Cada grupo se devuelve con `suppressed: bool`. Los suprimidos pierden todo
    valor numérico salvo su etiqueta: no basta con no dibujarlos en el gráfico,
    la API tampoco los entrega.
    """
    out = []
    for g in groups:
        g = dict(g)
        g["suppressed"] = int(g.get(count_key) or 0) < threshold
        out.append(g)

    visible = [g for g in out if not g["suppressed"]]
    hidden = [g for g in out if g["suppressed"]]
    hidden_total = sum(int(g.get(count_key) or 0) for g in hidden)

    # Complementaria: con un solo grupo visible y poco escondido, el oculto se deduce.
    if len(visible) == 1 and hidden and hidden_total < threshold:
        visible[0]["suppressed"] = True

    for g in out:
        if g["suppressed"]:
            for k in list(g.keys()):
                if k not in ("label", "key", "suppressed", "org_unit_id"):
                    g[k] = None
    return out


# ------------------------------------------------------------------ comentarios
_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_RE_PHONE = re.compile(r"(?:\+?56)?[\s-]?9[\s-]?\d{4}[\s-]?\d{4}")
_RE_RUT = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}[-‐][\dkK]\b")
_RE_URL = re.compile(r"https?://\S+")

# Menciones que activan el protocolo de revisión (§17). Deliberadamente amplias:
# marcan para revisión humana, no acusan ni concluyen nada.
SENSITIVE_PATTERNS = {
    "acoso": r"\bacos(o|ar|ada|ado)\b|\bhostigami",
    "acoso_sexual": r"\bacoso sexual\b|\btocamient|\binsinuaci(ón|on) sexual",
    "violencia": r"\bviolencia\b|\bagresi(ón|on|va|vo)\b|\bgolpe",
    "discriminacion": r"\bdiscrimina|\bracis|\bxenofob|\bhomofob|\bmachis",
    "amenaza": r"\bamenaz",
    "riesgo_inmediato": r"\bsuicid|\bautolesi|\bquitarme la vida",
    "salud_mental": r"\bdepresi(ón|on)\b|\bcrisis de p(á|a)nico\b|\blicencia psiqui",
}


def redact_personal_data(text: str) -> str:
    """Oculta datos personales evidentes antes de exponer un comentario."""
    t = _RE_EMAIL.sub("[correo oculto]", text or "")
    t = _RE_URL.sub("[enlace oculto]", t)
    t = _RE_RUT.sub("[rut oculto]", t)
    t = _RE_PHONE.sub("[teléfono oculto]", t)
    return t


def detect_sensitive(text: str) -> list[str]:
    """Devuelve las etiquetas de riesgo detectadas. Nunca decide por sí sola:
    marca el comentario para revisión humana con protocolo."""
    low = (text or "").lower()
    return [flag for flag, pattern in SENSITIVE_PATTERNS.items() if re.search(pattern, low)]


def visible_comments(
    comments: Iterable, viewer: Viewer, decision: SegmentDecision
) -> list:
    """Filtra comentarios según umbral y permiso de comentarios sensibles."""
    from ..security.permissions import P_COMMENTS_SENSITIVE

    if not decision.allowed:
        return []
    can_sensitive = viewer.can(P_COMMENTS_SENSITIVE)
    return [c for c in comments if can_sensitive or not c.is_sensitive]
