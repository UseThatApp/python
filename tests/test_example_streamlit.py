"""Tests for examples/streamlit_min/app.py.

Streamlit provides ``streamlit.testing.v1.AppTest`` for headless
script execution. We use it to drive the dev panel: paste an
envelope, click the verify button, then confirm the version lookup
runs.
"""
from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

streamlit = pytest.importorskip("streamlit")
try:
    from streamlit.testing.v1 import AppTest
except Exception:  # pragma: no cover
    pytest.skip("streamlit.testing.v1.AppTest unavailable", allow_module_level=True)


APP_PATH = str(Path(__file__).parent.parent / "examples" / "streamlit_min" / "app.py")


def _mock_httpx(monkeypatch, responder):
    transport = httpx.MockTransport(responder)

    def mock_post(url, **kwargs):
        with httpx.Client(transport=transport) as c:
            return c.post(url, **kwargs)

    monkeypatch.setattr(httpx, "post", mock_post)


def test_streamlit_initial_run_no_session():
    """A fresh run with no envelope should stop with the 'not launched' info."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=10)
    assert not at.exception
    infos = [m.value for m in at.info]
    assert any("No active launch session" in m for m in infos)


def test_streamlit_paste_envelope_then_get_version(make_envelope, monkeypatch):
    # Mock the marketplace before the script runs (it'll call get_version
    # after the user_key lands in session_state).
    _mock_httpx(monkeypatch, lambda req: httpx.Response(200, json={
        "version": "Pro",
        "cache_until": int(time.time()) + 30,
        "cache_seconds": 30,
    }))

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=10)
    assert not at.exception

    # Drive the dev panel: paste an envelope and click the button.
    at.text_area[0].set_value(make_envelope(version_hint="Pro"))
    at.button[0].click()
    at.run(timeout=10)

    assert not at.exception
    assert at.session_state["uta_user_key"] == "opaque-user-key-xyz"

    # The metric should show "Pro" as the current license tier.
    metric_values = [m.value for m in at.metric]
    assert "Pro" in metric_values


def test_streamlit_rejects_bad_payload(monkeypatch):
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=10)
    at.text_area[0].set_value("{not json")
    at.button[0].click()
    at.run(timeout=10)
    assert not at.exception
    assert "uta_user_key" not in at.session_state
    # An error widget should be present.
    errors = [e.value for e in at.error]
    assert any("Rejected" in e for e in errors)

