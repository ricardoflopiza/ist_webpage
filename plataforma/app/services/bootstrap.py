# -*- coding: utf-8 -*-
"""Arranque: biblioteca maestra, catálogo de servicios y datos de demostración."""
from __future__ import annotations

import logging
import os

from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..models import PlatformUser
from ..security.passwords import hash_password
from .catalog import seed_services
from .library import build_library

log = logging.getLogger("istendencia.clima.bootstrap")


def ensure_superadmin() -> PlatformUser | None:
    """Crea el primer superadministrador desde variables de entorno.

    En producción es obligatorio pasar `ADMIN_EMAIL` y `ADMIN_PASSWORD` (o usar
    `python -m app.cli crear-admin`): no existe ninguna credencial por defecto.
    """
    email = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD") or ""
    if not email or not password:
        return None
    db = SessionLocal()
    try:
        user = db.execute(
            select(PlatformUser).where(PlatformUser.email == email)
        ).scalar_one_or_none()
        if user:
            return user
        user = PlatformUser(
            email=email, full_name=os.environ.get("ADMIN_NAME", "Administrador"),
            password_hash=hash_password(password), is_superadmin=True,
        )
        db.add(user)
        db.commit()
        log.info("superadministrador creado: %s", email)
        return user
    finally:
        db.close()


def bootstrap() -> None:
    db = SessionLocal()
    try:
        build_library(db)
        seed_services(db)
    finally:
        db.close()
    ensure_superadmin()
    if settings.seed_demo:
        from .demo_data import seed_demo
        seed_demo()
