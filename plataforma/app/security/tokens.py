# -*- coding: utf-8 -*-
"""Tokens de invitación y tickets de retomar encuesta.

Reglas duras:
* El token de invitación se entrega UNA vez al construir el enlace y sólo se
  persiste su SHA-256. Desde la base de datos no se puede reconstruir un enlace
  válido ni, por tanto, suplantar a una persona.
* El ticket de retomar identifica una *respuesta*, jamás a una persona. Va
  firmado con HMAC y guardado en una cookie del navegador del participante; en
  la base sólo queda su hash.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from ..config import settings

_SECRET = settings.session_secret.encode()


# ------------------------------------------------------------------ invitaciones
def new_invitation_token() -> str:
    """Token opaco de 32 bytes. No es secuencial ni derivable del id de la fila."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ------------------------------------------------------------------ firma genérica
def _sign(raw: str) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(_SECRET, raw.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")


def sign_payload(payload: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{raw}.{_sign(raw)}"


def read_payload(value: str | None) -> dict | None:
    if not value or "." not in value:
        return None
    raw, sig = value.rsplit(".", 1)
    if not hmac.compare_digest(_sign(raw), sig):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


# ------------------------------------------------------------------ tickets de respuesta
def make_response_ticket(response_id: str) -> str:
    return sign_payload({"r": response_id, "exp": int(time.time()) + settings.response_ticket_ttl})


def read_response_ticket(value: str | None) -> str | None:
    payload = read_payload(value)
    return payload.get("r") if payload else None
