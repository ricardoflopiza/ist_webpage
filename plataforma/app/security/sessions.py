# -*- coding: utf-8 -*-
"""Sesión de plataforma: cookie firmada HMAC + rate limiting de login."""
from __future__ import annotations

import time

from ..config import settings
from .tokens import read_payload, sign_payload

SESSION_COOKIE = "ist_clima_session"
TICKET_COOKIE = "ist_clima_ticket"


def make_session(user_id: str, email: str, name: str, is_superadmin: bool) -> str:
    return sign_payload({
        "u": user_id, "e": email, "n": name, "sa": bool(is_superadmin),
        "exp": int(time.time()) + settings.session_ttl,
    })


def read_session(cookie: str | None) -> dict | None:
    payload = read_payload(cookie)
    if not payload or "u" not in payload:
        return None
    return {
        "user_id": payload["u"], "email": payload["e"],
        "name": payload["n"], "is_superadmin": payload.get("sa", False),
    }


# ------------------------------------------------------------------ rate limiting
# En memoria: suficiente para un proceso. Si se escala a varios workers, mover a Redis.
_fails: dict[str, dict] = {}
MAX_FAILS, WINDOW, LOCK = 5, 300, 900


def is_locked(key: str) -> int:
    rec = _fails.get(key)
    if not rec:
        return 0
    remaining = rec.get("locked_until", 0) - time.time()
    return int(remaining) if remaining > 0 else 0


def record_fail(key: str) -> None:
    now = time.time()
    rec = _fails.setdefault(key, {"stamps": [], "locked_until": 0})
    rec["stamps"] = [t for t in rec["stamps"] if now - t < WINDOW] + [now]
    if len(rec["stamps"]) >= MAX_FAILS:
        rec["locked_until"] = now + LOCK
        rec["stamps"] = []


def record_ok(key: str) -> None:
    _fails.pop(key, None)


def reset_rate_limit() -> None:
    """Sólo para tests."""
    _fails.clear()
