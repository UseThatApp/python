"""Tests for examples/flask_min/app.py."""
from __future__ import annotations

import time

import httpx
import pytest

flask = pytest.importorskip("flask")


@pytest.fixture
def flask_module(load_example):
    return load_example("flask_min", "uta_example_flask")


@pytest.fixture
def client(flask_module):
    flask_module.app.config["TESTING"] = True
    with flask_module.app.test_client() as c:
        yield c


def _mock_httpx(monkeypatch, response_factory):
    """Install a mock httpx.post that calls response_factory(request)."""
    transport = httpx.MockTransport(response_factory)

    def mock_post(url, **kwargs):
        with httpx.Client(transport=transport) as c:
            return c.post(url, **kwargs)

    monkeypatch.setattr(httpx, "post", mock_post)


def test_flask_launch_happy(client, make_envelope, app_id):
    envelope = make_envelope(version_hint="Pro")
    resp = client.post("/uta/launch/", data={"uta_payload": envelope})
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert body["user_key"] == "opaque-user-key-xyz"
    assert body["app_id"] == app_id
    assert body["version_hint"] == "Pro"


def test_flask_launch_rejects_garbage(client):
    resp = client.post("/uta/launch/", data={"uta_payload": "{not json"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_flask_launch_rejects_missing_field(client):
    resp = client.post("/uta/launch/", data={})
    assert resp.status_code == 400


def test_flask_me_version_unlaunched(client):
    resp = client.get("/me/version/")
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "not launched"}


def test_flask_full_flow_launch_then_version(client, make_envelope, monkeypatch):
    # 1. Launch — sets the session cookie.
    envelope = make_envelope()
    launch_resp = client.post("/uta/launch/", data={"uta_payload": envelope})
    assert launch_resp.status_code == 200

    # 2. Mock the marketplace's getversion endpoint.
    _mock_httpx(monkeypatch, lambda req: httpx.Response(200, json={
        "version": "Pro",
        "cache_until": int(time.time()) + 30,
        "cache_seconds": 30,
    }))

    # 3. The Flask session cookie is preserved by the test client.
    me_resp = client.get("/me/version/")
    assert me_resp.status_code == 200
    assert me_resp.get_json() == {"version": "Pro"}


def test_flask_session_revoked_surfaces_as_502(client, make_envelope, monkeypatch):
    client.post("/uta/launch/", data={"uta_payload": make_envelope()})
    _mock_httpx(monkeypatch, lambda req: httpx.Response(403, text="revoked"))

    me_resp = client.get("/me/version/")
    assert me_resp.status_code == 502


