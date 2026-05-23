"""Tests for examples/dash_min/app.py.

Dash sits on top of Flask. We exercise the launch endpoint registered
on Dash's underlying Flask server and verify it stores ``user_key`` in
the session, then directly invoke the callback function.
"""
from __future__ import annotations

import time

import httpx
import pytest

dash = pytest.importorskip("dash")


@pytest.fixture
def dash_module(load_example):
    return load_example("dash_min", "uta_example_dash")


@pytest.fixture
def flask_client(dash_module):
    dash_module.flask_server.config["TESTING"] = True
    with dash_module.flask_server.test_client() as c:
        yield c


def test_dash_launch_happy(flask_client, make_envelope, app_id):
    resp = flask_client.post(
        "/uta/launch/",
        data={"uta_payload": make_envelope(version_hint="Pro")},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["next"] == "/"


def test_dash_launch_rejects_bad_payload(flask_client):
    resp = flask_client.post("/uta/launch/", data={"uta_payload": "{garbage"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_dash_callback_without_session_says_not_launched(dash_module):
    """The ``refresh`` callback returns a clear message when no session."""
    with dash_module.flask_server.test_request_context("/"):
        # No session — the callback should not crash.
        msg = dash_module.refresh(1)
    assert "Not launched" in msg


def test_dash_callback_with_session_calls_get_version(
    dash_module, make_envelope, monkeypatch
):
    # 1. Mock the marketplace.
    def handler(req):
        return httpx.Response(200, json={
            "version": "Pro",
            "cache_until": int(time.time()) + 30,
            "cache_seconds": 30,
        })

    transport = httpx.MockTransport(handler)

    def mock_post(url, **kwargs):
        with httpx.Client(transport=transport) as c:
            return c.post(url, **kwargs)

    monkeypatch.setattr(httpx, "post", mock_post)

    # 2. Invoke the callback inside a request context with a populated session.
    from flask import session as flask_session

    with dash_module.flask_server.test_request_context("/"):
        flask_session["uta_user_key"] = "opaque-user-key-xyz"
        result = dash_module.refresh(1)

    assert "Pro" in result



