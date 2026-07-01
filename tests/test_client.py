"""Tests for the v2 OIDC client functions."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from usethatapp import (
    begin_login,
    complete_login,
    get_entitlement,
    get_entitlement_async,
    logout_url,
    refresh,
)
from usethatapp.errors import (
    UtaAuthError,
    UtaPermissionError,
    UtaServerError,
    UtaTokenError,
)
from tests.conftest import API_URL, CLIENT_ID, METADATA, REDIRECT_URI


# ── begin_login ───────────────────────────────────────────────────────

def test_begin_login_builds_authorize_url_with_pkce(oidc_routes):
    url, flow_state = begin_login()
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert url.startswith(METADATA["authorization_endpoint"])
    assert q["response_type"] == ["code"]
    assert q["client_id"] == [CLIENT_ID]
    assert q["redirect_uri"] == [REDIRECT_URI]
    assert q["code_challenge_method"] == ["S256"]
    assert "openid" in q["scope"][0]
    # flow_state is JSON-able and carries the PKCE verifier + state + nonce.
    assert set(flow_state) == {"state", "nonce", "code_verifier", "redirect_uri"}
    assert q["state"] == [flow_state["state"]]
    assert q["nonce"] == [flow_state["nonce"]]


def test_begin_login_state_and_verifier_are_random(oidc_routes):
    _, fs1 = begin_login()
    _, fs2 = begin_login()
    assert fs1["state"] != fs2["state"]
    assert fs1["code_verifier"] != fs2["code_verifier"]


# ── complete_login ────────────────────────────────────────────────────

def _token_response(make_id_token, **id_overrides):
    return httpx.Response(
        200,
        json={
            "access_token": "at-123",
            "refresh_token": "rt-456",
            "id_token": make_id_token(**id_overrides),
            "token_type": "Bearer",
            "expires_in": 1800,
            "scope": "openid entitlements",
        },
    )


def test_complete_login_success(oidc_routes, make_id_token):
    flow_state = {"state": "st", "nonce": "test-nonce", "code_verifier": "v", "redirect_uri": REDIRECT_URI}
    oidc_routes.post(METADATA["token_endpoint"]).mock(
        return_value=_token_response(make_id_token, nonce="test-nonce")
    )
    session = complete_login(code="abc", state="st", flow_state=flow_state)
    assert session.sub == "pairwise-sub-abc"
    assert session.access_token == "at-123"
    assert session.refresh_token == "rt-456"
    assert session.expires_at > 0


def test_complete_login_state_mismatch_raises(oidc_routes, make_id_token):
    flow_state = {"state": "expected", "nonce": "test-nonce", "code_verifier": "v", "redirect_uri": REDIRECT_URI}
    with pytest.raises(UtaAuthError, match="state mismatch"):
        complete_login(code="abc", state="WRONG", flow_state=flow_state)


def test_complete_login_nonce_mismatch_raises(oidc_routes, make_id_token):
    flow_state = {"state": "st", "nonce": "expected-nonce", "code_verifier": "v", "redirect_uri": REDIRECT_URI}
    oidc_routes.post(METADATA["token_endpoint"]).mock(
        return_value=_token_response(make_id_token, nonce="DIFFERENT")
    )
    with pytest.raises(UtaTokenError, match="nonce"):
        complete_login(code="abc", state="st", flow_state=flow_state)


def test_complete_login_expired_id_token_raises(oidc_routes, make_id_token):
    flow_state = {"state": "st", "nonce": "test-nonce", "code_verifier": "v", "redirect_uri": REDIRECT_URI}
    oidc_routes.post(METADATA["token_endpoint"]).mock(
        return_value=_token_response(make_id_token, nonce="test-nonce", exp=1),
    )
    with pytest.raises(UtaTokenError, match="ID token validation failed"):
        complete_login(code="abc", state="st", flow_state=flow_state)


def test_complete_login_wrong_audience_raises(oidc_routes, make_id_token):
    flow_state = {"state": "st", "nonce": "test-nonce", "code_verifier": "v", "redirect_uri": REDIRECT_URI}
    oidc_routes.post(METADATA["token_endpoint"]).mock(
        return_value=_token_response(make_id_token, nonce="test-nonce", aud="someone-else"),
    )
    with pytest.raises(UtaTokenError):
        complete_login(code="abc", state="st", flow_state=flow_state)


def test_complete_login_token_endpoint_error(oidc_routes):
    flow_state = {"state": "st", "nonce": "test-nonce", "code_verifier": "v", "redirect_uri": REDIRECT_URI}
    oidc_routes.post(METADATA["token_endpoint"]).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    with pytest.raises(UtaTokenError, match="invalid_grant"):
        complete_login(code="abc", state="st", flow_state=flow_state)


# ── get_entitlement ───────────────────────────────────────────────────

def test_get_entitlement_licensed(oidc_routes):
    oidc_routes.get(API_URL + "/licensing/entitlement/").mock(
        return_value=httpx.Response(200, json={
            "entitled": True, "version": "Pro", "product_id": "p-1",
            "status": "active", "is_free": False, "period_end": "2026-07-01",
        })
    )
    ent = get_entitlement("at-123")
    assert ent.entitled and ent.version == "Pro" and ent.product_id == "p-1"
    assert ent.status == "active" and ent.is_free is False
    assert ent.period_end == "2026-07-01"


def test_get_entitlement_free(oidc_routes):
    oidc_routes.get(API_URL + "/licensing/entitlement/").mock(
        return_value=httpx.Response(200, json={
            "entitled": True, "version": "Free", "product_id": "p-0",
            "status": "free", "is_free": True, "period_end": None,
        })
    )
    ent = get_entitlement("at-123")
    assert ent.entitled and ent.is_free and ent.status == "free"


@pytest.mark.parametrize("status,exc", [
    (401, UtaTokenError),
    (403, UtaPermissionError),
    (500, UtaServerError),
])
def test_get_entitlement_status_mapping(oidc_routes, status, exc):
    oidc_routes.get(API_URL + "/licensing/entitlement/").mock(
        return_value=httpx.Response(status, text="nope")
    )
    with pytest.raises(exc):
        get_entitlement("at-123")


@pytest.mark.asyncio
async def test_get_entitlement_async(oidc_routes):
    oidc_routes.get(API_URL + "/licensing/entitlement/").mock(
        return_value=httpx.Response(200, json={
            "entitled": False, "version": None, "product_id": None,
            "status": "none", "is_free": False,
        })
    )
    ent = await get_entitlement_async("at-123")
    assert ent.entitled is False and ent.status == "none"


# ── refresh / logout ──────────────────────────────────────────────────

def test_refresh_with_new_id_token(oidc_routes, make_id_token):
    oidc_routes.post(METADATA["token_endpoint"]).mock(
        return_value=httpx.Response(200, json={
            "access_token": "at-new", "refresh_token": "rt-new",
            "id_token": make_id_token(), "token_type": "Bearer",
            "expires_in": 1800, "scope": "openid entitlements",
        })
    )
    session = refresh("rt-456")
    assert session.access_token == "at-new"
    assert session.refresh_token == "rt-new"
    assert session.sub == "pairwise-sub-abc"


def test_refresh_without_id_token_falls_back_to_userinfo(oidc_routes):
    oidc_routes.post(METADATA["token_endpoint"]).mock(
        return_value=httpx.Response(200, json={
            "access_token": "at-new", "token_type": "Bearer", "expires_in": 1800,
        })
    )
    oidc_routes.get(METADATA["userinfo_endpoint"]).mock(
        return_value=httpx.Response(200, json={"sub": "pairwise-sub-abc"})
    )
    session = refresh("rt-456")
    assert session.sub == "pairwise-sub-abc"
    # Rotation didn't return a new refresh token → carry the old one forward.
    assert session.refresh_token == "rt-456"


def test_logout_url(oidc_routes):
    url = logout_url(id_token="idt", post_logout_redirect_uri="https://app.test.example/bye")
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert url.startswith(METADATA["end_session_endpoint"])
    assert q["id_token_hint"] == ["idt"]
    assert q["post_logout_redirect_uri"] == ["https://app.test.example/bye"]
    assert q["client_id"] == [CLIENT_ID]
