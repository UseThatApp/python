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
    # Keys-mode integrations never redirect a browser, so load()
    # tolerates a missing redirect URI; begin_login() enforces it.
    monkeypatch.delenv("UTA_REDIRECT_URI", raising=False)
    from usethatapp import begin_login
    from usethatapp import config as _cfg
    _cfg.reset_cache()
    assert _cfg.load().redirect_uri == ""
    with pytest.raises(UtaConfigError, match="UTA_REDIRECT_URI"):
        begin_login()


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


# ── configure() — in-code overrides (Glassbox F-19, JS-SDK parity) ──


@pytest.fixture(autouse=False)
def clean_overrides():
    uta_config.reset_config()
    yield
    uta_config.reset_config()


def test_configure_overrides_env(clean_overrides):
    uta_config.configure(
        api_url="http://localhost:8000", issuer="http://localhost:8000/o"
    )
    cfg = uta_config.load()
    assert cfg.api_url == "http://localhost:8000"
    assert cfg.issuer == "http://localhost:8000/o"
    # Untouched keys still resolve from the environment.
    assert cfg.client_id == "client-test-123"


def test_configure_clears_the_cache(clean_overrides):
    before = uta_config.load(force=True)
    uta_config.configure(api_url="http://localhost:8000")
    after = uta_config.load()  # no force — configure() must invalidate
    assert before.api_url != after.api_url


def test_configure_none_removes_one_override(clean_overrides):
    uta_config.configure(api_url="http://localhost:8000")
    uta_config.configure(api_url=None)
    assert uta_config.load().api_url == "https://api.test.example"


def test_reset_config_drops_everything(clean_overrides):
    uta_config.configure(api_url="http://localhost:8000")
    uta_config.reset_config()
    assert uta_config.load().api_url == "https://api.test.example"


def test_configure_rejects_unknown_options(clean_overrides):
    with pytest.raises(UtaConfigError, match="unknown configure"):
        uta_config.configure(apiUrl="http://localhost:8000")


def test_load_config_is_load(clean_overrides):
    assert uta_config.load_config(force=True) == uta_config.load()


def test_package_root_exports_the_config_api():
    import usethatapp

    for name in (
        "configure", "load_config", "reset_config", "UtaConfig",
        "DEFAULT_API_URL", "DEFAULT_ISSUER", "DEFAULT_SCOPES",
    ):
        assert name in usethatapp.__all__, name
        assert hasattr(usethatapp, name), name


def test_configured_secret_path_outranks_env_secret(
    clean_overrides, monkeypatch, tmp_path
):
    """Code review finding 2: precedence is decided per LAYER — a
    configure() override of EITHER half of the secret pair must outrank
    both env vars, or a stale deploy-env UTA_CLIENT_SECRET silently wins
    over the secret file the developer just configured."""
    import usethatapp

    monkeypatch.setenv("UTA_CLIENT_SECRET", "stale-env-secret")
    secret_file = tmp_path / "secret"
    secret_file.write_text("fresh-file-secret\n")
    usethatapp.configure(client_secret_path=str(secret_file))
    cfg = uta_config.load(force=True)
    assert cfg.client_secret == "fresh-file-secret"


def test_env_secret_still_wins_within_its_own_layer(
    clean_overrides, monkeypatch, tmp_path
):
    """Within one layer the direct value keeps winning over the path."""
    monkeypatch.setenv("UTA_CLIENT_SECRET", "env-secret")
    secret_file = tmp_path / "secret"
    secret_file.write_text("file-secret")
    monkeypatch.setenv("UTA_CLIENT_SECRET_PATH", str(secret_file))
    cfg = uta_config.load(force=True)
    assert cfg.client_secret == "env-secret"


def test_configure_rejects_non_string_values(clean_overrides):
    """Code review finding 6: wrong-typed values are rejected at the
    call site, naming the option — never silently str()-coerced into a
    corrupt value that surfaces later as an opaque OAuth error."""
    import usethatapp
    from usethatapp.errors import UtaConfigError

    with pytest.raises(UtaConfigError, match="scopes.*spaces"):
        usethatapp.configure(scopes=["openid", "entitlements"])

    with pytest.raises(UtaConfigError, match="request_timeout_seconds"):
        usethatapp.configure(request_timeout_seconds="5s")

    with pytest.raises(UtaConfigError, match="api_url"):
        usethatapp.configure(api_url=8000)

    # Legitimate shapes still pass: str everywhere, int for the numerics.
    usethatapp.configure(request_timeout_seconds=3, scopes="openid")
    cfg = uta_config.load(force=True)
    assert cfg.request_timeout_seconds == 3
    assert cfg.scopes == "openid"
