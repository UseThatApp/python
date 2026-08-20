"""Framework-agnostic OIDC client functions.

The whole public surface takes and returns primitives (strings + a
JSON-able ``flow_state`` dict), so the SDK never touches your framework.
You wire three things yourself: read ``code``/``state`` off the callback
request, store/load ``flow_state`` in your session, and issue the
redirect. See ``examples/`` for ~3-line patterns per framework.

Typical flow::

    auth_url, flow_state = begin_login()      # stash flow_state in session, redirect to auth_url
    session = complete_login(code=code, state=state, flow_state=flow_state)
    ent = get_entitlement(session.access_token)
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Any, Dict, Mapping, Optional, Tuple, cast
from urllib.parse import quote, urlencode

import httpx
from joserfc import jwt
from joserfc.errors import JoseError

from . import config as _config
from . import discovery as _discovery
from .errors import (
    UtaAuthError,
    UtaError,
    UtaPermissionError,
    UtaServerError,
    UtaServiceNotEnabledError,
    UtaTokenError,
)
from .types import AppInfo, AppPrices, Entitlement, Price, UtaSession

_ENTITLEMENT_PATH = "/licensing/entitlement/"
_PUBLIC_APPS_PATH = "/api/v1/public/apps/"


# ──────────────────────────────────────────────────────────────────────
# Login: begin / complete
# ──────────────────────────────────────────────────────────────────────

def _s256_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def begin_login(
    *,
    scopes: Optional[str] = None,
    redirect_uri: Optional[str] = None,
    prompt: Optional[str] = None,
    extra_params: Optional[Mapping[str, str]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Start an OIDC authorization-code (PKCE) login.

    Returns ``(authorization_url, flow_state)``. Persist ``flow_state`` in
    the user's session, then redirect the browser to ``authorization_url``.
    Pass the same ``flow_state`` back to :func:`complete_login` in your
    callback. ``flow_state`` is a plain JSON-serializable dict.
    """
    cfg = _config.load()
    meta = _discovery.get_metadata(cfg)

    code_verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    redirect = redirect_uri or cfg.redirect_uri

    params: Dict[str, str] = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": redirect,
        "scope": scopes or cfg.scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": _s256_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    if prompt:
        params["prompt"] = prompt
    if extra_params:
        clashes = sorted(set(params) & set(extra_params))
        if clashes:
            raise ValueError(
                "extra_params may not override reserved OAuth parameters "
                f"({', '.join(clashes)}) — the paired complete_login() validates "
                "against the internally generated values in flow_state"
            )
        params.update(extra_params)

    auth_url = meta["authorization_endpoint"] + "?" + urlencode(params)
    flow_state = {
        "state": state,
        "nonce": nonce,
        "code_verifier": code_verifier,
        "redirect_uri": redirect,
    }
    return auth_url, flow_state


def complete_login(
    *,
    code: Optional[str],
    state: Optional[str],
    flow_state: Mapping[str, Any],
) -> UtaSession:
    """Finish login: validate ``state``, exchange ``code``, verify the ID token.

    ``code``/``state`` come from your callback request's query string;
    ``flow_state`` is what :func:`begin_login` returned. Returns a
    :class:`UtaSession` whose ``sub`` is the user's stable per-app id.
    """
    cfg = _config.load()
    if not code:
        raise UtaAuthError("missing authorization code")
    expected = flow_state.get("state")
    if not expected or not secrets.compare_digest(str(state or ""), str(expected)):
        raise UtaAuthError("state mismatch — possible CSRF or a stale login")

    meta = _discovery.get_metadata(cfg)
    token = _token_request(
        cfg,
        meta,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": flow_state.get("redirect_uri") or cfg.redirect_uri,
            "code_verifier": flow_state.get("code_verifier"),
        },
    )

    id_token = token.get("id_token")
    if not id_token:
        raise UtaTokenError("token response did not include an id_token")
    claims = _validate_id_token(cfg, id_token, nonce=flow_state.get("nonce"))
    return _session(token, sub=str(claims["sub"]), claims=dict(claims), id_token=id_token)


