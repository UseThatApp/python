"""Tests for examples/fastapi_min/app.py."""
from __future__ import annotations

import time

import httpx
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def fastapi_module(load_example):
    # Reset module-level _DEMO_SESSIONS between tests by re-loading.
    return load_example("fastapi_min", "uta_example_fastapi")


@pytest.fixture
def client(fastapi_module):
    return TestClient(fastapi_module.app)


@pytest.fixture
def patched_async_httpx(monkeypatch):
    """Patch httpx.AsyncClient with a configurable mock transport."""
    state = {"responder": lambda req: httpx.Response(200, json={
        "version": "Pro",
        "cache_until": int(time.time()) + 30,
        "cache_seconds": 30,
    }), "requests": []}

    original = httpx.AsyncClient

    class PatchedAsyncClient(original):
        def __init__(self, *args, **kwargs):
            def handler(req):
                state["requests"].append(req)
                return state["responder"](req)
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", PatchedAsyncClient)
    return state


def test_fastapi_launch_happy(client, make_envelope, app_id):
    envelope = make_envelope(version_hint="Pro")
    resp = client.post("/uta/launch/", data={"uta_payload": envelope})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_key"] == "opaque-user-key-xyz"
    assert body["app_id"] == app_id
    assert body["version_hint"] == "Pro"


def test_fastapi_launch_rejects_garbage(client):
    resp = client.post("/uta/launch/", data={"uta_payload": "{nope"})
    assert resp.status_code == 400


def test_fastapi_me_version_unlaunched(client):
    resp = client.get("/me/version/")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "not launched"}


def test_fastapi_full_flow(client, make_envelope, patched_async_httpx):
    launch_resp = client.post(
        "/uta/launch/",
        data={"uta_payload": make_envelope()},
        headers={"x-session-id": "abc"},
    )
    assert launch_resp.status_code == 200

    me_resp = client.get("/me/version/", headers={"x-session-id": "abc"})
    assert me_resp.status_code == 200
    assert me_resp.json() == {"version": "Pro"}
    assert len(patched_async_httpx["requests"]) == 1


def test_fastapi_revoked_clears_session(client, make_envelope, patched_async_httpx):
    client.post(
        "/uta/launch/",
        data={"uta_payload": make_envelope()},
        headers={"x-session-id": "session-2"},
    )
    patched_async_httpx["responder"] = lambda req: httpx.Response(403, text="revoked")
    resp = client.get("/me/version/", headers={"x-session-id": "session-2"})
    assert resp.status_code == 401
    assert "revoked" in resp.json()["detail"]

    # And the session is gone — a subsequent call returns "not launched".
    resp2 = client.get("/me/version/", headers={"x-session-id": "session-2"})
    assert resp2.status_code == 401
    assert resp2.json() == {"detail": "not launched"}


def test_fastapi_server_error_502(client, make_envelope, patched_async_httpx):
    client.post(
        "/uta/launch/",
        data={"uta_payload": make_envelope()},
        headers={"x-session-id": "s3"},
    )
    patched_async_httpx["responder"] = lambda req: httpx.Response(500, text="boom")
    resp = client.get("/me/version/", headers={"x-session-id": "s3"})
    assert resp.status_code == 502


