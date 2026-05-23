# Changelog

All notable changes to this project are documented in this file. This project adheres to
[Semantic Versioning](https://semver.org/) and follows a clear, machine- and human-readable
format inspired by "Keep a Changelog".

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