# ──────────────────────────────────────────────────────────────────────
# Refresh / userinfo / logout
# ──────────────────────────────────────────────────────────────────────

def refresh(refresh_token: Optional[str]) -> UtaSession:
    """Exchange a refresh token for a fresh :class:`UtaSession`.

    usethatapp.com rotates refresh tokens, so use the returned
    ``refresh_token`` for the next refresh. If the provider omits a new
    ID token, ``sub`` is resolved via the userinfo endpoint.
    """
    cfg = _config.load()
    if not refresh_token:
        raise UtaTokenError("refresh_token is required")
    meta = _discovery.get_metadata(cfg)
    # No ``scope`` param: RFC 6749 §6 then treats the request as asking for
    # the original grant's scope, which may be narrower than cfg.scopes.
    token = _token_request(
        cfg,
        meta,
        {"grant_type": "refresh_token", "refresh_token": refresh_token},
    )
    # Carry the old refresh token forward if rotation didn't return a new one.
    token.setdefault("refresh_token", refresh_token)

    id_token = token.get("id_token")
    if id_token:
        claims = _validate_id_token(cfg, id_token, nonce=None)
        return _session(token, sub=str(claims["sub"]), claims=dict(claims), id_token=id_token)
    info = userinfo(token["access_token"])
    sub = info.get("sub")
    if not sub:
        raise UtaTokenError("userinfo response missing sub")
    return _session(token, sub=str(sub), claims=dict(info), id_token=None)


def userinfo(access_token: str) -> Dict[str, Any]:
    """Fetch the OIDC userinfo claims (``sub`` only — no PII)."""
    cfg = _config.load()
    endpoint: str = _discovery.get_metadata(cfg).get("userinfo_endpoint", "")
    if not endpoint:
        raise UtaError("provider has no userinfo_endpoint")
    try:
        resp = httpx.get(
            endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=cfg.request_timeout_seconds,
            follow_redirects=True,
        )
    except httpx.RequestError as e:
        raise UtaServerError(f"network error calling userinfo: {e}")
    if resp.status_code == 401:
        raise UtaTokenError(f"401 from userinfo: {resp.text}")
    if resp.status_code == 403:
        raise UtaPermissionError(f"403 from userinfo — token lacks required scope: {resp.text}")
    if resp.status_code >= 500:
        raise UtaServerError(f"{resp.status_code} from userinfo: {resp.text}")
    if not (200 <= resp.status_code < 300):
        raise UtaError(f"unexpected status {resp.status_code} from userinfo: {resp.text}")
    try:
        return cast(Dict[str, Any], resp.json())
    except ValueError as e:
        raise UtaError(f"userinfo response is not valid JSON: {e}")


def logout_url(
    *,
    id_token: Optional[str] = None,
    post_logout_redirect_uri: Optional[str] = None,
    state: Optional[str] = None,
) -> str:
    """Build the RP-initiated end-session (logout) URL to redirect to."""
    cfg = _config.load()
    endpoint: str = _discovery.get_metadata(cfg).get("end_session_endpoint", "")
    if not endpoint:
        raise UtaError("provider has no end_session_endpoint")
    params: Dict[str, str] = {}
    if id_token:
        params["id_token_hint"] = id_token
    if post_logout_redirect_uri:
        params["post_logout_redirect_uri"] = post_logout_redirect_uri
        params["client_id"] = cfg.client_id
    if state:
        params["state"] = state
    if not params:
        return endpoint
    sep = "&" if "?" in endpoint else "?"
    return endpoint + sep + urlencode(params)


# ──────────────────────────────────────────────────────────────────────
# Entitlement (the OAuth-era replacement for get_version)
# ──────────────────────────────────────────────────────────────────────

