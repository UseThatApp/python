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

# In-code configuration overrides (Glassbox F-19: parity with the
# JavaScript SDK's ``configure()``). Highest precedence: consulted before
# Django settings and the environment.
_overrides: dict[str, Any] = {}

# Integer-valued options: validated as int (or digit string) up front.
_INT_OVERRIDES = frozenset({
    "request_timeout_seconds",
    "clock_skew_seconds",
})

_ALLOWED_OVERRIDES = frozenset({
    "client_id",
    "client_secret",
    "client_secret_path",
    "redirect_uri",
    "issuer",
    "api_url",
    "scopes",
    "request_timeout_seconds",
    "clock_skew_seconds",
})


def configure(**overrides: Any) -> None:
    """Set configuration in code, overriding Django settings and env vars.

    Mirrors the JavaScript SDK's ``configure()``. Accepts the
    :class:`UtaConfig` field names as keyword arguments::

        import usethatapp
        usethatapp.configure(api_url="http://localhost:8000",
                             issuer="http://localhost:8000/o")

    Values are strings (``request_timeout_seconds`` and
    ``clock_skew_seconds`` also accept int). Passing ``None`` for a key
    removes that override. Clears the cached config, so the next SDK
    call sees the new values. Use :func:`reset_config` to drop every
    override at once.

    Raises:
        UtaConfigError: on an unknown option name or a value of the
            wrong type — rejected HERE, naming the option, rather than
            silently str()-coerced into a corrupt value that surfaces
            later as an opaque OAuth or env-var error (code review:
            ``scopes=["openid"]`` used to become the Python repr string
            and reach the wire as the literal scope parameter).
    """
    unknown = set(overrides) - _ALLOWED_OVERRIDES
    if unknown:
        raise UtaConfigError(
            "unknown configure() option(s): " + ", ".join(sorted(unknown))
        )
    for key, value in overrides.items():
        if value is None:
            continue
        if key in _INT_OVERRIDES:
            # bool is an int subclass; True would silently become 1.
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                raise UtaConfigError(
                    f"configure() option {key!r} must be an integer, "
                    f"got {type(value).__name__}"
                )
            try:
                int(value)
            except ValueError:
                raise UtaConfigError(
                    f"configure() option {key!r} must be an integer, "
                    f"got {value!r}"
                )
        elif not isinstance(value, str):
            hint = ""
            if key == "scopes" and isinstance(value, (list, tuple, set)):
                hint = (
                    ' — join scope names with spaces, e.g. '
                    'scopes="openid entitlements"'
                )
            raise UtaConfigError(
                f"configure() option {key!r} must be a string, "
                f"got {type(value).__name__}{hint}"
            )
    global _cached
    for key, value in overrides.items():
        if value is None:
            _overrides.pop(key, None)
        else:
            _overrides[key] = value
    _cached = None


def load_config(force: bool = False) -> UtaConfig:
    """Resolve and return the active configuration (cached).

    The JS-parity spelling of :func:`load`.
    """
    return load(force)


def reset_config() -> None:
    """Drop every :func:`configure` override and the cached config.

    The next SDK call resolves fresh from Django settings / env vars.
    """
    _overrides.clear()
    reset_cache()



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


def _from_overrides(name: str) -> Any:
    # UTA_CLIENT_ID → "client_id", UTA_API_URL → "api_url", etc.
    if name.startswith("UTA_"):
        return _overrides.get(name[len("UTA_"):].lower())
    return None


def _from_django(name: str) -> Any:
    djs = _get_django_settings()
    if djs is not None:
        return getattr(djs, name, None)
    return None


def _from_env(name: str) -> Any:
    return os.environ.get(name)


# Precedence, highest first: configure() overrides, Django settings,
# environment. _secret_or_path walks these LAYERS explicitly — never mix
# layers per key, or a configured secret path loses to a stale env
# secret (code review finding 2).
_LAYERS = (_from_overrides, _from_django, _from_env)


def _raw(name: str) -> Any:
    for layer in _LAYERS:
        v = layer(name)
        if v is not None:
            return v
    return None


def _str(name: str) -> Optional[str]:
    v = _raw(name)
    if v is None:
        return None
    return v if isinstance(v, str) else str(v)


def _secret_or_path(direct_name: str, path_name: str) -> Optional[str]:
    """Return a secret from ``direct_name`` or by reading ``path_name``.

    The ``*_PATH`` variant supports hosting providers that mount secret
    files (Render Secret Files, Fly volumes, k8s secret volumes, …).

    Precedence is decided per LAYER, not per key: whichever of the pair
    is set in the highest-precedence layer wins, so
    ``configure(client_secret_path=…)`` outranks an environment
    ``UTA_CLIENT_SECRET`` — "overrides win over Django settings and
    environment variables" must hold across the pair, not only within
    one name (code review finding 2). Within a layer, the direct value
    wins over the path.
    """
    for layer in _LAYERS:
        direct = layer(direct_name)
        if direct is not None:
            return direct if isinstance(direct, str) else str(direct)
        path = layer(path_name)
        if path is None:
            continue
        path = path if isinstance(path, str) else str(path)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError as e:
            raise UtaConfigError(
                f"{path_name}={path!r}: could not read file: {e}"
            )
    return None


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

    # Required only for the OIDC login flow; a keys-mode integration
    # (License Key API, add-on off) never redirects a browser, so its
    # absence is enforced in begin_login(), not here.
    redirect_uri = _str("UTA_REDIRECT_URI") or ""

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


def resolve_api_url() -> str:
    """Resolve ``UTA_API_URL`` alone (default + trailing-slash normalize).

    Used by the purchase/pricing helpers, which need only the API base URL
    — not the full OIDC configuration (no redirect URI or secret).
    """
    return (_str("UTA_API_URL") or DEFAULT_API_URL).rstrip("/")


def resolve_client_id() -> str:
    """Resolve ``UTA_CLIENT_ID`` alone.

    Raises:
        UtaConfigError: if ``UTA_CLIENT_ID`` is missing.
    """
    client_id = _str("UTA_CLIENT_ID")
    if not client_id:
        raise UtaConfigError("UTA_CLIENT_ID is required")
    return client_id


def resolve_request_timeout_seconds() -> int:
    """Resolve ``UTA_REQUEST_TIMEOUT_SECONDS`` alone (default ``10``)."""
    return _int("UTA_REQUEST_TIMEOUT_SECONDS", 10)


def reset_cache() -> None:
    """Clear the cached configuration. Mostly useful in tests."""
    global _cached
    _cached = None


__all__ = [
    "UtaConfig",
    "configure",
    "load_config",
    "reset_config",
    "load",
    "reset_cache",
    "resolve_api_url",
    "resolve_client_id",
    "resolve_request_timeout_seconds",
    "DEFAULT_ISSUER",
    "DEFAULT_API_URL",
    "DEFAULT_SCOPES",
]
