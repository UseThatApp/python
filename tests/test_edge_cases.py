"""Extra edge-case tests to push coverage on payloads.py and client.py above 90%."""
from __future__ import annotations

import json
import time

import httpx
import pytest

from usethatapp import (
    UtaAppMismatchError,
    UtaError,
    UtaServerError,
    UtaSessionRevokedError,
    get_user_from_request_async,
    get_version_async,
)
from usethatapp.payloads import unpack_payload


# ── payloads.py edge cases ─────────────────────────────────────────────

def test_envelope_must_be_str_or_mapping(developer_keypair, market_keypair):
    with pytest.raises(UtaError, match="JSON string or mapping"):
        unpack_payload(
            12345,  # type: ignore[arg-type]
            developer_private_key=developer_keypair,
            market_public_key=market_keypair.public_key(),
        )


def test_envelope_field_non_string(make_envelope):
    env = json.loads(make_envelope())
    env["ek"] = 123  # not a string
    with pytest.raises(UtaError, match="must be a hex string"):
        from usethatapp import get_user
        get_user(json.dumps(env))


def test_envelope_bad_iv_length(make_envelope, developer_keypair, market_keypair):
    """If iv is not 12 bytes the SDK rejects before AES-GCM."""
    env = json.loads(make_envelope())
    env["iv"] = "00" * 8  # 8 bytes instead of 12
    # signature now won't verify either (covers ek||iv||ct), but the iv
    # length check could fire first depending on ordering; either error is
    # fine — both inherit UtaError.
    from usethatapp import get_user
    with pytest.raises(UtaError):
        get_user(json.dumps(env))


def test_envelope_unsupported_alg(make_envelope):
    env = json.loads(make_envelope())
    env["alg"] = "made-up"
    from usethatapp import get_user
    with pytest.raises(UtaError, match="unsupported envelope alg"):
        get_user(json.dumps(env))


def test_inner_plaintext_not_object(developer_keypair, market_keypair, app_id):
    """Build an envelope whose plaintext is a JSON array instead of object."""
    import secrets

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    aes = secrets.token_bytes(32)
    iv = secrets.token_bytes(12)
    plaintext = json.dumps(["not", "an", "object"]).encode()
    ek = developer_keypair.public_key().encrypt(
        aes,
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                     algorithm=hashes.SHA256(), label=None),
    )
    ct = AESGCM(aes).encrypt(iv, plaintext, ek + iv)
    signature = market_keypair.sign(
        ek + iv + ct,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    env = {
        "v": 1,
        "alg": "RSA-OAEP-SHA256+AES-256-GCM+RSA-PSS-SHA256",
        "ek": ek.hex(), "iv": iv.hex(), "ct": ct.hex(),
        "signature": signature.hex(),
    }
    from usethatapp import get_user
    with pytest.raises(UtaError, match="not a JSON object"):
        get_user(json.dumps(env))


# ── client.py: schema edge cases ───────────────────────────────────────

def test_inner_payload_missing_field(make_envelope, monkeypatch):
    """If decrypted payload lacks a field, _build_user raises UtaError."""
    # Easiest path: monkeypatch unpack_payload to return a partial dict.
    from usethatapp import client as client_mod

    def fake_unpack(*a, **k):
        return {"kind": "launch", "user_key": "k", "app_id": "irrelevant"}
        # missing iat/exp/nonce

    monkeypatch.setattr(client_mod, "unpack_payload", fake_unpack)
    with pytest.raises(UtaError, match="missing field"):
        client_mod.get_user("{}")


def test_inner_payload_bad_iat(monkeypatch):
    from usethatapp import client as client_mod

    def fake_unpack(*a, **k):
        return {
            "kind": "launch", "user_key": "k",
            "app_id": "11111111-2222-3333-4444-555555555555",
            "iat": "not-int", "exp": "also-bad", "nonce": "xx",
        }

    monkeypatch.setattr(client_mod, "unpack_payload", fake_unpack)
    with pytest.raises(UtaError, match="not integers"):
        client_mod.get_user("{}")


def test_inner_payload_empty_user_key(monkeypatch):
    from usethatapp import client as client_mod

    def fake_unpack(*a, **k):
        return {
            "kind": "launch", "user_key": "",
            "app_id": "11111111-2222-3333-4444-555555555555",
            "iat": int(time.time()), "exp": int(time.time()) + 60,
            "nonce": "xx",
        }

    monkeypatch.setattr(client_mod, "unpack_payload", fake_unpack)
    with pytest.raises(UtaError, match="non-empty string"):
        client_mod.get_user("{}")


def test_inner_payload_bad_version_hint(monkeypatch):
    from usethatapp import client as client_mod

    def fake_unpack(*a, **k):
        return {
            "kind": "launch", "user_key": "k",
            "app_id": "11111111-2222-3333-4444-555555555555",
            "iat": int(time.time()), "exp": int(time.time()) + 60,
            "nonce": "xx", "version_hint": 12345,
        }

    monkeypatch.setattr(client_mod, "unpack_payload", fake_unpack)
    with pytest.raises(UtaError, match="version_hint must be a string"):
        client_mod.get_user("{}")


def test_app_id_wrong_type(monkeypatch):
    from usethatapp import client as client_mod

    def fake_unpack(*a, **k):
        return {
            "kind": "launch", "user_key": "k",
            "app_id": 12345,
            "iat": int(time.time()), "exp": int(time.time()) + 60,
            "nonce": "xx",
        }

    monkeypatch.setattr(client_mod, "unpack_payload", fake_unpack)
    with pytest.raises(UtaAppMismatchError):
        client_mod.get_user("{}")


# ── client.py: async request shapes ───────────────────────────────────

@pytest.mark.asyncio
async def test_get_user_from_request_async_django_style(make_envelope):
    class Req:
        def __init__(self, payload):
            self.POST = {"uta_payload": payload}

    user = await get_user_from_request_async(Req(make_envelope()))
    assert user.user_key == "opaque-user-key-xyz"


@pytest.mark.asyncio
async def test_get_user_from_request_async_starlette_style(make_envelope):
    payload = make_envelope()

    class Req:
        async def form(self):
            return {"uta_payload": payload}

    user = await get_user_from_request_async(Req())
    assert user.user_key == "opaque-user-key-xyz"


@pytest.mark.asyncio
async def test_get_user_from_request_async_missing_form():
    class Req:
        pass

    with pytest.raises(UtaError):
        await get_user_from_request_async(Req())


@pytest.mark.asyncio
async def test_get_user_from_request_async_missing_payload():
    class Req:
        async def form(self):
            return {}

    with pytest.raises(UtaError, match="uta_payload"):
        await get_user_from_request_async(Req())


def test_get_user_from_request_async_request_with_async_form_in_sync_path(make_envelope):
    """Sync get_user_from_request against a Starlette-style request should raise a clear error."""
    from usethatapp import get_user_from_request

    payload = make_envelope()

    class Req:
        async def form(self):
            return {"uta_payload": payload}

    with pytest.raises(UtaError, match="async"):
        get_user_from_request(Req())


# ── client.py: async network failure path ─────────────────────────────

@pytest.mark.asyncio
async def test_get_version_async_network_error(monkeypatch):
    class BoomClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k):
            raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", BoomClient)
    with pytest.raises(UtaServerError):
        await get_version_async("uk-net", use_cache=False)


