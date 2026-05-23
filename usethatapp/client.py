"""Public client functions: ``get_user_from_request`` and ``get_version``.

These are the two entry points developers call from their apps.
"""

from __future__ import annotations

import inspect
import json
import secrets
import threading
import time
from typing import Any, Dict, Mapping, Optional, Tuple, Union

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from . import config as _config
from .errors import (
    UtaAppMismatchError,
    UtaBadRequestError,
    UtaError,
    UtaPayloadExpiredError,
    UtaServerError,
    UtaSessionRevokedError,
    UtaSignatureError,
    UtaUnknownSessionError,
)
from .payloads import unpack_payload
from .types import UtaUser

_GETVERSION_PATH = "/licensing/getversion/"

# Process-local TTL cache: { user_key: (version, expires_at_unix_seconds) }
_version_cache: Dict[str, Tuple[Optional[str], int]] = {}
_cache_lock = threading.Lock()


# ──────────────────────────────────────────────────────────────────────
# get_user_from_request
# ──────────────────────────────────────────────────────────────────────

def _extract_payload_from_request(request: Any) -> str:
    """Best-effort extraction of the ``uta_payload`` field from a
    Django / Flask / Starlette-style request.

    For FastAPI/Starlette (which exposes an async ``form()`` method),
    callers should prefer :func:`get_user_from_request_async` or pass the raw
    payload to :func:`get_user`.
    """
    # Django: request.POST is a QueryDict
    post = getattr(request, "POST", None)
    if post is not None:
        try:
            val = post.get("uta_payload")
        except Exception:
            val = None
        if val is not None:
            return val

    # Flask: request.form is an ImmutableMultiDict
    form = getattr(request, "form", None)
    if form is not None and not callable(form):
        try:
            val = form.get("uta_payload")
        except Exception:
            val = None
        if val is not None:
            return val

    # Starlette/FastAPI: request.form is async; try to call it.
    if callable(form):
        try:
            result = form()
        except Exception as e:
            raise UtaError(f"failed to read form from request: {e}")
        # Starlette returns an ``AwaitableOrContextManagerWrapper`` that
        # is awaitable but is NOT a coroutine — use ``inspect.isawaitable``
        # for the broader check.
        if inspect.isawaitable(result):
            raise UtaError(
                "request.form() is async; use get_user_from_request_async() or pass the "
                "raw payload to get_user()"
            )
        try:
            val = result.get("uta_payload")
        except Exception:
            val = None
        if val is not None:
            return val

    raise UtaError("could not find 'uta_payload' in request")


def _build_user(inner: Dict[str, Any], expected_app_id: str, clock_skew: int) -> UtaUser:
    # Schema check
    for field in ("kind", "user_key", "app_id", "iat", "exp", "nonce"):
        if field not in inner:
            raise UtaError(f"decrypted payload missing field: {field}")

    if inner["kind"] != "launch":
        raise UtaError(f"unexpected payload kind: {inner['kind']!r}")

    if not isinstance(inner["app_id"], str) or inner["app_id"] != expected_app_id:
        raise UtaAppMismatchError(
            "payload app_id does not match configured UTA_APP_ID"
        )

    try:
        exp = int(inner["exp"])
        iat = int(inner["iat"])
    except (TypeError, ValueError):
        raise UtaError("payload iat/exp are not integers")

    if int(time.time()) > exp + clock_skew:
        raise UtaPayloadExpiredError("launch payload has expired")

    user_key = inner["user_key"]
    if not isinstance(user_key, str) or not user_key:
        raise UtaError("payload user_key must be a non-empty string")

    version_hint = inner.get("version_hint")
    if version_hint is not None and not isinstance(version_hint, str):
        raise UtaError("payload version_hint must be a string when present")

    return UtaUser(
        user_key=user_key,
        app_id=inner["app_id"],
        issued_at=iat,
        expires_at=exp,
        version_hint=version_hint,
    )


def get_user(payload: Union[str, Mapping[str, Any]]) -> UtaUser:
    """Verify + decrypt a launch envelope and return a :class:`UtaUser`.

    Args:
        payload: the raw ``uta_payload`` JSON string (as POSTed by the
            marketplace) or an already-parsed mapping.
    """
    cfg = _config.load()
    inner = unpack_payload(
        payload,
        developer_private_key=cfg.private_key,
        market_public_key=cfg.market_public_key,
    )
    return _build_user(inner, cfg.app_id, cfg.clock_skew_seconds)


def get_user_from_request(request: Any) -> UtaUser:
    """Verify the launch envelope on an inbound request.

    Detects Django (``request.POST``), Flask (``request.form``), and
    Starlette/FastAPI (async ``request.form()`` — use
    :func:`get_user_from_request_async` for those).
    """
    payload = _extract_payload_from_request(request)
    return get_user(payload)


async def get_user_from_request_async(request: Any) -> UtaUser:
    """Async variant for Starlette/FastAPI."""
    # Try sync path first.
    post = getattr(request, "POST", None)
    if post is not None:
        val = post.get("uta_payload")
        if val is not None:
            return get_user(val)

    form = getattr(request, "form", None)
    if form is None:
        raise UtaError("request has no POST/form interface")
    if callable(form):
        result = form()
        if inspect.isawaitable(result):
            result = await result
    else:
        result = form
    val = result.get("uta_payload")
    if val is None:
        raise UtaError("could not find 'uta_payload' in request")
    return get_user(val)


# ──────────────────────────────────────────────────────────────────────
# get_version
# ──────────────────────────────────────────────────────────────────────

