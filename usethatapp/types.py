"""Public dataclasses for the UseThatApp SDK (v2, OIDC).

The v2 flow shares **only** a pairwise pseudonymous ``sub`` — no email,
username, or other PII. ``sub`` is stable for a given user *within your
app* but differs across apps, so it is safe to use as your local user key
but cannot be correlated against other apps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


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
    """Legacy UUID product identifier. For gating, prefer
    :attr:`product_public_id` — it matches :attr:`Price.product_id` from the
    pricing API. After the platform's identifier cutover this field carries
    the same opaque ``prod_…`` value as ``product_public_id``."""

    status: str
    """``active``/``trialing``/``one_time_active``/``free``/``none``/…"""

    is_free: bool
    """True when the entitlement comes from the app's free tier."""

    period_end: Optional[str] = None
    """ISO date the current license period ends, or ``None``."""

    raw: Dict[str, Any] = field(default_factory=dict)
    """The full decoded response, for forward-compatibility."""

    # Appended AFTER ``raw`` deliberately: inserting a field ahead of it
    # would silently rebind positional constructor arguments written
    # against 2.0 (``Entitlement(..., period_end, raw_dict)``), landing the
    # raw dict in this field with no error. New fields go on the end.
    product_public_id: Optional[str] = None
    """Opaque public product identifier (``prod_…``) — matches
    :attr:`Price.product_id` from the pricing API. New integrations should
    gate on this field."""


@dataclass(frozen=True)
class AppInfo:
    """Public listing details for an app, from the anonymous apps API.

    Returned by :func:`usethatapp.get_app_info`. The endpoint needs no
    authentication, so this is safe to call from anywhere — including a
    plain marketing site that never logs anyone in.
    """

    client_id: str
    """The app's OAuth client id (same value as ``UTA_CLIENT_ID``)."""

    name: str
    """The app's display name."""

    tagline: str
    """Short marketing tagline set by the seller."""

    listing_mode: str
    """``marketplace`` or ``external`` — where the app is sold."""

    url: str
    """The app's own website URL."""

    marketplace_url: str
    """The app's listing page on usethatapp.com."""

    raw: Dict[str, Any] = field(default_factory=dict)
    """The full decoded response, for forward-compatibility."""


@dataclass(frozen=True)
class Price:
    """One purchasable price for an app, from the anonymous pricing API.

    Render prices from :func:`usethatapp.get_prices` instead of hardcoding
    them — sellers can change prices at any time. ``product_id`` here is
    the opaque ``prod_…`` identifier to gate on: compare it against
    :attr:`Entitlement.product_public_id`.
    """

    public_id: str
    """Opaque public price identifier (``prc_…``); pass to :func:`usethatapp.purchase_url`."""

    product_id: str
    """Opaque product identifier (``prod_…``) — matches
    :attr:`Entitlement.product_public_id` for gating (and
    ``Entitlement.product_id`` after the platform's identifier cutover)."""

    product_name: str
    """The product/plan display name."""

    amount: str
    """Decimal amount as a string (e.g. ``"10.00"``) — kept as ``str`` so
    no float precision is imposed on you. Parse with :class:`decimal.Decimal`."""

    currency: str
    """Lowercase ISO currency code (e.g. ``usd``)."""

    is_recurring: bool
    """True for subscriptions, False for one-time purchases."""

    frequency: Optional[str]
    """Billing interval — ``day``/``week``/``month``/``year`` — or ``None``
    for one-time purchases."""

    buy_url: str
    """Ready-made hosted checkout link for this price (what
    :func:`usethatapp.purchase_url` builds, minus the optional params)."""


@dataclass(frozen=True)
class AppPrices:
    """An app's full public price list, from the anonymous pricing API.

    Returned by :func:`usethatapp.get_prices`.
    """

    client_id: str
    """The app's OAuth client id (same value as ``UTA_CLIENT_ID``)."""

    app_name: str
    """The app's display name."""

    has_free_tier: bool
    """True if the app offers a free tier (no purchase needed to start)."""

    prices: Tuple[Price, ...]
    """Every purchasable price, ready to render as a pricing table."""

    raw: Dict[str, Any] = field(default_factory=dict)
    """The full decoded response, for forward-compatibility."""


__all__ = ["UtaSession", "Entitlement", "AppInfo", "Price", "AppPrices"]
