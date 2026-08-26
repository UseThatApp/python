"""Tests for the v2 OIDC client functions."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

import json

from usethatapp import (
    begin_login,
    complete_login,
    get_entitlement,
    get_entitlement_async,
    logout_url,
    refresh,
    userinfo,
)
from usethatapp.errors import (
    UtaAuthError,
    UtaError,
    UtaPermissionError,
    UtaServiceNotEnabledError,
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


def test_begin_login_extra_params_cannot_override_reserved(oidc_routes):
    with pytest.raises(ValueError, match="state"):
        begin_login(extra_params={"state": "my-tracking-id"})


def test_begin_login_extra_params_passthrough(oidc_routes):
    url, _ = begin_login(extra_params={"audience": "api://x"})
    q = parse_qs(urlparse(url).query)
    assert q["audience"] == ["api://x"]


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
            "product_public_id": "prod_abc123",
        })
    )
    ent = get_entitlement("at-123")
    assert ent.entitled and ent.version == "Pro" and ent.product_id == "p-1"
    assert ent.product_public_id == "prod_abc123"
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


def test_get_entitlement_service_not_enabled(oidc_routes):
    """A 403 whose body says service_not_enabled is the developer's to
    fix (enable the add-on) — it must NOT be reported as a scope
    problem, but must stay catchable as UtaPermissionError."""
    oidc_routes.get(API_URL + "/licensing/entitlement/").mock(
        return_value=httpx.Response(403, json={
            "error": "service_not_enabled",
            "error_description": "The developer has not enabled the "
                                 "entitlement service for this app.",
        })
    )
    with pytest.raises(UtaServiceNotEnabledError, match="Hosted sign-in") as exc_info:
        get_entitlement("at-123")
    assert issubclass(UtaServiceNotEnabledError, UtaPermissionError)
    # Glassbox F-10: the message names the CURRENT public feature name.
    # Code review finding 10 (reversing F-10's host half): the manage
    # hub lives on the production dashboard host — the configured
    # api_url may be a dev stack or gateway with no manage UI, so the
    # message must NOT point there.
    message = str(exc_info.value)
    assert "Auth & Entitlement" not in message
    assert "https://www.usethatapp.com" in message
    assert API_URL not in message


def test_get_entitlement_scope_403_still_permission_error(oidc_routes):
    """The pre-existing 403 (insufficient_scope) keeps its exact class —
    not the new subclass — so callers can tell the two apart."""
    oidc_routes.get(API_URL + "/licensing/entitlement/").mock(
        return_value=httpx.Response(403, json={
            "error": "insufficient_scope", "scope": "entitlements",
        })
    )
    with pytest.raises(UtaPermissionError) as excinfo:
        get_entitlement("at-123")
    assert type(excinfo.value) is UtaPermissionError


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


def test_refresh_userinfo_fallback_missing_sub_raises(oidc_routes):
    oidc_routes.post(METADATA["token_endpoint"]).mock(
        return_value=httpx.Response(200, json={
            "access_token": "at-new", "token_type": "Bearer", "expires_in": 1800,
        })
    )
    oidc_routes.get(METADATA["userinfo_endpoint"]).mock(
        return_value=httpx.Response(200, json={"detail": "no sub here"})
    )
    with pytest.raises(UtaTokenError, match="missing sub"):
        refresh("rt-456")


@pytest.mark.parametrize("status,exc", [
    (400, UtaError),
    (401, UtaTokenError),
    (403, UtaPermissionError),
    (404, UtaError),
    (500, UtaServerError),
])
def test_userinfo_status_mapping(oidc_routes, status, exc):
    oidc_routes.get(METADATA["userinfo_endpoint"]).mock(
        return_value=httpx.Response(status, json={"detail": "nope"})
    )
    with pytest.raises(exc):
        userinfo("at-123")


def test_logout_url(oidc_routes):
    url = logout_url(id_token="idt", post_logout_redirect_uri="https://app.test.example/bye")
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert url.startswith(METADATA["end_session_endpoint"])
    assert q["id_token_hint"] == ["idt"]
    assert q["post_logout_redirect_uri"] == ["https://app.test.example/bye"]
    assert q["client_id"] == [CLIENT_ID]


def test_get_entitlement_429_maps_to_server_error(oidc_routes):
    """Glassbox F-04: a throttle answer is transient — it must land in
    UtaServerError (the retry-with-backoff class), not the base class."""
    oidc_routes.get(API_URL + "/licensing/entitlement/").mock(
        return_value=httpx.Response(
            429, json={"error": "rate_limited"}, headers={"Retry-After": "60"}
        )
    )
    with pytest.raises(UtaServerError, match="rate limited"):
        get_entitlement("at-123")


def test_snippet_caps_every_body_shape():
    """Glassbox F-11 + code review finding 5: ALL bodies are collapsed
    and capped — JSON gets no exemption, because a DRF validation map or
    debug-mode JSON 500 can carry a multi-kilobyte traceback (the
    log-flooding the cap exists to stop). Short bodies pass whole."""
    from usethatapp.client import _snippet

    json_body = '{"error": "unknown_key"}'
    assert _snippet(json_body) == json_body

    html = "<!DOCTYPE html>\n<html>\n" + ("<p>filler</p>\n" * 200) + "</html>"
    out = _snippet(html)
    assert len(out) < 260
    assert "\n" not in out
    assert "truncated" in out

    big_json = json.dumps({"detail": "Traceback (most recent call last)" * 200})
    out = _snippet(big_json)
    assert len(out) < 260
    assert "truncated" in out


def test_non_json_error_body_is_not_inlined_whole(oidc_routes):
    html_page = "<!DOCTYPE html><html>" + "x" * 5000 + "</html>"
    oidc_routes.get(API_URL + "/licensing/entitlement/").mock(
        return_value=httpx.Response(500, text=html_page)
    )
    with pytest.raises(UtaServerError) as exc_info:
        get_entitlement("at-123")
    assert len(str(exc_info.value)) < 400


def test_429_surfaces_retry_after_on_the_exception(oidc_routes):
    """Quiver J-05: the server's backoff hint must reach the caller —
    documented, sent, and previously discarded one layer below them."""
    oidc_routes.get(API_URL + "/licensing/entitlement/").mock(
        return_value=httpx.Response(
            429, json={"error": "rate_limited"}, headers={"Retry-After": "60"}
        )
    )
    with pytest.raises(UtaServerError) as exc_info:
        get_entitlement("at-123")
    assert exc_info.value.retry_after == 60


def test_retry_after_is_none_when_absent(oidc_routes):
    oidc_routes.get(API_URL + "/licensing/entitlement/").mock(
        return_value=httpx.Response(503, text="unavailable")
    )
    with pytest.raises(UtaServerError) as exc_info:
        get_entitlement("at-123")
    assert exc_info.value.retry_after is None


def test_retry_after_http_date_form_is_none(oidc_routes):
    # RFC 9110 allows an HTTP-date; we only surface the seconds form.
    oidc_routes.get(API_URL + "/licensing/entitlement/").mock(
        return_value=httpx.Response(
            429, json={"error": "rate_limited"},
            headers={"Retry-After": "Sat, 23 Aug 2026 02:00:00 GMT"},
        )
    )
    with pytest.raises(UtaServerError) as exc_info:
        get_entitlement("at-123")
    assert exc_info.value.retry_after is None


def test_entitlement_product_id_falls_back_to_public_id(oidc_routes):
    """Code review finding 1: the alias promise in types.py ("gate on
    either field") must hold against a server that predates the
    identifier cutover — same fallback the LicenseState parser has."""
    oidc_routes.get(API_URL + "/licensing/entitlement/").mock(
        return_value=httpx.Response(200, json={
            "entitled": True,
            "version": "Pro",
            "status": "active",
            "product_public_id": "prod_abc123",
            # no product_id field at all
        })
    )
    ent = get_entitlement("at-123")
    assert ent.product_id == "prod_abc123"
    assert ent.product_id == ent.product_public_id


def test_unicode_digit_retry_after_does_not_crash(oidc_routes):
    """Code review finding 3 (reproduced): '²'.isdigit() is True but
    int('²') raises — a malformed Retry-After must degrade to None, not
    turn a 429 into an uncaught ValueError."""
    oidc_routes.get(API_URL + "/licensing/entitlement/").mock(
        # As the wire delivers it: the latin-1 byte 0xB2, which httpx
        # decodes to '²' on read.
        return_value=httpx.Response(
            429, text="slow down", headers=[(b"Retry-After", b"\xb2")]
        )
    )
    with pytest.raises(UtaServerError) as exc_info:
        get_entitlement("at-123")
    assert exc_info.value.retry_after is None


def test_userinfo_429_is_retriable_with_retry_after(oidc_routes):
    """Code review finding 4: the backoff loop this release invites must
    work when the same rate limiter throttles userinfo during login."""
    oidc_routes.get(METADATA["userinfo_endpoint"]).mock(
        return_value=httpx.Response(
            429, text="rate limited", headers={"Retry-After": "30"}
        )
    )
    with pytest.raises(UtaServerError) as exc_info:
        userinfo("at-123")
    assert exc_info.value.retry_after == 30


def test_token_endpoint_429_is_not_a_credential_failure(oidc_routes):
    """Code review finding 4: a throttled token refresh is retriable
    server pushback — surfacing it as UtaTokenError makes callers log
    the user out instead of backing off."""
    oidc_routes.post(METADATA["token_endpoint"]).mock(
        return_value=httpx.Response(
            429, text="rate limited", headers={"Retry-After": "15"}
        )
    )
    with pytest.raises(UtaServerError) as exc_info:
        refresh("rt-123")
    assert exc_info.value.retry_after == 15


def test_timeout_zero_is_respected(oidc_routes, monkeypatch):
    """Code review finding 8: timeout=0.0 — expressible since the float
    widening — is a fail-fast probe, not falsy noise to be replaced by
    the configured default."""
    seen = {}
    real_get = httpx.get

    def spying_get(url, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return real_get(url, **kwargs)

    monkeypatch.setattr(httpx, "get", spying_get)
    oidc_routes.get(API_URL + "/licensing/entitlement/").mock(
        return_value=httpx.Response(200, json={"entitled": False})
    )
    get_entitlement("at-123", timeout=0.0)
    assert seen["timeout"] == 0.0
