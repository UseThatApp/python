"""Top-level public API for the ``usethatapp`` SDK (v2, OIDC).

usethatapp.com is an OpenID Provider. This SDK is a framework-agnostic
OIDC client: it helps you log a user in via the marketplace, identify them
by a pairwise pseudonymous ``sub`` (no PII), and query their live license
entitlement. It never touches your web framework — you read the callback
params, store ``flow_state`` in your session, and issue redirects yourself.

Login flow::

    from usethatapp import begin_login, complete_login, get_entitlement

    auth_url, flow_state = begin_login()          # save flow_state in session; redirect to auth_url
    # ...browser returns to your redirect_uri with ?code=...&state=...
    session = complete_login(code=code, state=state, flow_state=flow_state)
    ent = get_entitlement(session.access_token)   # Entitlement(entitled=..., version=..., ...)
"""

from __future__ import annotations

from .client import (
    begin_login,
    complete_login,
    get_entitlement,
    get_entitlement_async,
    logout_url,
    refresh,
    userinfo,
)
from .errors import (
    UtaAuthError,
    UtaConfigError,
    UtaDiscoveryError,
    UtaError,
    UtaPermissionError,
    UtaServerError,
    UtaTokenError,
)
from .types import Entitlement, UtaSession

__version__ = "2.0.0"

__all__ = [
    "__version__",
    # login flow
    "begin_login",
    "complete_login",
    "refresh",
    "userinfo",
    "logout_url",
    # entitlement
    "get_entitlement",
    "get_entitlement_async",
    # types
    "UtaSession",
    "Entitlement",
    # errors
    "UtaError",
    "UtaConfigError",
    "UtaDiscoveryError",
    "UtaAuthError",
    "UtaTokenError",
    "UtaPermissionError",
    "UtaServerError",
]
