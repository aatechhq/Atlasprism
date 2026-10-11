from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core import security


@pytest.mark.parametrize("audience_kind", ["origin", "auth_url"])
def test_decode_neon_token_accepts_instance_audiences(monkeypatch, audience_kind: str) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    issuer = "https://example.neonauth.test/database/auth"
    origin = "https://example.neonauth.test"
    audience = origin if audience_kind == "origin" else issuer
    now = dt.datetime.now(dt.timezone.utc)
    token = jwt.encode(
        {
            "sub": "user-1",
            "email": "user@example.test",
            "emailVerified": True,
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + dt.timedelta(minutes=5),
        },
        private_key,
        algorithm="EdDSA",
        headers={"kid": "test-key"},
    )

    client = SimpleNamespace(
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=public_key)
    )
    monkeypatch.setattr(security, "_neon_jwks_client", lambda: client)
    monkeypatch.setattr(security.settings, "neon_auth_jwks_url", issuer + "/.well-known/jwks.json")
    monkeypatch.setattr(security.settings, "neon_auth_issuer", issuer)
    monkeypatch.setattr(security.settings, "neon_auth_audience", origin)

    payload = security.decode_neon_token(token)
    assert payload is not None
    assert payload["sub"] == "user-1"


def test_decode_neon_token_rejects_unrelated_audience(monkeypatch) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    issuer = "https://example.neonauth.test/database/auth"
    now = dt.datetime.now(dt.timezone.utc)
    token = jwt.encode(
        {
            "sub": "user-1",
            "iss": issuer,
            "aud": "https://attacker.example",
            "exp": now + dt.timedelta(minutes=5),
        },
        private_key,
        algorithm="EdDSA",
        headers={"kid": "test-key"},
    )

    client = SimpleNamespace(
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=public_key)
    )
    monkeypatch.setattr(security, "_neon_jwks_client", lambda: client)
    monkeypatch.setattr(security.settings, "neon_auth_jwks_url", issuer + "/.well-known/jwks.json")
    monkeypatch.setattr(security.settings, "neon_auth_issuer", issuer)
    monkeypatch.setattr(security.settings, "neon_auth_audience", "https://example.neonauth.test")

    assert security.decode_neon_token(token) is None
