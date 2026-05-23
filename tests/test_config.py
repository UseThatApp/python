"""Tests for usethatapp.config.load()."""
from __future__ import annotations

import pytest

from usethatapp import UtaConfigError
from usethatapp import config as uta_config


def test_load_reads_env(monkeypatch):
    cfg = uta_config.load(force=True)
    assert cfg.app_id  # set by conftest
    assert cfg.api_url == "https://test.usethatapp.example"
    assert cfg.clock_skew_seconds == 60
    assert cfg.request_timeout_seconds == 5


def test_load_caches(monkeypatch):
    a = uta_config.load(force=True)
    b = uta_config.load()
    assert a is b


def test_missing_app_id_raises(monkeypatch):
    monkeypatch.delenv("UTA_APP_ID", raising=False)
    uta_config.reset_cache()
    with pytest.raises(UtaConfigError, match="UTA_APP_ID"):
        uta_config.load()


def test_missing_private_key_raises(monkeypatch):
    monkeypatch.delenv("UTA_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("UTA_PRIVATE_KEY_PATH", raising=False)
    uta_config.reset_cache()
    with pytest.raises(
        UtaConfigError,
        match="UTA_PRIVATE_KEY or UTA_PRIVATE_KEY_PATH",
    ):
        uta_config.load()


def test_missing_market_pub_raises(monkeypatch):
    monkeypatch.delenv("UTA_MARKET_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("UTA_MARKET_PUBLIC_KEY_PATH", raising=False)
    uta_config.reset_cache()
    with pytest.raises(
        UtaConfigError,
        match="UTA_MARKET_PUBLIC_KEY or UTA_MARKET_PUBLIC_KEY_PATH",
    ):
        uta_config.load()


def test_bad_skew_raises(monkeypatch):
    monkeypatch.setenv("UTA_CLOCK_SKEW_SECONDS", "not-int")
    uta_config.reset_cache()
    with pytest.raises(UtaConfigError, match="UTA_CLOCK_SKEW_SECONDS"):
        uta_config.load()


def test_bad_private_key_raises(monkeypatch):
    monkeypatch.setenv("UTA_PRIVATE_KEY", "not a pem")
    uta_config.reset_cache()
    with pytest.raises(UtaConfigError, match="UTA_PRIVATE_KEY"):
        uta_config.load()


def test_api_url_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("UTA_API_URL", "https://example.test/")
    uta_config.reset_cache()
    cfg = uta_config.load()
    assert cfg.api_url == "https://example.test"


# ─── KEY_PATH fallback ────────────────────────────────────────────────


def test_loads_private_key_from_path(
    monkeypatch, tmp_path, developer_keypair, market_keypair, app_id
):
    """Setting UTA_PRIVATE_KEY_PATH (and unsetting UTA_PRIVATE_KEY) reads the file."""
    from cryptography.hazmat.primitives import serialization

    pem = developer_keypair.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_file = tmp_path / "priv.pem"
    key_file.write_bytes(pem)

    monkeypatch.delenv("UTA_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("UTA_PRIVATE_KEY_PATH", str(key_file))
    uta_config.reset_cache()

    cfg = uta_config.load()
    assert cfg.app_id == app_id
    # Round-trip the key to confirm the loaded private key matches the file.
    assert cfg.private_key.private_numbers() == developer_keypair.private_numbers()


def test_loads_market_public_key_from_path(
    monkeypatch, tmp_path, market_keypair
):
    """Setting UTA_MARKET_PUBLIC_KEY_PATH reads the file."""
    from cryptography.hazmat.primitives import serialization

    pub_pem = market_keypair.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_file = tmp_path / "market.pub"
    key_file.write_bytes(pub_pem)

    monkeypatch.delenv("UTA_MARKET_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("UTA_MARKET_PUBLIC_KEY_PATH", str(key_file))
    uta_config.reset_cache()

    cfg = uta_config.load()
    assert cfg.market_public_key.public_numbers() == market_keypair.public_key().public_numbers()


def test_direct_env_var_wins_over_path(
    monkeypatch, tmp_path, developer_keypair, app_id
):
    """If both UTA_PRIVATE_KEY and UTA_PRIVATE_KEY_PATH are set, the direct value wins."""
    from cryptography.hazmat.primitives import serialization

    pem = developer_keypair.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    # File contains garbage; if it were read, load() would fail.
    bad_file = tmp_path / "garbage.pem"
    bad_file.write_text("this is not a PEM key")

    monkeypatch.setenv("UTA_PRIVATE_KEY", pem)
    monkeypatch.setenv("UTA_PRIVATE_KEY_PATH", str(bad_file))
    uta_config.reset_cache()

    # Should succeed — the bad file path is ignored because direct env var is set.
    cfg = uta_config.load()
    assert cfg.app_id == app_id


def test_private_key_path_missing_file_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("UTA_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("UTA_PRIVATE_KEY_PATH", str(tmp_path / "does-not-exist.pem"))
    uta_config.reset_cache()
    with pytest.raises(UtaConfigError, match="UTA_PRIVATE_KEY_PATH"):
        uta_config.load()

