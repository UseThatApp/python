# Changelog

All notable changes to this project are documented in this file. This project adheres to
[Semantic Versioning](https://semver.org/) and follows a clear, machine- and human-readable
format inspired by "Keep a Changelog".

## [Unreleased]

### Added

- `UtaServiceNotEnabledError` (subclass of `UtaPermissionError`), raised
  when the entitlement endpoint returns `403 service_not_enabled`: the
  app's developer has not enabled the Auth & Entitlement add-on. The
  previous behavior mislabeled this case as a missing `entitlements`
  scope; the new error says the actual fix (enable the add-on on the
  app's manage page). Existing `except UtaPermissionError` blocks catch
  it unchanged.

## [2.1.0] - 2026-08-11

Thin, dependency-free support for selling your app from your own website
— hosted purchase links, the buyer management page, and the public
(anonymous, CORS-enabled) app/pricing APIs — plus fixes to several
identity-integrity and error-contract bugs in the 2.0 OIDC path.

### Added

- `purchase_url(price_id, *, next=, ref=, email=)` — build the hosted
  checkout URL for a public price id (`prc_…`). Pure URL builder, no
  network.
- `manage_url(*, next=)` — build the buyer's subscription-management page
  URL for your app. Pure URL builder, no network.
- `get_app_info()` / `get_app_info_async()` → `AppInfo(client_id, name,
  tagline, listing_mode, url, marketplace_url)`, from the anonymous
  public apps API.
- `get_prices()` / `get_prices_async()` → `AppPrices(client_id, app_name,
  has_free_tier, prices)`, from the anonymous public pricing API —
  render your pricing UI from this instead of hardcoding amounts.
- New frozen dataclasses: `AppInfo`, `Price` (`public_id`, `product_id`,
  `product_name`, `amount` — a decimal string, `currency`, `is_recurring`,
  `frequency`, `buy_url`), and `AppPrices`.
- `Entitlement.product_public_id` — the opaque public product identifier
  (`prod_…`) matching `Price.product_id` from the pricing API. New
  integrations should gate on it; `Entitlement.product_id` currently
  carries a legacy UUID and will converge on the same `prod_…` value.

### Changed

- `refresh()` no longer sends a `scope` parameter. It previously sent the
  full configured `UTA_SCOPES`, which is *broader* than the grant whenever
  a login narrowed it via `begin_login(scopes=…)` — RFC 6749 §6 requires
  the provider to reject that with `invalid_scope`, forcing a needless
  interactive re-login. Omitting it asks for the original grant's scope.
- `begin_login(extra_params=…)` now raises `ValueError` when `extra_params`
  collides with a reserved OAuth parameter (`state`, `nonce`,
  `code_challenge`, `redirect_uri`, …). Such a value previously landed in
  the authorization URL while `flow_state` kept the internally generated
  one, so the paired `complete_login()` always failed with a misleading
  "state mismatch — possible CSRF" error.

### Fixed

- `userinfo()` returned the response body as the user's claims for any
  status other than 401/5xx. A 403 or 400 error body (e.g.
  `{"detail": "insufficient scope"}`) was therefore treated as a valid
  claim set, and `refresh()`'s no-ID-token fallback turned it into a
  `UtaSession` with `sub=""` — collapsing every affected user onto one
  empty-string local key. 403 now raises `UtaPermissionError` and any
  other non-2xx raises `UtaError`.
- `refresh()` likewise accepted a 200 userinfo response with no `sub`,
  again producing `sub=""`. It now raises `UtaTokenError`, matching what
  `complete_login()` already did for the same case.
- ID-token validation refetched the JWKS on *any* signature or decode
  failure, so every malformed or forged token cost a blocking HTTPS
  round-trip, and a network blip during that refetch surfaced
  `UtaDiscoveryError` in place of the real validation error. The refetch
  now happens only when the token references a `kid` that is not cached
  (genuine key rotation).
- `purchase_url()` validated `price_id` with `strip()` but interpolated
  the raw value into the path, so a stray-whitespace or `/?#`-bearing id
  produced a broken checkout link. It is now stripped and percent-encoded.
- `get_prices()` / `get_prices_async()` raised a bare `AttributeError` when
  a price entry was not a JSON object, escaping the documented "catch
  `UtaError`" contract. Malformed entries now raise `UtaError`.
- Gating guidance: the README quickstart and the `Entitlement.product_id`
  docstring still pointed feature gating at `product_id` (a legacy UUID),
  which locks out every paying customer. Both now point at
  `product_public_id`.

## [2.0.0] - 2026-06-21

Breaking rewrite onto standard OAuth2 / OpenID Connect. usethatapp.com is
now an OpenID Provider; the SDK is a framework-agnostic OIDC client. The
v1 launch-envelope push + signed `get_version` pull are gone.

### Removed

- `get_user` / `get_user_from_request` / `get_user_from_request_async` and
  the encrypted launch-envelope handling (`usethatapp.payloads`).
- `get_version` / `get_version_async` and the process-local version cache.
- `uta_launch_view` Django decorator and `usethatapp.django_helpers` — the
  SDK no longer ships any framework-specific code.
- `UtaUser` (and its `user_key` / `version_hint`).
- RSA-key configuration (`UTA_PRIVATE_KEY[_PATH]`,
  `UTA_MARKET_PUBLIC_KEY[_PATH]`) and `UTA_APP_ID`.
- The bundled `cryptography` dependency (now pulled transitively by
  `joserfc`).

### Added

- OIDC login flow:
  - `begin_login()` → `(authorization_url, flow_state)` (authorization
    code + PKCE; `flow_state` is a JSON-able dict you stash in the session).
  - `complete_login(code=, state=, flow_state=)` → `UtaSession`, validating
    `state`, exchanging the code, and verifying the ID token (signature via
    JWKS, `iss`/`aud`/`exp`/`nonce`).
  - `refresh(refresh_token)`, `userinfo(access_token)`, `logout_url(...)`.
- `get_entitlement(access_token)` / `get_entitlement_async(...)` →
  `Entitlement(entitled, version, product_id, status, is_free, period_end)`,
  the Bearer-token replacement for `get_version`.
- `UtaSession` (carries the pairwise pseudonymous `sub` + tokens) and
  `Entitlement` dataclasses.
- New config: `UTA_CLIENT_ID`, `UTA_CLIENT_SECRET[_PATH]`,
  `UTA_REDIRECT_URI`, `UTA_ISSUER`, `UTA_SCOPES`.
- New typed errors: `UtaDiscoveryError`, `UtaAuthError`, `UtaTokenError`,
  `UtaPermissionError` (replacing the v1 envelope/session error set).

### Changed

- Runtime dependencies are now `httpx` + `joserfc`.
- Identity is a pairwise, per-app pseudonymous `sub` — stable within your
  app, uncorrelatable across apps. Key your user records off `sub`.

## [1.0.0] - 2026-05-21

Breaking rewrite for the new usethatapp.com webhook-based handoff. The browser
iframe / `usethatapp.js` model has been retired in favor of a server-to-server
push + pull flow.

### Removed

- `usethatapp.js` integration, `requestAccessLevel()` JS bridge, and all
  iframe / `postMessage` handling.
- `usethatapp.webapps.get_version(envelope, public_key_path, private_key_path)` —
  the old envelope (`type`/`responseTo`/`message{contents,signature}`) is no
  longer accepted.
- `usethatapp.encryption` module (`Keys`, `decrypt_message`, `verify_signature`).
  PEM key loading is now handled internally by `usethatapp.config`.
- `uid` / `username` fields on the returned user object. The v1 envelope carries
  only an opaque `user_key`.

### Added

- New top-level public API:
  - `get_user(payload)` — verify + decrypt the launch envelope POSTed by
    the marketplace. Framework-agnostic; takes the raw `uta_payload`
    string or already-parsed mapping.
  - `get_user_from_request(request)` and `get_user_from_request_async(request)`
    — request-aware helpers that pull `uta_payload` directly out of a
    Django / Flask / Werkzeug / Starlette request and forward to `get_user`.
  - `get_version(user_key)` and `get_version_async(user_key)` — signed
    server-to-server POST to `https://usethatapp.com/licensing/getversion/`,
    returning the current product name or `None`. Honors a process-local TTL
    cache keyed off the server's `cache_until`.
  - `UtaUser` frozen dataclass (`user_key`, `app_id`, `issued_at`,
    `expires_at`, `version_hint`).
  - `uta_launch_view` Django decorator (csrf-exempt, POST-only, injects
    `request.uta_user`).
- Hybrid envelope crypto in `usethatapp.payloads`:
  `RSA-OAEP-SHA256 + AES-256-GCM + RSA-PSS-SHA256`. The PSS signature now
  covers `ek || iv || ct` (not the plaintext).
- Typed exception hierarchy under `UtaError`: `UtaSignatureError`,
  `UtaPayloadExpiredError`, `UtaAppMismatchError`, `UtaBadRequestError`,
  `UtaSessionRevokedError`, `UtaUnknownSessionError`, `UtaServerError`,
  `UtaConfigError`. Every failure mode (local validation + each HTTP status)
  maps to a specific subclass.
- `usethatapp.config.load()` settings resolver reading from
  `django.conf.settings` then `os.environ`. New settings:
  `UTA_APP_ID`, `UTA_PRIVATE_KEY`, `UTA_PRIVATE_KEY_PATH`,
  `UTA_MARKET_PUBLIC_KEY`, `UTA_MARKET_PUBLIC_KEY_PATH`, `UTA_API_URL`,
  `UTA_CLOCK_SKEW_SECONDS`, `UTA_REQUEST_TIMEOUT_SECONDS`. The
  `*_PATH` variants read the PEM from a file at boot (intended for
  hosting providers that mount secret files into the container);
  direct values take precedence when both are set.
- `py.typed` marker — package now ships type information.
- `httpx` runtime dependency (sync + async HTTP).

### Changed

- Minimum Python is now 3.9.
- `cryptography` constraint relaxed to `>=42`.

### Migration

```python
# Before (0.x)
from usethatapp.webapps import get_version
version = get_version(envelope, "pub.pem", "priv.pem")

# After (1.0)
from usethatapp import get_user_from_request, get_version

# In your launch view (Django shown):
user = get_user_from_request(request)            # verifies envelope, returns UtaUser
session["uta_user_key"] = user.user_key

# Later, whenever you need the live tier:
version = get_version(user.user_key)  # str | None
```

## [0.3.0] - 2026-04-10

### Changed

- Breaking change: `get_version` now accepts a full `requestAccessLevel()` envelope instead of
  a flat message dict. The first parameter has been renamed from `message` to `envelope` and
  must contain a `type` field (`"level"`) and a nested `message` dict with `contents` and
  `signature`.
- Error envelopes (`type == "error"`) are now detected and raise a `ValueError` with the
  server's error description.
- Envelope `type` is validated; unexpected types raise a `ValueError`.

## [0.2.0] - 2026-03-29

### Changed

- Breaking change: renamed `get_product` -> `get_version` to better reflect the function's
  purpose and improve clarity of the public API.

## [0.1.0] - 2026-03-19

### Added

- Initial release: introduced `get_product` (now renamed to `get_version`) to retrieve
  licensing or version information from signed/encrypted messages.

---

For more details, including commit-level history, see the project's Git repository.
