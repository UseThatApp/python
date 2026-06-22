"""Tests for usethatapp.config (v2)."""
from __future__ import annotations

import pytest

from usethatapp import config as uta_config
from usethatapp.config import DEFAULT_API_URL, DEFAULT_ISSUER, DEFAULT_SCOPES
from usethatapp.errors import UtaConfigError


def test_loads_from_env():
    cfg = uta_config.load(force=True)
    assert cfg.client_id == "client-test-123"
    assert cfg.client_secret == "secret-xyz"
    assert cfg.redirect_uri == "https://app.test.example/callback"
    assert cfg.issuer == "https://oidc.test.example/o"


def test_defaults(monkeypatch):
    monkeypatch.delenv("UTA_ISSUER", raising=False)
    monkeypatch.delenv("UTA_API_URL", raising=False)
    monkeypatch.delenv("UTA_SCOPES", raising=False)
    cfg = uta_config.load(force=True)
    assert cfg.issuer == DEFAULT_ISSUER
    assert cfg.api_url == DEFAULT_API_URL
    assert cfg.scopes == DEFAULT_SCOPES


def test_missing_client_id(monkeypatch):
    monkeypatch.delenv("UTA_CLIENT_ID", raising=False)
    with pytest.raises(UtaConfigError, match="UTA_CLIENT_ID"):
        uta_config.load(force=True)


def test_missing_redirect_uri(monkeypatch):
    monkeypatch.delenv("UTA_REDIRECT_URI", raising=False)
    with pytest.raises(UtaConfigError, match="UTA_REDIRECT_URI"):
        uta_config.load(force=True)


def test_public_client_has_no_secret(monkeypatch):
    monkeypatch.delenv("UTA_CLIENT_SECRET", raising=False)
    cfg = uta_config.load(force=True)
    assert cfg.client_secret is None


def test_secret_from_path(monkeypatch, tmp_path):
    monkeypatch.delenv("UTA_CLIENT_SECRET", raising=False)
    secret_file = tmp_path / "secret"
    secret_file.write_text("file-secret-123\n")
    monkeypatch.setenv("UTA_CLIENT_SECRET_PATH", str(secret_file))
    cfg = uta_config.load(force=True)
    assert cfg.client_secret == "file-secret-123"


def test_bad_int(monkeypatch):
    monkeypatch.setenv("UTA_REQUEST_TIMEOUT_SECONDS", "not-a-number")
    with pytest.raises(UtaConfigError):
        uta_config.load(force=True)