def get_entitlement(access_token: str, *, timeout: Optional[int] = None) -> Entitlement:
    """Query the user's live license state for your app.

    Sends ``Authorization: Bearer <access_token>`` to
    ``/licensing/entitlement/``. Always authoritative — a canceled license
    stops being entitled immediately, regardless of token lifetime.
    """
    cfg = _config.load()
    if not access_token:
        raise UtaTokenError("access_token must be a non-empty string")
    url = cfg.api_url + _ENTITLEMENT_PATH
    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout or cfg.request_timeout_seconds,
            follow_redirects=True,
        )
    except httpx.RequestError as e:
        raise UtaServerError(f"network error calling entitlement: {e}")
    _raise_for_entitlement_status(resp.status_code, resp.text)
    return _parse_entitlement(_json(resp))


async def get_entitlement_async(
    access_token: str, *, timeout: Optional[int] = None
) -> Entitlement:
    """Async variant of :func:`get_entitlement`."""
    cfg = _config.load()
    if not access_token:
        raise UtaTokenError("access_token must be a non-empty string")
    url = cfg.api_url + _ENTITLEMENT_PATH
    try:
        async with httpx.AsyncClient(
            timeout=timeout or cfg.request_timeout_seconds, follow_redirects=True
        ) as client:
            resp = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )
    except httpx.RequestError as e:
        raise UtaServerError(f"network error calling entitlement: {e}")
    _raise_for_entitlement_status(resp.status_code, resp.text)
    return _parse_entitlement(_json(resp))


# ──────────────────────────────────────────────────────────────────────
# Purchase links & public pricing (selling from your own website)
# ──────────────────────────────────────────────────────────────────────

def purchase_url(
    price_id: str,
    *,
    next: Optional[str] = None,
    ref: Optional[str] = None,
    email: Optional[str] = None,
) -> str:
    """Build the hosted purchase (checkout) URL for a price. No network.

    ``price_id`` is the opaque public price identifier (``prc_…``) — get
    it from :func:`get_prices` (each :class:`~usethatapp.Price` carries a
    ``public_id`` and a ready-made ``buy_url``).

    ``next`` is where the buyer lands after a completed purchase. It must
    be an HTTPS URL on your app's registered domain — this is validated
    server-side, and an invalid value shows the buyer a "misconfigured
    link" page. When omitted, the buyer is returned to your app's
    registered Login URL. ``ref`` is an affiliate code. ``email`` prefills
    the buyer's email on the checkout page.

    Raises:
        ValueError: if ``price_id`` is empty or whitespace.
    """
    if not price_id or not price_id.strip():
        raise ValueError("price_id must be a non-empty string")
    url = _config.resolve_api_url() + f"/buy/{quote(price_id.strip(), safe='')}/"
    params: Dict[str, str] = {}
    if next is not None:
        params["next"] = next
    if ref is not None:
        params["ref"] = ref
    if email is not None:
        params["email"] = email
    if not params:
        return url
    return url + "?" + urlencode(params)


def manage_url(*, next: Optional[str] = None) -> str:
    """Build the buyer's subscription-management page URL for this app. No network.

    The page is scoped to this app (via ``UTA_CLIENT_ID``): the buyer can
    review, update, or cancel their purchase there. ``next`` becomes the
    page's "Back to app" link and gets the same server-side domain
    validation as purchase links (HTTPS, your app's registered domain).

    Raises:
        UtaConfigError: if ``UTA_CLIENT_ID`` is not configured.
    """
    url = _config.resolve_api_url() + f"/manage/{_config.resolve_client_id()}/"
    if next is None:
        return url
    return url + "?" + urlencode({"next": next})


def get_app_info(*, timeout: Optional[float] = None) -> AppInfo:
    """Fetch your app's public listing details. Anonymous — no auth needed.

    Sends a plain GET to ``/api/v1/public/apps/{client_id}/``, so it works
    anywhere — including a marketing site that never logs anyone in.
    """
    url = _public_app_url()
    try:
        resp = httpx.get(
            url,
            timeout=_public_timeout(timeout),
            follow_redirects=True,
        )
    except httpx.RequestError as e:
        raise UtaServerError(f"network error calling app info: {e}")
    _raise_for_public_api_status(resp.status_code, resp.text, endpoint="app info")
    return _parse_app_info(_json(resp))


