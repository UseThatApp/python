"""Shared fixtures for the v2 (OIDC) SDK test suite."""
from __future__ import annotations

import time

import httpx
import pytest
from joserfc import jwt
from joserfc.jwk import RSAKey

from usethatapp import config as uta_config
from usethatapp import discovery as uta_discovery

ISSUER = "https://oidc.test.example/o"
API_URL = "https://api.test.example"
CLIENT_ID = "client-test-123"
CLIENT_SECRET = "secret-xyz"
REDIRECT_URI = "https://app.test.example/callback"
KID = "test-key-1"

METADATA = {
    "issuer": ISSUER,
    "authorization_endpoint": ISSUER + "/authorize/",
    "token_endpoint": ISSUER + "/token/",
    "jwks_uri": ISSUER + "/.well-known/jwks.json",
    "userinfo_endpoint": ISSUER + "/userinfo/",
    "end_session_endpoint": ISSUER + "/logout/",
}


@pytest.fixture(scope="session")
def signing_key() -> RSAKey:
    return RSAKey.generate_key(2048, parameters={"kid": KID}, private=True)


@pytest.fixture(scope="session")
def jwks_dict(signing_key) -> dict:
    return {"keys": [signing_key.as_dict(private=False)]}


@pytest.fixture
def make_id_token(signing_key):
    """Factory: mint a signed ID token, overriding any claim."""

    def _make(**overrides) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "pairwise-sub-abc",
            "iat": now,
            "exp": now + 3600,
            "nonce": "test-nonce",
        }
        claims.update(overrides)
        header = {"alg": "RS256", "kid": overrides.pop("kid", KID)}
        return jwt.encode(header, claims, signing_key)

    return _make


@pytest.fixture(autouse=True)
def configure_env(monkeypatch):
    """Configure the SDK via env vars; reset caches around each test."""
    monkeypatch.setenv("UTA_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("UTA_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("UTA_REDIRECT_URI", REDIRECT_URI)
    monkeypatch.setenv("UTA_ISSUER", ISSUER)
    monkeypatch.setenv("UTA_API_URL", API_URL)
    monkeypatch.setenv("UTA_REQUEST_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("UTA_CLOCK_SKEW_SECONDS", "60")
    # Drop any inherited secret-path var so tests are hermetic.
    monkeypatch.delenv("UTA_CLIENT_SECRET_PATH", raising=False)
    uta_config.reset_cache()
    uta_discovery.reset_cache()
    yield
    uta_config.reset_cache()
    uta_discovery.reset_cache()


@pytest.fixture
def oidc_routes(respx_mock, jwks_dict):
    """Mock the discovery + JWKS endpoints; return the respx router so a
    test can add token/entitlement/userinfo routes."""
    respx_mock.get(ISSUER + "/.well-known/openid-configuration").mock(
        return_value=httpx.Response(200, json=METADATA)
    )
    respx_mock.get(METADATA["jwks_uri"]).mock(
        return_value=httpx.Response(200, json=jwks_dict)
    )
    return respx_mock
