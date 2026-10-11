"""Minimal auth: PBKDF2 password hashing + signed JWT.

PBKDF2-HMAC-SHA256 from the standard library is used deliberately instead of
bcrypt/argon2: no compiled dependency, auditable in a few lines, and adequate
for the single-admin release this version ships (PRD 3). If this grows to real
multi-user signup, move to argon2id.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import secrets
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from app.core.config import settings

_ITERATIONS = 310_000
_ALGO = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return "{}${}${}${}".format(
        _ALGO, _ITERATIONS,
        base64.b64encode(salt).decode(), base64.b64encode(dk).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, b64salt, b64dk = stored.split("$")
        if algo != _ALGO:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(b64salt), int(iters)
        )
        return hmac.compare_digest(dk, base64.b64decode(b64dk))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


@lru_cache(maxsize=1)
def _neon_jwks_client() -> PyJWKClient:
    return PyJWKClient(settings.neon_auth_jwks_url)


def decode_neon_token(token: str) -> dict[str, Any] | None:
    """Verify a Neon Auth JWT against its rotating public keys."""
    if not settings.neon_auth_jwks_url:
        return None
    try:
        signing_key = _neon_jwks_client().get_signing_key_from_jwt(token)
        options: dict[str, Any] = {
            "require": ["exp", "sub"],
        }
        kwargs: dict[str, Any] = {}
        if settings.neon_auth_issuer:
            kwargs["issuer"] = settings.neon_auth_issuer
        else:
            options["verify_iss"] = False
        if settings.neon_auth_audience:
            # Neon anonymous tokens use the instance origin as `aud`, while
            # authenticated Better Auth JWTs can use the full Auth URL. Both
            # are issued by this same verified JWKS/issuer and must be accepted.
            kwargs["audience"] = list({
                settings.neon_auth_audience.rstrip("/"),
                settings.neon_auth_issuer.rstrip("/"),
            })
        else:
            options["verify_aud"] = False
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["EdDSA"],
            options=options,
            **kwargs,
        )
    except (jwt.PyJWTError, ValueError):
        return None


def redact_secret(value: str | None) -> str:
    """UI-safe representation of a credential: never the value itself."""
    if not value:
        return "not configured"
    v = value.strip()
    return f"configured (****{v[-4:]})" if len(v) >= 4 else "configured"