async def get_app_info_async(*, timeout: Optional[float] = None) -> AppInfo:
    """Async variant of :func:`get_app_info`."""
    url = _public_app_url()
    try:
        async with httpx.AsyncClient(
            timeout=_public_timeout(timeout), follow_redirects=True
        ) as client:
            resp = await client.get(url)
    except httpx.RequestError as e:
        raise UtaServerError(f"network error calling app info: {e}")
    _raise_for_public_api_status(resp.status_code, resp.text, endpoint="app info")
    return _parse_app_info(_json(resp))


def get_prices(*, timeout: Optional[float] = None) -> AppPrices:
    """Fetch your app's live public price list. Anonymous — no auth needed.

    Render your pricing UI from this instead of hardcoding amounts —
    sellers can change prices at any time. Each :class:`~usethatapp.Price`
    carries a ready-made hosted checkout ``buy_url`` and the opaque
    ``product_id`` to gate on — compare it against
    :attr:`Entitlement.product_public_id` (``Entitlement.product_id``
    still carries the legacy UUID until the platform's identifier
    cutover).
    """
    url = _public_app_url() + "prices/"
    try:
        resp = httpx.get(
            url,
            timeout=_public_timeout(timeout),
            follow_redirects=True,
        )
    except httpx.RequestError as e:
        raise UtaServerError(f"network error calling prices: {e}")
    _raise_for_public_api_status(resp.status_code, resp.text, endpoint="prices")
    return _parse_app_prices(_json(resp))


async def get_prices_async(*, timeout: Optional[float] = None) -> AppPrices:
    """Async variant of :func:`get_prices`."""
    url = _public_app_url() + "prices/"
    try:
        async with httpx.AsyncClient(
            timeout=_public_timeout(timeout), follow_redirects=True
        ) as client:
            resp = await client.get(url)
    except httpx.RequestError as e:
        raise UtaServerError(f"network error calling prices: {e}")
    _raise_for_public_api_status(resp.status_code, resp.text, endpoint="prices")
    return _parse_app_prices(_json(resp))


# ──────────────────────────────────────────────────────────────────────
# Internals
# ──────────────────────────────────────────────────────────────────────

def _client_auth(
    cfg: "_config.UtaConfig", data: Dict[str, Any]
) -> Tuple[Optional[Tuple[str, str]], Dict[str, Any]]:
    """Return ``(httpx_auth, body)`` for the token endpoint.

    Confidential clients authenticate with HTTP Basic (client_secret_basic);
    public clients send ``client_id`` in the body and rely on PKCE.
    """
    if cfg.client_secret:
        return (cfg.client_id, cfg.client_secret), data
    data = {**data, "client_id": cfg.client_id}
    return None, data


