# -*- coding: utf-8 -*-
"""istendencia · plataforma de clima y experiencia organizacional.

Punto de entrada. El cálculo, los permisos y el umbral de confidencialidad viven
en el servidor: el navegador recibe agregados ya decididos.
"""
from __future__ import annotations

import logging
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import (
    actions,
    benchmarks,
    comments,
    findings,
    organizations,
    reports,
    surveys,
    users,
)
from .api import (
    audit as audit_api,
)
from .api import (
    campaigns as campaigns_api,
)
from .api import (
    platform as platform_api,
)
from .api import (
    results as results_api,
)
from .api import (
    services as services_api,
)
from .config import settings
from .db import TenantIsolationError, engine
from .models import Base
from .security.deps import TenantMiddleware
from .templating import templates
from .web import app_views, auth_views, public_views, survey_views

ROOT = pathlib.Path(__file__).resolve().parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("istendencia.clima")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Al arrancar: esquema, biblioteca maestra, catálogo y (opcional) demo."""
    Base.metadata.create_all(bind=engine)
    from .services.bootstrap import bootstrap
    bootstrap()
    log.info("plataforma lista · entorno=%s · demo=%s", settings.environment, settings.seed_demo)
    yield


app = FastAPI(
    title="istendencia · plataforma de clima organizacional",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs" if not settings.is_production else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if not settings.is_production else None,
    description=(
        "API de la plataforma de diagnóstico y mejoramiento organizacional. "
        "Todos los endpoints de resultados aplican el umbral de confidencialidad "
        "del tenant antes de entregar cualquier agregado."
    ),
)

app.add_middleware(TenantMiddleware)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

# --------------------------------------------------------------- routers
for router in (
    platform_api.router, organizations.router, users.router, surveys.router,
    campaigns_api.router, campaigns_api.pulse_router, results_api.router,
    comments.router, findings.router,
    actions.router, reports.router, benchmarks.router, services_api.router,
    audit_api.router,
):
    app.include_router(router)

app.include_router(public_views.router)
app.include_router(auth_views.router)
app.include_router(survey_views.router)
app.include_router(app_views.router)


# --------------------------------------------------------------- errores
@app.exception_handler(TenantIsolationError)
def _tenant_error(request: Request, exc: TenantIsolationError):
    log.error("aislamiento multitenant violado: %s", exc)
    return JSONResponse({"detail": "Operación no permitida entre organizaciones"}, status_code=403)


@app.exception_handler(StarletteHTTPException)
def _http_error(request: Request, exc: StarletteHTTPException):
    wants_html = "text/html" in (request.headers.get("accept") or "") and not request.url.path.startswith("/api")
    if not wants_html:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    if exc.status_code == 401:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(f"/entrar?next={request.url.path}", status_code=302)
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "status": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )


# --------------------------------------------------------------- salud y arranque
@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok", "environment": settings.environment}


@app.get("/robots.txt", include_in_schema=False, response_class=HTMLResponse)
def robots():
    # La aplicación autenticada y las encuestas no se indexan.
    return HTMLResponse("User-agent: *\nDisallow: /app/\nDisallow: /e/\nAllow: /\n")
