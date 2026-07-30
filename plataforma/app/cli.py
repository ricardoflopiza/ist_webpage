# -*- coding: utf-8 -*-
"""Utilidades de línea de comandos.

    python -m app.cli init-db
    python -m app.cli crear-admin correo@dominio.cl "Nombre Apellido"
    python -m app.cli crear-organizacion mi-empresa "Mi Empresa SpA"
    python -m app.cli cargar-demo
    python -m app.cli reset-password correo@dominio.cl
"""
from __future__ import annotations

import getpass
import sys

from sqlalchemy import select

from .db import SessionLocal, engine
from .models import Base, Organization, PlatformUser
from .security.passwords import generate_password, hash_password


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    from .services.bootstrap import bootstrap
    bootstrap()
    print("Base de datos lista (biblioteca y catálogo de servicios cargados).")


def crear_admin(email: str, nombre: str) -> None:
    password = getpass.getpass("Contraseña: ")
    if len(password) < 10:
        sys.exit("La contraseña debe tener al menos 10 caracteres.")
    if password != getpass.getpass("Repite la contraseña: "):
        sys.exit("Las contraseñas no coinciden.")
    db = SessionLocal()
    try:
        email = email.strip().lower()
        user = db.execute(
            select(PlatformUser).where(PlatformUser.email == email)
        ).scalar_one_or_none()
        if user:
            user.password_hash = hash_password(password)
            user.is_superadmin = True
            print(f"Actualizado: {email}")
        else:
            db.add(PlatformUser(email=email, full_name=nombre,
                                password_hash=hash_password(password), is_superadmin=True))
            print(f"Superadministrador creado: {email}")
        db.commit()
    finally:
        db.close()


def crear_organizacion(slug: str, nombre: str) -> None:
    db = SessionLocal()
    try:
        if db.execute(select(Organization).where(Organization.slug == slug)
                      .execution_options(include_all=True)).scalar_one_or_none():
            sys.exit(f"Ya existe una organización con el identificador «{slug}».")
        org = Organization(slug=slug, name=nombre)
        db.add(org)
        db.commit()
        print(f"Organización creada: {nombre} (/app/o/{slug})")
    finally:
        db.close()


def reset_password(email: str) -> None:
    nueva = generate_password()
    db = SessionLocal()
    try:
        user = db.execute(
            select(PlatformUser).where(PlatformUser.email == email.strip().lower())
        ).scalar_one_or_none()
        if not user:
            sys.exit("No existe ese usuario.")
        user.password_hash = hash_password(nueva)
        db.commit()
        print(f"Contraseña temporal para {email}: {nueva}")
        print("Entrégala por un canal seguro; se muestra una sola vez.")
    finally:
        db.close()


def cargar_demo() -> None:
    from .services.demo_data import seed_demo
    org = seed_demo()
    print(f"Datos de demostración cargados: {org.name} (/app/o/{org.slug})" if org else "Ya existían.")


def main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        return
    cmd, *args = argv
    commands = {
        "init-db": init_db,
        "crear-admin": crear_admin,
        "crear-organizacion": crear_organizacion,
        "cargar-demo": cargar_demo,
        "reset-password": reset_password,
    }
    fn = commands.get(cmd)
    if not fn:
        sys.exit(f"Comando desconocido: {cmd}\n{__doc__}")
    fn(*args)


if __name__ == "__main__":
    main(sys.argv[1:])
