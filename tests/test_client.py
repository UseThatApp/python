"""Tests for get_version / get_version_async (server-to-server license pull)."""
from __future__ import annotations

import json
import time

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from usethatapp import (
    UtaBadRequestError,
    UtaError,
    UtaServerError,
    UtaSessionRevokedError,
    UtaSignatureError,
    UtaUnknownSessionError,
    clear_version_cache,
    get_version,
    get_version_async,
)
from usethatapp import config as uta_config


# ──────────────────────────────────────────────────────────────────────
# A tiny httpx mock transport that records each request and lets the
# test set a response.
# ──────────────────────────────────────────────────────────────────────

class _Recorder:
    def __init__(self):
        self.requests = []
        self.responder = lambda req: httpx.Response(200, json={
            "version": "Pro", "cache_until": int(time.time()) + 60,
            "cache_seconds": 60,
        })

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responder(request)


@pytest.fixture
def httpx_mock(monkeypatch):
    rec = _Recorder()
    transport = httpx.MockTransport(rec)

    original_post = httpx.post

    def mock_post(url, **kwargs):
        with httpx.Client(transport=transport) as client:
            return client.post(url, **kwargs)

    monkeypatch.setattr(httpx, "post", mock_post)

    # Async path: patch AsyncClient to use the mock transport.
    original_async_client = httpx.AsyncClient

    class PatchedAsyncClient(original_async_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(rec)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", PatchedAsyncClient)
    return rec


# ──────────────────────────────────────────────────────────────────────
# Sync happy path
# ──────────────────────────────────────────────────────────────────────

def test_get_version_happy_path(httpx_mock, app_id, market_keypair):
    version = get_version("uk-1")
    assert version == "Pro"
    assert len(httpx_mock.requests) == 1

    req = httpx_mock.requests[0]
    assert req.method == "POST"
    assert req.url.path == "/licensing/getversion/"
    assert req.headers["content-type"].startswith("application/json")

    body = json.loads(req.content)
    assert body["app_id"] == app_id
    assert body["user_key"] == "uk-1"
    assert isinstance(body["ts"], int)
    assert abs(body["ts"] - int(time.time())) < 5
    assert isinstance(body["nonce"], str) and len(body["nonce"]) == 32
    assert "signature" in body


def test_request_body_is_canonical_and_signed(httpx_mock, developer_keypair):
    get_version("uk-1")
    req = httpx_mock.requests[0]
    body = json.loads(req.content)

    # Reconstruct canonical bytes — sorted keys, compact separators.
    canonical_dict = {k: body[k] for k in ("app_id", "user_key", "ts", "nonce")}
    canonical = json.dumps(
        canonical_dict, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    sig = bytes.fromhex(body["signature"])
    # Verify with the developer's *public* key — must not raise.
    developer_keypair.public_key().verify(
        sig,
        canonical,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )


def test_fresh_nonce_and_ts_per_call(httpx_mock):
    # bypass cache
    get_version("uk-1", use_cache=False)
    get_version("uk-1", use_cache=False)
    nonces = [json.loads(r.content)["nonce"] for r in httpx_mock.requests]
    assert nonces[0] != nonces[1]


def test_caches_within_cache_until(httpx_mock):
    # Default responder returns cache_until = now + 60.
    v1 = get_version("uk-cache")
    v2 = get_version("uk-cache")
    assert v1 == v2 == "Pro"
    assert len(httpx_mock.requests) == 1  # second call served from cache


def test_use_cache_false_bypasses_cache(httpx_mock):
    get_version("uk-cache")
    get_version("uk-cache", use_cache=False)
    assert len(httpx_mock.requests) == 2


def test_cache_expiry_triggers_new_request(httpx_mock):
    # Responder with cache_until in the past => never cached.
    httpx_mock.responder = lambda req: httpx.Response(200, json={
        "version": "Free",
        "cache_until": int(time.time()) - 1,
        "cache_seconds": 0,
    })
    get_version("uk-expire")
    get_version("uk-expire")
    assert len(httpx_mock.requests) == 2


def test_returns_none_when_version_null(httpx_mock):
    httpx_mock.responder = lambda req: httpx.Response(200, json={
        "version": None,
        "cache_until": int(time.time()) + 30,
        "cache_seconds": 30,
    })
    assert get_version("uk-null") is None


# ──────────────────────────────────────────────────────────────────────
# Error mapping
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,exc", [
    (400, UtaBadRequestError),
    (401, UtaSignatureError),
    (403, UtaSessionRevokedError),
    (404, UtaUnknownSessionError),
    (500, UtaServerError),
    (502, UtaServerError),
    (503, UtaServerError),
])
def test_http_status_mapping(httpx_mock, status, exc):
    httpx_mock.responder = lambda req, s=status: httpx.Response(s, text="nope")
    with pytest.raises(exc):
        get_version("uk-err", use_cache=False)


def test_network_error_maps_to_server_error(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("nope")
    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(UtaServerError):
        get_version("uk-net", use_cache=False)


def test_invalid_json_response(httpx_mock):
    httpx_mock.responder = lambda req: httpx.Response(
        200, text="not json", headers={"content-type": "application/json"}
    )
    with pytest.raises(UtaError):
        get_version("uk-bad", use_cache=False)


def test_response_missing_version(httpx_mock):
    httpx_mock.responder = lambda req: httpx.Response(200, json={"cache_until": 0})
    with pytest.raises(UtaError, match="missing 'version'"):
        get_version("uk-miss", use_cache=False)


def test_empty_user_key_rejected():
    with pytest.raises(UtaError):
        get_version("")


# ──────────────────────────────────────────────────────────────────────
# Async path
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_version_async_happy(httpx_mock):
    clear_version_cache()
    version = await get_version_async("uk-async")
    assert version == "Pro"
    assert len(httpx_mock.requests) == 1


@pytest.mark.asyncio
async def test_get_version_async_403(httpx_mock):
    clear_version_cache()
    httpx_mock.responder = lambda req: httpx.Response(403, text="revoked")
    with pytest.raises(UtaSessionRevokedError):
        await get_version_async("uk-async-403", use_cache=False)

