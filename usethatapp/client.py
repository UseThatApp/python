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
import secrets
import time
from typing import Any, Dict, Mapping, Optional, Tuple, cast
from urllib.parse import urlencode

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
    UtaTokenError,
)
from .types import Entitlement, UtaSession

_ENTITLEMENT_PATH = "/licensing/entitlement/"


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
    token = _token_request(
        cfg,
        meta,
        {"grant_type": "refresh_token", "refresh_token": refresh_token, "scope": cfg.scopes},
    )
    # Carry the old refresh token forward if rotation didn't return a new one.
    token.setdefault("refresh_token", refresh_token)

    id_token = token.get("id_token")
    if id_token:
        claims = _validate_id_token(cfg, id_token, nonce=None)
        return _session(token, sub=str(claims["sub"]), claims=dict(claims), id_token=id_token)
    info = userinfo(token["access_token"])
    return _session(token, sub=str(info.get("sub", "")), claims=dict(info), id_token=None)


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
    if resp.status_code >= 500:
        raise UtaServerError(f"{resp.status_code} from userinfo: {resp.text}")
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


def _decode_id_token(cfg: "_config.UtaConfig", id_token: str) -> Any:
    """Decode + RS256 signature-verify, refetching JWKS once on key rotation."""
    try:
        return jwt.decode(id_token, _discovery.get_jwks(cfg), algorithms=["RS256"])
    except JoseError:
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
        raise UtaPermissionError(f"403 from entitlement — missing 'entitlements' scope: {body_text}")
    if 500 <= status < 600:
        raise UtaServerError(f"{status} from entitlement: {body_text}")
    raise UtaError(f"unexpected status {status} from entitlement: {body_text}")


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
]
