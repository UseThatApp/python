"""Configuration resolution for the UseThatApp SDK (v2, OIDC).

Reads from :mod:`django.conf.settings` when Django is installed and
configured, otherwise from :data:`os.environ`. Resolution is cached after
the first :func:`load`; call :func:`reset_cache` (e.g. in tests) to clear.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from .errors import UtaConfigError

# Production defaults. usethatapp.com only serves the ``www`` host.
DEFAULT_ISSUER = "https://www.usethatapp.com/o"
DEFAULT_API_URL = "https://www.usethatapp.com"
DEFAULT_SCOPES = "openid entitlements"


@dataclass(frozen=True)
class UtaConfig:
    client_id: str
    redirect_uri: str
    issuer: str
    api_url: str
    scopes: str
    client_secret: Optional[str]  # None for public (PKCE-only) clients
    request_timeout_seconds: int
    clock_skew_seconds: int


_cached: Optional[UtaConfig] = None


def _get_django_settings() -> Any:
    try:
        from django.conf import settings
    except Exception:
        return None
    # Accessing attributes on unconfigured settings raises (not AttributeError),
    # so guard on ``configured`` first.
    if getattr(settings, "configured", False):
        return settings
    return None


def _raw(name: str) -> Any:
    djs = _get_django_settings()
    if djs is not None:
        v = getattr(djs, name, None)
        if v is not None:
            return v
    return os.environ.get(name)


def _str(name: str) -> Optional[str]:
    v = _raw(name)
    if v is None:
        return None
    return v if isinstance(v, str) else str(v)


def _secret_or_path(direct_name: str, path_name: str) -> Optional[str]:
    """Return a secret from ``direct_name`` or by reading ``path_name``.

    The ``*_PATH`` variant supports hosting providers that mount secret
    files (Render Secret Files, Fly volumes, k8s secret volumes, …). The
    direct value wins if both are set.
    """
    direct = _str(direct_name)
    if direct is not None:
        return direct
    path = _str(path_name)
    if path is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError as e:
        raise UtaConfigError(f"{path_name}={path!r}: could not read file: {e}")


def _int(name: str, default: int) -> int:
    v = _raw(name)
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        raise UtaConfigError(f"{name} must be an integer")


def load(force: bool = False) -> UtaConfig:
    """Resolve and cache SDK configuration.

    Raises:
        UtaConfigError: if a required setting is missing or invalid.
    """
    global _cached
    if _cached is not None and not force:
        return _cached

    client_id = _str("UTA_CLIENT_ID")
    if not client_id:
        raise UtaConfigError("UTA_CLIENT_ID is required")

    redirect_uri = _str("UTA_REDIRECT_URI")
    if not redirect_uri:
        raise UtaConfigError("UTA_REDIRECT_URI is required")

    # Optional: omit for a public (browser/native) client using PKCE only.
    client_secret = _secret_or_path("UTA_CLIENT_SECRET", "UTA_CLIENT_SECRET_PATH")

    issuer = (_str("UTA_ISSUER") or DEFAULT_ISSUER).rstrip("/")
    api_url = (_str("UTA_API_URL") or DEFAULT_API_URL).rstrip("/")
    scopes = _str("UTA_SCOPES") or DEFAULT_SCOPES

    _cached = UtaConfig(
        client_id=client_id,
        redirect_uri=redirect_uri,
        issuer=issuer,
        api_url=api_url,
        scopes=scopes,
        client_secret=client_secret,
        request_timeout_seconds=_int("UTA_REQUEST_TIMEOUT_SECONDS", 10),
        clock_skew_seconds=_int("UTA_CLOCK_SKEW_SECONDS", 60),
    )
    return _cached


def reset_cache() -> None:
    """Clear the cached configuration. Mostly useful in tests."""
    global _cached
    _cached = None


__all__ = [
    "UtaConfig",
    "load",
    "reset_cache",
    "DEFAULT_ISSUER",
    "DEFAULT_API_URL",
    "DEFAULT_SCOPES",
]
