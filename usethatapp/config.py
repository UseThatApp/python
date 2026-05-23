"""Configuration resolution for the UseThatApp SDK.

Reads from :mod:`django.conf.settings` when Django is installed, otherwise
falls back to :data:`os.environ`. The resolved config is cached after the
first :func:`load` call.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Union

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import (
    RSAPrivateKey,
    RSAPublicKey,
)

from .errors import UtaConfigError


# ──────────────────────────────────────────────────────────────────────
# Default (production) marketplace public key.
#
# Maintainers: paste the marketplace's production RSA public key (PEM,
# triple-quoted string) here so end developers don't have to configure
# ``UTA_MARKET_PUBLIC_KEY`` themselves. Leave as ``None`` to require
# explicit configuration.
# ──────────────────────────────────────────────────────────────────────
DEFAULT_MARKET_PUBLIC_KEY_PEM: Optional[str] = """
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA4geFPJUHrBAsG+v9IO+V
nIAK8ZNrHcoLVYPdLE58AyTGtZsg3WkbuJBYtu4dewjPvyFzX5amw7jAf3xNYQb5
DWBSEBDKuGAAyhUFT2/bV7hK+iHchWh/kozR6tyIM5LruL97F+YUDo3EsZF83+19
4tATb75EZdtFz3W2IbuOFId4kYlKnI8yGf2b0wNK37X+v12D0D8gfwPq6v2LnPQ0
YnE9nGtWopMfVVBN+61BdFq+/qeFPBNVuN2VI+Zc32pE0/MyutcoewaG0ZMGCyZC
AejI47yWCnEUGLtto1G5TIkXqII9wExS5qhyAFjn2RR053qw5HD+CuCQ1GTZWt7l
VQIDAQAB
-----END PUBLIC KEY-----
"""


@dataclass(frozen=True)
class UtaConfig:
    app_id: str
    private_key: RSAPrivateKey
    market_public_key: RSAPublicKey
    api_url: str
    clock_skew_seconds: int
    request_timeout_seconds: int


_cached: Optional[UtaConfig] = None


def _get_django_settings():
    try:
        from django.conf import settings  # type: ignore[import-not-found]
    except Exception:
        return None
    # Only return settings if they are actually configured; otherwise
    # accessing attributes raises ImproperlyConfigured (which is NOT
    # an AttributeError, so getattr(..., default) wouldn't save us).
    if getattr(settings, "configured", False):
        return settings
    return None


def _read(name: str) -> Optional[str]:
    djs = _get_django_settings()
    if djs is not None:
        val = getattr(djs, name, None)
        if val is not None:
            return val if isinstance(val, str) else str(val)
    val = os.environ.get(name)
    return val


def _coerce_private_key(value: Union[str, bytes, RSAPrivateKey]) -> RSAPrivateKey:
    if isinstance(value, RSAPrivateKey):
        return value
    if isinstance(value, str):
        value = value.encode("utf-8")
    try:
        key = serialization.load_pem_private_key(value, password=None)
    except Exception as e:  # pragma: no cover - exercised via tests
        raise UtaConfigError(f"UTA_PRIVATE_KEY is not a valid PEM RSA key: {e}")
    if not isinstance(key, RSAPrivateKey):
        raise UtaConfigError("UTA_PRIVATE_KEY must be an RSA private key")
    return key


def _coerce_public_key(value: Union[str, bytes, RSAPublicKey]) -> RSAPublicKey:
    if isinstance(value, RSAPublicKey):
        return value
    if isinstance(value, str):
        value = value.encode("utf-8")
    try:
        key = serialization.load_pem_public_key(value)
    except Exception as e:
        raise UtaConfigError(
            f"UTA_MARKET_PUBLIC_KEY is not a valid PEM RSA public key: {e}"
        )
    if not isinstance(key, RSAPublicKey):
        raise UtaConfigError("UTA_MARKET_PUBLIC_KEY must be an RSA public key")
    return key


def _resolve_key_value(raw_getter, *, direct_name: str, path_name: str):
    """Return raw key material for a (direct, path) setting pair.

    If the direct setting is provided, return it verbatim (string,
    bytes, or already-constructed key object). Otherwise, if the path
    setting is provided, read the file at that path and return its
    bytes. If neither is set, return ``None``.
    """
    direct = raw_getter(direct_name)
    if direct is not None:
        return direct
    path = raw_getter(path_name)
    if path is None:
        return None
    if not isinstance(path, str):
        raise UtaConfigError(f"{path_name} must be a filesystem path string")
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as e:
        raise UtaConfigError(f"{path_name}={path!r}: could not read file: {e}")


def load(force: bool = False) -> UtaConfig:
    """Resolve and cache SDK configuration.

    Args:
        force: re-read from settings/env even if cached.

    Raises:
        UtaConfigError: if a required setting is missing or invalid.
    """
    global _cached
    if _cached is not None and not force:
        return _cached

    # We bypass _read for these to also accept already-constructed key
    # objects when assigned via django.conf.settings.
    djs = _get_django_settings()

    def _raw(name: str):
        if djs is not None:
            v = getattr(djs, name, None)
            if v is not None:
                return v
        return os.environ.get(name)

    app_id = _raw("UTA_APP_ID")
    if not app_id or not isinstance(app_id, str):
        raise UtaConfigError("UTA_APP_ID is required")

    private_key_raw = _resolve_key_value(
        _raw,
        direct_name="UTA_PRIVATE_KEY",
        path_name="UTA_PRIVATE_KEY_PATH",
    )
    if private_key_raw is None:
        raise UtaConfigError(
            "UTA_PRIVATE_KEY or UTA_PRIVATE_KEY_PATH is required"
        )
    private_key = _coerce_private_key(private_key_raw)

    market_pub_raw = _resolve_key_value(
        _raw,
        direct_name="UTA_MARKET_PUBLIC_KEY",
        path_name="UTA_MARKET_PUBLIC_KEY_PATH",
    )
    if market_pub_raw is None:
        market_pub_raw = DEFAULT_MARKET_PUBLIC_KEY_PEM
    if market_pub_raw is None:
        raise UtaConfigError(
            "UTA_MARKET_PUBLIC_KEY or UTA_MARKET_PUBLIC_KEY_PATH is required "
            "(no bundled default available)"
        )
    market_public_key = _coerce_public_key(market_pub_raw)

    api_url = _raw("UTA_API_URL") or "https://usethatapp.com"
    if not isinstance(api_url, str):
        raise UtaConfigError("UTA_API_URL must be a string")
    api_url = api_url.rstrip("/")

    skew_raw = _raw("UTA_CLOCK_SKEW_SECONDS")
    try:
        clock_skew_seconds = int(skew_raw) if skew_raw is not None else 60
    except (TypeError, ValueError):
        raise UtaConfigError("UTA_CLOCK_SKEW_SECONDS must be an integer")

    timeout_raw = _raw("UTA_REQUEST_TIMEOUT_SECONDS")
    try:
        request_timeout_seconds = int(timeout_raw) if timeout_raw is not None else 10
    except (TypeError, ValueError):
        raise UtaConfigError("UTA_REQUEST_TIMEOUT_SECONDS must be an integer")

    _cached = UtaConfig(
        app_id=app_id,
        private_key=private_key,
        market_public_key=market_public_key,
        api_url=api_url,
        clock_skew_seconds=clock_skew_seconds,
        request_timeout_seconds=request_timeout_seconds,
    )
    return _cached


def reset_cache() -> None:
    """Clear the cached configuration. Mostly useful in tests."""
    global _cached
    _cached = None


__all__ = ["UtaConfig", "load", "reset_cache", "DEFAULT_MARKET_PUBLIC_KEY_PEM"]

