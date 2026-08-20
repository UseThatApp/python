"""Exception hierarchy for the UseThatApp SDK (v2, OIDC).

Every error raised out of the public API inherits from :class:`UtaError`.
Catch :class:`UtaError` (or a specific subclass) — never ``Exception``.
"""

from __future__ import annotations


class UtaError(Exception):
    """Base class for every error raised by the UseThatApp SDK."""


class UtaConfigError(UtaError):
    """SDK configuration is missing or invalid."""


class UtaDiscoveryError(UtaError):
    """OIDC discovery document or JWKS could not be fetched/parsed."""


class UtaAuthError(UtaError):
    """The authorization step failed.

    Raised for a ``state`` mismatch, a provider ``error`` response, or a
    user-denied authorization. Treat as "login did not succeed".
    """


class UtaTokenError(UtaError):
    """A token could not be obtained or validated.

    Covers token-endpoint failures (code exchange / refresh) and ID-token
    validation failures (bad signature, issuer, audience, expiry, or
    nonce). Also raised when the entitlement endpoint returns 401 (the
    access token is invalid or expired).
    """


class UtaPermissionError(UtaError):
    """The token is valid but the request is not permitted (403).

    Usually a missing ``entitlements`` scope. When the server says the
    app's developer has not enabled the entitlement service, the more
    specific :class:`UtaServiceNotEnabledError` subclass is raised
    instead — existing ``except UtaPermissionError`` blocks still catch
    it.
    """


class UtaServiceNotEnabledError(UtaPermissionError):
    """The app's developer has not enabled the Auth & Entitlement add-on.

    The token is fine and no retry, refresh, or re-consent will help:
    the entitlement service is switched off for this app. Enable it on
    the app's manage page at usethatapp.com (Integration panel →
    "Turn on entitlement").
    """


class UtaServerError(UtaError):
    """A usethatapp.com endpoint returned 5xx, or the network failed.

    Callers MAY retry with backoff.
    """


__all__ = [
    "UtaError",
    "UtaConfigError",
    "UtaDiscoveryError",
    "UtaAuthError",
    "UtaTokenError",
    "UtaPermissionError",
    "UtaServiceNotEnabledError",
    "UtaServerError",
]
