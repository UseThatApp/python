"""Shared fixtures for the SDK test suite."""
from __future__ import annotations

import importlib.util
import os
import secrets
import sys
from pathlib import Path
from types import ModuleType

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from usethatapp import config as uta_config
from usethatapp.client import clear_version_cache


def _gen_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem(priv: rsa.RSAPrivateKey) -> str:
    return priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


def _pub_pem(priv: rsa.RSAPrivateKey) -> str:
    return priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


@pytest.fixture(scope="session")
def market_keypair() -> rsa.RSAPrivateKey:
    return _gen_key()


@pytest.fixture(scope="session")
def developer_keypair() -> rsa.RSAPrivateKey:
    return _gen_key()


@pytest.fixture
def app_id() -> str:
    return "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def configure_env(monkeypatch, app_id, developer_keypair, market_keypair):
    """Configure SDK via env vars and reset caches for each test."""
    monkeypatch.setenv("UTA_APP_ID", app_id)
    monkeypatch.setenv("UTA_PRIVATE_KEY", _pem(developer_keypair))
    monkeypatch.setenv("UTA_MARKET_PUBLIC_KEY", _pub_pem(market_keypair))
    monkeypatch.setenv("UTA_API_URL", "https://test.usethatapp.example")
    monkeypatch.setenv("UTA_CLOCK_SKEW_SECONDS", "60")
    monkeypatch.setenv("UTA_REQUEST_TIMEOUT_SECONDS", "5")
    uta_config.reset_cache()
    clear_version_cache()
    yield
    uta_config.reset_cache()
    clear_version_cache()


@pytest.fixture
def make_envelope(developer_keypair, market_keypair, app_id):
    """Factory: builds a launch envelope using the test keypairs."""
    from usethatapp.payloads import build_payload

    def _make(**overrides):
        kwargs = dict(
            user_key=overrides.pop("user_key", "opaque-user-key-xyz"),
            app_id=overrides.pop("app_id", app_id),
            developer_public_key=developer_keypair.public_key(),
            market_private_key=market_keypair,
        )
        kwargs.update(overrides)
        return build_payload(**kwargs)

    return _make


# ──────────────────────────────────────────────────────────────────────
# Example-app loader (used by tests/test_example_*.py)
# ──────────────────────────────────────────────────────────────────────

EXAMPLES_ROOT = Path(__file__).parent.parent / "examples"


@pytest.fixture
def load_example():
    """Factory fixture: import an example's ``app.py`` as a fresh module."""

    def _load(folder: str, module_name: str) -> ModuleType:
        path = EXAMPLES_ROOT / folder / "app.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    return _load
