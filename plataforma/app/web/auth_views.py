# -*- coding: utf-8 -*-
"""Autenticación de la plataforma."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_session
from ..models import PlatformUser
from ..security.deps import client_ip
from ..security.passwords import verify_password
from ..security.sessions import (
    SESSION_COOKIE,
    is_locked,
    make_session,
    record_fail,
    record_ok,
)
from ..services import audit as audit_svc
from ..templating import templates

router = APIRouter(tags=["autenticación"], include_in_schema=False)


@router.get("/entrar")
def login_form(request: Request):
    return templates.TemplateResponse("public/login.html", {
        "request": request, "error": None, "next": request.query_params.get("next", "/app"),
    })


@router.post("/entrar")
def login(request: Request, email: str = Form(...), password: str = Form(...),
          next: str = Form("/app"), db: Session = Depends(get_session)):
    ip = client_ip(request)
    espera = is_locked(f"login:{ip}")
    if espera:
        return templates.TemplateResponse("public/login.html", {
            "request": request, "next": next,
            "error": f"Demasiados intentos. Espera {espera // 60 + 1} minutos.",
        }, status_code=429)

    email = email.strip().lower()
    user = db.execute(
        select(PlatformUser).where(PlatformUser.email == email)
        .execution_options(include_all=True)
    ).scalar_one_or_none()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        record_fail(f"login:{ip}")
        audit_svc.log(db, "login_fallido", actor_email=email, ip=ip, result="denegado")
        return templates.TemplateResponse("public/login.html", {
            "request": request, "next": next,
            "error": "Credenciales incorrectas.",
        }, status_code=401)

    record_ok(f"login:{ip}")
    user.last_login_at = dt.datetime.now(dt.UTC)
    db.commit()
    audit_svc.log(db, "login", user_id=user.id, actor_email=user.email, ip=ip)

    # Sólo se aceptan destinos internos: evita redirección abierta.
    destination = next if next.startswith("/") and not next.startswith("//") else "/app"
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        make_session(user.id, user.email, user.full_name, user.is_superadmin),
        max_age=settings.session_ttl, httponly=True, samesite="lax",
        secure=settings.secure_cookies, path="/",
    )
    return response


@router.get("/salir")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
