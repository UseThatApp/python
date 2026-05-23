# usethatapp

Python SDK for [usethatapp.com](https://usethatapp.com). Verifies the
encrypted+signed *launch envelope* the marketplace POSTs to your app
and lets you pull the user's current license tier on demand.

**Framework-agnostic.** Use with Django, Flask, FastAPI, Starlette,
Dash, Streamlit, Pyramid, Bottle, AIOHTTP, plain WSGI, or a CLI. The
only runtime dependencies are `cryptography` and `httpx`. A Django
helper is shipped, but only imported when Django is installed.

> **v1.0 is a breaking rewrite.** The old browser-side
> `usethatapp.js` / `requestAccessLevel()` / iframe handshake has been
> removed. See [CHANGELOG.md](./CHANGELOG.md) for migration notes.

## How it works

usethatapp.com uses a two-phase, license-centric handoff:

1. **Launch (one-way push).** When a user clicks *Launch app* on
   usethatapp.com, the marketplace POSTs an encrypted+signed envelope
   to your app's URL. The envelope carries an opaque `user_key`. Your
   app verifies + decrypts it, persists `user_key` against its own
   session, and renders your UI.
2. **Query (server-to-server pull).** Whenever your app needs the
   user's current license tier, it POSTs a signed request to
   `https://usethatapp.com/licensing/getversion/` with the `user_key`
   and gets back the live product name (or `null`).

## Install

```bash
pip install usethatapp
```

Requires Python 3.9+. Runtime deps: `cryptography`, `httpx`. No web
framework required.

## Settings

The SDK reads from `django.conf.settings` **only if** Django is
installed and configured; otherwise it falls back to environment
variables. Non-Django users just `export` these:

| Name                          | Required | Purpose                                                                                   |
|-------------------------------|----------|-------------------------------------------------------------------------------------------|
| `UTA_APP_ID`                  | yes      | Your app's UUID on usethatapp.com.                                                        |
| `UTA_PRIVATE_KEY`             | yes†     | Your RSA-2048 private key (PEM string or `RSAPrivateKey` object).                         |
| `UTA_PRIVATE_KEY_PATH`        | yes†     | Filesystem path to a PEM file containing the private key. †Set this *or* `UTA_PRIVATE_KEY`.|
| `UTA_MARKET_PUBLIC_KEY`       | yes*     | Marketplace public key (PEM string or `RSAPublicKey`). *A production default is bundled.  |
| `UTA_MARKET_PUBLIC_KEY_PATH`  | no       | Filesystem path to a PEM file containing the marketplace public key (alternative to `UTA_MARKET_PUBLIC_KEY`). |
| `UTA_API_URL`                 | no       | Defaults to `https://usethatapp.com`.                                                     |
| `UTA_CLOCK_SKEW_SECONDS`      | no       | Defaults to `60`.                                                                         |
| `UTA_REQUEST_TIMEOUT_SECONDS` | no       | Defaults to `10`.                                                                         |

The `*_PATH` variants are intended for hosting providers that mount
secret files into the container (Render Secret Files, Fly.io volumes,
Kubernetes secret volumes, GCP Secret Manager volume mounts, etc.).
The SDK reads the file at boot. If both the direct setting and the
path setting are provided for the same key, the direct value wins.

## Public API

Three functions cover every integration:

```python
from usethatapp import (
    get_user,                       # framework-agnostic: takes the raw uta_payload str/dict
    get_user_from_request,          # auto-detects Django / Flask / Werkzeug requests
    get_user_from_request_async,    # for Starlette / FastAPI (await)
    get_version,                    # signed server-to-server license-tier lookup
    get_version_async,              # async variant
    UtaUser,                        # frozen dataclass: user_key, app_id, iat, exp, version_hint
    # typed errors:
    UtaError, UtaSignatureError, UtaPayloadExpiredError,
    UtaAppMismatchError, UtaBadRequestError, UtaSessionRevokedError,
    UtaUnknownSessionError, UtaServerError, UtaConfigError,
    # Django-only (imported lazily — present only if Django is installed):
    uta_launch_view,
)
```

`UtaUser` carries only the opaque `user_key` — no PII. Persist it
against your own session; pass it to `get_version` whenever you need
the live license tier.

## Quickstart — any framework

```python
from usethatapp import get_user, get_version, UtaError

# In your POST handler — however your framework spells it:
raw_payload = read_form_field("uta_payload")  # str
try:
    uta_user = get_user(raw_payload)
except UtaError as e:
    return bad_request(str(e))

save_to_session("uta_user_key", uta_user.user_key)

# Later, anywhere in your app:
version = get_version(load_from_session("uta_user_key"))  # str | None
```

## Framework examples

Runnable single-file examples for each major framework live under
[`examples/`](./examples/):

- [`examples/django_min/`](./examples/django_min/) — `@uta_launch_view`
- [`examples/flask_min/`](./examples/flask_min/) — `get_user_from_request(request)`
- [`examples/fastapi_min/`](./examples/fastapi_min/) — `await get_user_from_request_async(request)`
- [`examples/dash_min/`](./examples/dash_min/) — Flask route on Dash's underlying server
- [`examples/streamlit_min/`](./examples/streamlit_min/) — sidecar pattern + `get_user`

> `uta_user.version_hint` is **not** the source of truth. Use it only
> for first paint. The authoritative value comes from
> `get_version(user_key)`.

## Error mapping

`get_version` maps server status codes to typed exceptions:

| Status | Exception                | Meaning                                |
|--------|--------------------------|----------------------------------------|
| 400    | `UtaBadRequestError`     | Bad JSON / ts outside window / replay. |
| 401    | `UtaSignatureError`      | Signature verification failed.         |
| 403    | `UtaSessionRevokedError` | Treat as "user logged out".            |
| 404    | `UtaUnknownSessionError` | Unknown `user_key` or `app_id`.        |
| 5xx    | `UtaServerError`         | Retriable with backoff.                |

All inherit from `UtaError` — catch that for a single `except` clause.

## License

MIT — see [LICENSE](./LICENSE).

