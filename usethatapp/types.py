"""Public dataclasses for the UseThatApp SDK (v2, OIDC).

The v2 flow shares **only** a pairwise pseudonymous ``sub`` — no email,
username, or other PII. ``sub`` is stable for a given user *within your
app* but differs across apps, so it is safe to use as your local user key
but cannot be correlated against other apps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class UtaSession:
    """The result of a completed OIDC login.

    Persist ``sub`` as your local user identifier. Persist the tokens
    (against your own server-side session) to call
    :func:`usethatapp.get_entitlement` and to refresh later.
    """

    sub: str
    """Pairwise pseudonymous user id. Stable per-app; use as your user key."""

    access_token: str
    """Bearer token for :func:`usethatapp.get_entitlement`."""

    expires_at: int
    """Unix seconds at which ``access_token`` expires."""

    refresh_token: Optional[str] = None
    """Use with :func:`usethatapp.refresh` to obtain a fresh session."""

    id_token: Optional[str] = None
    """Raw OIDC ID token (JWT). Pass to :func:`usethatapp.logout_url`."""

    scope: str = ""
    """Space-separated granted scopes."""

    token_type: str = "Bearer"

    claims: Dict[str, Any] = field(default_factory=dict)
    """Validated ID-token claims (``sub`` plus standard OIDC claims)."""


@dataclass(frozen=True)
class Entitlement:
    """A user's live license state for your app.

    Always reflects the current license on usethatapp.com, so re-query
    whenever you need an authoritative answer (it is cheap and cacheable
    on your side if you wish).
    """

    entitled: bool
    """True if the user may use the app (an active license or a free tier)."""

    version: Optional[str]
    """Product/plan display name, or ``None`` when not entitled."""

    product_id: Optional[str]
    """Stable product UUID — prefer this over ``version`` for gating logic."""

    status: str
    """``active``/``trialing``/``one_time_active``/``free``/``none``/…"""

    is_free: bool
    """True when the entitlement comes from the app's free tier."""

    period_end: Optional[str] = None
    """ISO date the current license period ends, or ``None``."""

    raw: Dict[str, Any] = field(default_factory=dict)
    """The full decoded response, for forward-compatibility."""


__all__ = ["UtaSession", "Entitlement"]