# ── client.py: cache_until fallback to cache_seconds ──────────────────

def test_response_uses_cache_seconds_when_no_cache_until(monkeypatch):
    """If server omits cache_until but sends cache_seconds, we still cache."""
    from usethatapp import get_version

    state = {"calls": 0}

    def handler(req):
        state["calls"] += 1
        return httpx.Response(200, json={"version": "Pro", "cache_seconds": 30})

    transport = httpx.MockTransport(handler)

    def mock_post(url, **kwargs):
        with httpx.Client(transport=transport) as c:
            return c.post(url, **kwargs)

    monkeypatch.setattr(httpx, "post", mock_post)
    assert get_version("uk-cs") == "Pro"
    assert get_version("uk-cs") == "Pro"
    assert state["calls"] == 1


def test_response_with_no_cache_info_does_not_cache(monkeypatch):
    from usethatapp import get_version

    state = {"calls": 0}

    def handler(req):
        state["calls"] += 1
        return httpx.Response(200, json={"version": "Pro"})

    transport = httpx.MockTransport(handler)

    def mock_post(url, **kwargs):
        with httpx.Client(transport=transport) as c:
            return c.post(url, **kwargs)

    monkeypatch.setattr(httpx, "post", mock_post)
    get_version("uk-nocache")
    get_version("uk-nocache")
    assert state["calls"] == 2


def test_unexpected_http_status(monkeypatch):
    from usethatapp import get_version

    def handler(req):
        return httpx.Response(302, text="redirect")

    transport = httpx.MockTransport(handler)

    def mock_post(url, **kwargs):
        with httpx.Client(transport=transport) as c:
            return c.post(url, **kwargs)

    monkeypatch.setattr(httpx, "post", mock_post)
    with pytest.raises(UtaError, match="unexpected status"):
        get_version("uk-302", use_cache=False)


# ── cache eviction on expiry ──────────────────────────────────────────

def test_cache_evicts_on_expiry(monkeypatch):
    """Once cache_until is past, the next call hits the network again."""
    from usethatapp import client as client_mod
    from usethatapp import get_version

    # Pre-populate the cache with a near-future expiry.
    client_mod._cache_put("uk-evict", "Pro", int(time.time()) + 1)

    state = {"calls": 0}

    def handler(req):
        state["calls"] += 1
        return httpx.Response(200, json={"version": "Free", "cache_seconds": 0})

    transport = httpx.MockTransport(handler)

    def mock_post(url, **kwargs):
        with httpx.Client(transport=transport) as c:
            return c.post(url, **kwargs)

    monkeypatch.setattr(httpx, "post", mock_post)

    # First call: served from cache, no HTTP.
    assert get_version("uk-evict") == "Pro"
    assert state["calls"] == 0

    # Advance "now" past the cache window.
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 10)
    monkeypatch.setattr(client_mod.time, "time", lambda: real_time() + 10)

    # Now the cached entry should be considered expired.
    assert get_version("uk-evict") == "Free"
    assert state["calls"] == 1


# ── sync form callable that returns a dict (Werkzeug-ish edge case) ───

def test_get_user_from_request_sync_callable_form_returning_dict(make_envelope):
    """If request.form is callable and returns a dict (not a coroutine)."""
    from usethatapp import get_user_from_request

    payload = make_envelope()

    class Req:
        def form(self):
            return {"uta_payload": payload}

    user = get_user_from_request(Req())
    assert user.user_key == "opaque-user-key-xyz"


def test_get_user_from_request_form_get_raises(make_envelope):
    """If form.get() blows up, _extract should fall through cleanly."""
    from usethatapp import get_user_from_request

    class WeirdForm:
        def get(self, key, default=None):
            raise RuntimeError("boom")

    class Req:
        form = WeirdForm()
        POST = {}  # so we go past POST too

    with pytest.raises(UtaError, match="uta_payload"):
        get_user_from_request(Req())

