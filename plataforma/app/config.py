# -*- coding: utf-8 -*-
"""Configuración central. Todo por variables de entorno; nada de secretos en el repo."""
import os
from dataclasses import dataclass


def _bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip() in ("1", "true", "True", "yes")


@dataclass(frozen=True)
class Settings:
    session_secret: str
    database_url: str
    secure_cookies: bool
    session_ttl: int
    response_ticket_ttl: int
    default_anonymity_threshold: int
    default_min_item_completion: float
    environment: str
    public_base_url: str
    seed_demo: bool

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def load_settings() -> Settings:
    secret = os.environ.get("SESSION_SECRET", "").strip()
    env = os.environ.get("ENVIRONMENT", "development").strip()
    if not secret:
        if env == "production":
            raise RuntimeError("Falta SESSION_SECRET en producción")
        # Desarrollo/test: secreto efímero, se invalidan las sesiones al reiniciar.
        secret = "dev-inseguro-solo-local"
    return Settings(
        session_secret=secret,
        database_url=os.environ.get("DATABASE_URL", "sqlite:///./clima.db"),
        secure_cookies=_bool("SECURE_COOKIES", "0"),
        session_ttl=int(os.environ.get("SESSION_TTL", 8 * 3600)),
        response_ticket_ttl=int(os.environ.get("RESPONSE_TICKET_TTL", 30 * 86400)),
        default_anonymity_threshold=int(os.environ.get("DEFAULT_ANONYMITY_THRESHOLD", 7)),
        default_min_item_completion=float(os.environ.get("DEFAULT_MIN_ITEM_COMPLETION", 0.6)),
        environment=env,
        public_base_url=os.environ.get("PUBLIC_BASE_URL", "http://localhost:8003").rstrip("/"),
        seed_demo=_bool("SEED_DEMO", "0"),
    )


settings = load_settings()
