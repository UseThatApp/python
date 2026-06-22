"""OIDC discovery + JWKS fetching, cached per issuer.

The discovery document (``/.well-known/openid-configuration``) and the
signing keys (``jwks_uri``) are fetched once and cached in-process. JWKS
is refetched on demand when an ID token references an unknown ``kid``
(key rotation), so rotating the marketplace's signing key does not break
live apps.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, cast

import httpx
from joserfc.jwk import KeySet

from .config import UtaConfig
from .errors import UtaDiscoveryError

_lock = threading.Lock()
_metadata_cache: Dict[str, Dict[str, Any]] = {}
_jwks_cache: Dict[str, KeySet] = {}


def get_metadata(cfg: UtaConfig) -> Dict[str, Any]:
    """Return the OIDC discovery document for ``cfg.issuer`` (cached)."""
    with _lock:
        cached = _metadata_cache.get(cfg.issuer)
    if cached is not None:
        return cached

    url = cfg.issuer + "/.well-known/openid-configuration"
    try:
        resp = httpx.get(url, timeout=cfg.request_timeout_seconds, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise UtaDiscoveryError(f"failed to fetch OIDC discovery from {url}: {e}")

    for key in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"):
        if key not in data:
            raise UtaDiscoveryError(f"discovery document missing {key!r}")

    metadata = cast(Dict[str, Any], data)
    with _lock:
        _metadata_cache[cfg.issuer] = metadata
    return metadata


def get_jwks(cfg: UtaConfig, *, force: bool = False) -> KeySet:
    """Return the marketplace JWKS for ``cfg.issuer`` (cached).

    ``force=True`` bypasses the cache to pick up a rotated signing key.
    """
    if not force:
        with _lock:
            cached = _jwks_cache.get(cfg.issuer)
        if cached is not None:
            return cached

    jwks_uri = get_metadata(cfg)["jwks_uri"]
    try:
        resp = httpx.get(jwks_uri, timeout=cfg.request_timeout_seconds, follow_redirects=True)
        resp.raise_for_status()
        key_set = KeySet.import_key_set(resp.json())
    except (httpx.HTTPError, ValueError) as e:
        raise UtaDiscoveryError(f"failed to fetch JWKS from {jwks_uri}: {e}")

    with _lock:
        _jwks_cache[cfg.issuer] = key_set
    return key_set


def reset_cache() -> None:
    """Clear cached discovery + JWKS. Mostly useful in tests."""
    with _lock:
        _metadata_cache.clear()
        _jwks_cache.clear()


__all__ = ["get_metadata", "get_jwks", "reset_cache"]