def _pss() -> padding.PSS:
    return padding.PSS(
        mgf=padding.MGF1(hashes.SHA256()),
        salt_length=padding.PSS.MAX_LENGTH,
    )


def _build_getversion_body(cfg: "_config.UtaConfig", user_key: str) -> Dict[str, Any]:
    body = {
        "app_id": cfg.app_id,
        "user_key": user_key,
        "ts": int(time.time()),
        "nonce": secrets.token_hex(16),
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = cfg.private_key.sign(canonical, _pss(), hashes.SHA256())
    body["signature"] = signature.hex()
    return body


def _cache_get(user_key: str) -> Optional[Tuple[Optional[str], int]]:
    with _cache_lock:
        entry = _version_cache.get(user_key)
        if entry is None:
            return None
        version, expires_at = entry
        if int(time.time()) >= expires_at:
            _version_cache.pop(user_key, None)
            return None
        return entry


def _cache_put(user_key: str, version: Optional[str], cache_until: int) -> None:
    with _cache_lock:
        _version_cache[user_key] = (version, int(cache_until))


def clear_version_cache() -> None:
    """Drop all entries from the process-local version cache."""
    with _cache_lock:
        _version_cache.clear()


def _handle_response_status(status: int, body_text: str) -> None:
    if 200 <= status < 300:
        return
    if status == 400:
        raise UtaBadRequestError(f"400 from getversion: {body_text}")
    if status == 401:
        raise UtaSignatureError(f"401 from getversion: {body_text}")
    if status == 403:
        raise UtaSessionRevokedError(f"403 from getversion: {body_text}")
    if status == 404:
        raise UtaUnknownSessionError(f"404 from getversion: {body_text}")
    if 500 <= status < 600:
        raise UtaServerError(f"{status} from getversion: {body_text}")
    raise UtaError(f"unexpected status {status} from getversion: {body_text}")


def _parse_getversion_response(data: Any) -> Tuple[Optional[str], int]:
    if not isinstance(data, dict):
        raise UtaError("getversion response is not a JSON object")
    if "version" not in data:
        raise UtaError("getversion response missing 'version'")
    version = data["version"]
    if version is not None and not isinstance(version, str):
        raise UtaError("getversion response 'version' must be string or null")
    cache_until = data.get("cache_until")
    if not isinstance(cache_until, int):
        # Fall back to cache_seconds + now if provided
        cache_seconds = data.get("cache_seconds")
        if isinstance(cache_seconds, int):
            cache_until = int(time.time()) + cache_seconds
        else:
            cache_until = int(time.time())  # don't cache
    return version, int(cache_until)


def get_version(user_key: str, *, use_cache: bool = True) -> Optional[str]:
    """Fetch the current license tier for ``user_key`` from the marketplace.

    Args:
        user_key: opaque key obtained from a :class:`UtaUser`.
        use_cache: if True (default), honor the server-provided
            ``cache_until`` in a process-local TTL cache.

    Returns:
        The product/version name as a string, or ``None`` if the user
        has no active license.

    Raises:
        UtaBadRequestError, UtaSignatureError, UtaSessionRevokedError,
        UtaUnknownSessionError, UtaServerError, UtaError on transport
        or schema failures.
    """
    if not isinstance(user_key, str) or not user_key:
        raise UtaError("user_key must be a non-empty string")

    cfg = _config.load()

    if use_cache:
        cached = _cache_get(user_key)
        if cached is not None:
            return cached[0]

    body = _build_getversion_body(cfg, user_key)
    url = cfg.api_url + _GETVERSION_PATH

    try:
        response = httpx.post(
            url,
            json=body,
            timeout=cfg.request_timeout_seconds,
            headers={"Content-Type": "application/json"},
            follow_redirects=True,
        )
    except httpx.RequestError as e:
        raise UtaServerError(f"network error calling getversion: {e}")

    _handle_response_status(response.status_code, response.text)

    try:
        data = response.json()
    except ValueError as e:
        raise UtaError(f"getversion response is not valid JSON: {e}")

    version, cache_until = _parse_getversion_response(data)
    if use_cache and cache_until > int(time.time()):
        _cache_put(user_key, version, cache_until)
    return version


async def get_version_async(user_key: str, *, use_cache: bool = True) -> Optional[str]:
    """Async variant of :func:`get_version` (uses ``httpx.AsyncClient``)."""
    if not isinstance(user_key, str) or not user_key:
        raise UtaError("user_key must be a non-empty string")

    cfg = _config.load()

    if use_cache:
        cached = _cache_get(user_key)
        if cached is not None:
            return cached[0]

    body = _build_getversion_body(cfg, user_key)
    url = cfg.api_url + _GETVERSION_PATH

    try:
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds,
            follow_redirects=True,
        ) as client:
            response = await client.post(
                url,
                json=body,
                headers={"Content-Type": "application/json"},
            )
    except httpx.RequestError as e:
        raise UtaServerError(f"network error calling getversion: {e}")

    _handle_response_status(response.status_code, response.text)

    try:
        data = response.json()
    except ValueError as e:
        raise UtaError(f"getversion response is not valid JSON: {e}")

    version, cache_until = _parse_getversion_response(data)
    if use_cache and cache_until > int(time.time()):
        _cache_put(user_key, version, cache_until)
    return version


__all__ = [
    "get_user_from_request",
    "get_user_from_request_async",
    "get_user",
    "get_version",
    "get_version_async",
    "clear_version_cache",
]

