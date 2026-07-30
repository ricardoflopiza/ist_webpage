# -*- coding: utf-8 -*-
"""Contraseñas: PBKDF2-SHA256 600k (recomendación OWASP), sólo stdlib.

Se mantiene el mismo esquema que `reportes-web` para que las credenciales de la
consultora sean migrables entre ambos servicios sin re-hashear. No se usa
`hashlib.scrypt`: depende de cómo se compiló OpenSSL y no está garantizado.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

PBKDF2_ITER = 600_000


def hash_password(pw: str, iterations: int = PBKDF2_ITER) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, iterations, dklen=32)
    return f"pbkdf2${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, iter_s, salt_b64, dk_b64 = stored.split("$")
        if algo != "pbkdf2":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, int(iter_s), dklen=len(expected))
        return hmac.compare_digest(dk, expected)   # comparación en tiempo constante
    except Exception:
        return False


def generate_password(length: int = 14) -> str:
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))