def _token_request(
    cfg: "_config.UtaConfig", meta: Dict[str, Any], data: Dict[str, Any]
) -> Dict[str, Any]:
    endpoint = meta["token_endpoint"]
    auth, body = _client_auth(cfg, dict(data))
    try:
        resp = httpx.post(
            endpoint,
            data=body,
            auth=auth,
            timeout=cfg.request_timeout_seconds,
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
    except httpx.RequestError as e:
        raise UtaServerError(f"network error calling token endpoint: {e}")
    if resp.status_code >= 500:
        raise UtaServerError(f"{resp.status_code} from token endpoint: {resp.text}")
    payload = _json(resp, error_cls=UtaTokenError)
    if resp.status_code != 200 or "error" in payload:
        err = payload.get("error", f"http_{resp.status_code}")
        desc = payload.get("error_description", "")
        raise UtaTokenError(f"token endpoint error: {err} {desc}".strip())
    if "access_token" not in payload:
        raise UtaTokenError("token response missing access_token")
    return cast(Dict[str, Any], payload)


def _unverified_kid(id_token: str) -> Optional[str]:
    """Read the JOSE header ``kid`` without verifying the signature."""
    try:
        header_b64 = id_token.split(".")[0]
        padded = header_b64 + "=" * (-len(header_b64) % 4)
        header = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return None
    kid = header.get("kid") if isinstance(header, dict) else None
    return kid if isinstance(kid, str) else None


def _decode_id_token(cfg: "_config.UtaConfig", id_token: str) -> Any:
    """Decode + RS256 signature-verify, refetching JWKS once on key rotation."""
    jwks = _discovery.get_jwks(cfg)
    try:
        return jwt.decode(id_token, jwks, algorithms=["RS256"])
    except JoseError:
        # Refetch only when the token references a key we don't have cached
        # (rotation). Any other failure is final — a refetch can't fix it,
        # and would let every bad token trigger a network round-trip.
        kid = _unverified_kid(id_token)
        if kid is None or any(getattr(k, "kid", None) == kid for k in jwks.keys):
            raise
        return jwt.decode(
            id_token, _discovery.get_jwks(cfg, force=True), algorithms=["RS256"]
        )


def _validate_id_token(
    cfg: "_config.UtaConfig", id_token: str, *, nonce: Optional[str]
) -> Dict[str, Any]:
    meta = _discovery.get_metadata(cfg)
    registry = jwt.JWTClaimsRegistry(
        leeway=cfg.clock_skew_seconds,
        iss={"essential": True, "value": meta["issuer"]},
        aud={"essential": True, "value": cfg.client_id},
        exp={"essential": True},
    )
    try:
        token = _decode_id_token(cfg, id_token)
        registry.validate(token.claims)
    except JoseError as e:
        raise UtaTokenError(f"ID token validation failed: {e}")
    claims: Dict[str, Any] = token.claims
    if "sub" not in claims:
        raise UtaTokenError("ID token missing sub")
    if nonce is not None and claims.get("nonce") != nonce:
        raise UtaTokenError("ID token nonce mismatch")
    return claims


def _session(
    token: Mapping[str, Any],
    *,
    sub: str,
    claims: Dict[str, Any],
    id_token: Optional[str],
) -> UtaSession:
    expires_in = int(token.get("expires_in", 0) or 0)
    return UtaSession(
        sub=sub,
        access_token=token["access_token"],
        expires_at=int(time.time()) + expires_in,
        refresh_token=token.get("refresh_token"),
        id_token=id_token,
        scope=token.get("scope", "") or "",
        token_type=token.get("token_type", "Bearer") or "Bearer",
        claims=claims,
    )


def _raise_for_entitlement_status(status: int, body_text: str) -> None:
    if 200 <= status < 300:
        return
    if status == 400:
        raise UtaError(f"400 from entitlement (client not linked to an app?): {body_text}")
    if status == 401:
        raise UtaTokenError(f"401 from entitlement — access token invalid/expired: {body_text}")
    if status == 403:
        # Two distinct 403s (see the server's EntitlementView contract):
        # insufficient_scope (fix the requested scopes) vs
        # service_not_enabled (the developer must enable the add-on —
        # nothing in this process will fix it).
        if _error_code(body_text) == "service_not_enabled":
            raise UtaServiceNotEnabledError(
                "403 from entitlement — the entitlement service is not "
                "enabled for this app. Enable the Auth & Entitlement "
                "add-on on the app's manage page at usethatapp.com "
                f"(Integration panel): {body_text}"
            )
        raise UtaPermissionError(f"403 from entitlement — missing 'entitlements' scope: {body_text}")
    if 500 <= status < 600:
        raise UtaServerError(f"{status} from entitlement: {body_text}")
    raise UtaError(f"unexpected status {status} from entitlement: {body_text}")


def _error_code(body_text: str) -> str:
    """The ``error`` field of a JSON error body, or "" when the body is
    not JSON / not a mapping / has no string error code."""
    try:
        data = json.loads(body_text)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    code = data.get("error")
    return code if isinstance(code, str) else ""


def _parse_entitlement(data: Mapping[str, Any]) -> Entitlement:
    if not isinstance(data, Mapping):
        raise UtaError("entitlement response is not a JSON object")
    return Entitlement(
        entitled=bool(data.get("entitled", False)),
        version=data.get("version"),
        product_id=data.get("product_id"),
        status=str(data.get("status", "none")),
        is_free=bool(data.get("is_free", False)),
        period_end=data.get("period_end"),
        product_public_id=data.get("product_public_id"),
        raw=dict(data),
    )


def _public_app_url() -> str:
    return (
        _config.resolve_api_url()
        + _PUBLIC_APPS_PATH
        + _config.resolve_client_id()
        + "/"
    )


def _public_timeout(timeout: Optional[float]) -> float:
    return timeout if timeout is not None else float(
        _config.resolve_request_timeout_seconds()
    )


def _raise_for_public_api_status(status: int, body_text: str, *, endpoint: str) -> None:
    if 200 <= status < 300:
        return
    if status == 404:
        raise UtaError(
            f"404 from {endpoint} — the app is unknown, unpublished, or "
            f"external sales is not enabled for it: {body_text}"
        )
    if status == 429:
        raise UtaServerError(
            f"429 from {endpoint} — rate limited (120 requests/minute per IP); "
            f"retry with backoff: {body_text}"
        )
    if 500 <= status < 600:
        raise UtaServerError(f"{status} from {endpoint}: {body_text}")
    raise UtaError(f"unexpected status {status} from {endpoint}: {body_text}")


def _parse_app_info(data: Mapping[str, Any]) -> AppInfo:
    if not isinstance(data, Mapping):
        raise UtaError("app info response is not a JSON object")
    return AppInfo(
        client_id=str(data.get("client_id", "")),
        name=str(data.get("name", "")),
        tagline=str(data.get("tagline", "")),
        listing_mode=str(data.get("listing_mode", "")),
        url=str(data.get("url", "")),
        marketplace_url=str(data.get("marketplace_url", "")),
        raw=dict(data),
    )


def _parse_price(data: Mapping[str, Any]) -> Price:
    if not isinstance(data, Mapping):
        raise UtaError("price entry is not a JSON object")
    frequency = data.get("frequency")
    return Price(
        public_id=str(data.get("public_id", "")),
        product_id=str(data.get("product_id", "")),
        product_name=str(data.get("product_name", "")),
        amount=str(data.get("amount", "")),
        currency=str(data.get("currency", "")),
        is_recurring=bool(data.get("is_recurring", False)),
        frequency=None if frequency is None else str(frequency),
        buy_url=str(data.get("buy_url", "")),
    )


def _parse_app_prices(data: Mapping[str, Any]) -> AppPrices:
    if not isinstance(data, Mapping):
        raise UtaError("prices response is not a JSON object")
    raw_prices = data.get("prices", [])
    if not isinstance(raw_prices, list):
        raise UtaError("prices response has no 'prices' list")
    return AppPrices(
        client_id=str(data.get("client_id", "")),
        app_name=str(data.get("app_name", "")),
        has_free_tier=bool(data.get("has_free_tier", False)),
        prices=tuple(_parse_price(p) for p in raw_prices),
        raw=dict(data),
    )


def _json(resp: httpx.Response, error_cls: type = UtaError) -> Any:
    try:
        return resp.json()
    except ValueError as e:
        raise error_cls(f"response is not valid JSON ({resp.status_code}): {e}")


__all__ = [
    "begin_login",
    "complete_login",
    "refresh",
    "userinfo",
    "logout_url",
    "get_entitlement",
    "get_entitlement_async",
    "purchase_url",
    "manage_url",
    "get_app_info",
    "get_app_info_async",
    "get_prices",
    "get_prices_async",
]
