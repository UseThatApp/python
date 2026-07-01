# usethatapp

Python SDK for [usethatapp.com](https://usethatapp.com). usethatapp.com is
an **OpenID Connect provider**: this SDK logs a user in through the
marketplace, identifies them by a privacy-preserving `sub`, and tells you
their **live license entitlement** for your app.

**Framework-agnostic.** The SDK never touches your web framework — it
takes and returns plain strings and one JSON-able `flow_state` dict. You
wire the three framework-specific bits yourself (read the callback query
params, store `flow_state` in your session, issue the redirect). Works
with Django, Flask, FastAPI, Starlette, Dash, Streamlit, plain WSGI, a
CLI — anything. Runtime deps: `httpx`, `joserfc`.

> **v2.0 is a breaking rewrite.** The v1 launch-envelope / `user_key` /
> `get_version` handoff is replaced by standard OAuth2/OIDC. See
> [CHANGELOG.md](./CHANGELOG.md) and *Migrating from v1* below.

## How it works

1. **Login (redirect).** Start a login with `begin_login()`, send the user
   to usethatapp.com to authenticate, and finish in your callback with
   `complete_login()`. You get a `UtaSession` carrying the user's `sub`
   (a stable, **per-app**, pseudonymous id — no PII) and OAuth tokens.
2. **Entitlement (Bearer query).** Call `get_entitlement(access_token)`
   whenever you need the user's current license. It's always
   authoritative — a canceled license stops being entitled immediately.

`sub` is **pairwise**: stable for a user within *your* app, but different
in every other app, so it can't be correlated across apps. Use it as your
local user key — and key off `sub`, never an email (we never share one).

## Install

```bash
pip install usethatapp
```

Python 3.9+. Runtime deps: `httpx`, `joserfc`. No web framework required.

## Settings

Read from `django.conf.settings` if Django is installed and configured,
otherwise from environment variables.

| Name                          | Required | Purpose                                                        |
|-------------------------------|----------|----------------------------------------------------------------|
| `UTA_CLIENT_ID`               | yes      | Your app's OAuth client id (from the usethatapp.com dashboard).|
| `UTA_REDIRECT_URI`            | yes      | Your registered callback URL.                                  |
| `UTA_CLIENT_SECRET`           | yes*     | Client secret. *Omit for a public (browser/native) PKCE client.|
| `UTA_CLIENT_SECRET_PATH`      | no       | Read the secret from a mounted file instead (Render/k8s/Fly).  |
| `UTA_ISSUER`                  | no       | Defaults to `https://www.usethatapp.com/o`.                    |
| `UTA_API_URL`                 | no       | Defaults to `https://www.usethatapp.com`.                      |
| `UTA_SCOPES`                  | no       | Defaults to `openid entitlements`.                             |
| `UTA_CLOCK_SKEW_SECONDS`      | no       | ID-token validation leeway. Defaults to `60`.                  |
| `UTA_REQUEST_TIMEOUT_SECONDS` | no       | Defaults to `10`.                                              |

## Public API

```python
from usethatapp import (
    begin_login,        # -> (authorization_url, flow_state)
    complete_login,     # (code=, state=, flow_state=) -> UtaSession
    get_entitlement,    # (access_token) -> Entitlement
    get_entitlement_async,
    refresh,            # (refresh_token) -> UtaSession
    userinfo,           # (access_token) -> {"sub": ...}
    logout_url,         # (id_token=, post_logout_redirect_uri=) -> str
    UtaSession,         # sub, access_token, refresh_token, id_token, expires_at, ...
    Entitlement,        # entitled, version, product_id, status, is_free, period_end
    # errors:
    UtaError, UtaConfigError, UtaDiscoveryError, UtaAuthError,
    UtaTokenError, UtaPermissionError, UtaServerError,
)
```

## Quickstart — any framework

```python
from usethatapp import begin_login, complete_login, get_entitlement

# 1) Start login — however your framework spells "redirect":
auth_url, flow_state = begin_login()
save_to_session("uta_flow", flow_state)        # JSON-able dict
return redirect(auth_url)

# 2) In your callback (reads ?code=...&state=... off the request).
#    On cancel/deny the provider sends ?error=... and no code — handle it first:
if read_query("error"):
    return redirect("/")   # login was canceled
session = complete_login(
    code=read_query("code"),
    state=read_query("state"),
    flow_state=load_from_session("uta_flow"),
)
save_to_session("uta_sub", session.sub)
save_to_session("uta_access_token", session.access_token)

# 3) Anywhere you gate features:
ent = get_entitlement(load_from_session("uta_access_token"))
if ent.entitled and ent.product_id == "...":
    ...
```

Runnable per-framework demos live under [`examples/`](./examples/). They
are documentation only — nothing framework-specific ships in the package.

## Error mapping

`get_entitlement` maps status codes to typed exceptions:

| Status | Exception            | Meaning                                       |
|--------|----------------------|-----------------------------------------------|
| 401    | `UtaTokenError`      | Access token invalid/expired — re-auth/refresh.|
| 403    | `UtaPermissionError` | Token lacks the `entitlements` scope.         |
| 400    | `UtaError`           | Client not linked to an app (misconfig).      |
| 5xx    | `UtaServerError`     | Retriable with backoff.                       |

All inherit from `UtaError` — catch that for a single `except` clause.

## Signing out

Sign-out is RP-initiated: redirect the user to `logout_url(id_token=…)`. Both
outcomes — they confirm, or they choose "Stay signed in" — return to your
`post_logout_redirect_uri`, so you **can't** tell which happened from the
redirect alone.

So **don't clear your session when you start logout.** Reconcile on return
using the token instead: a confirmed logout revokes it, so your next
`get_entitlement()` raises `UtaTokenError` (401) — drop the token then. If they
stayed signed in, the token is still valid and they keep their session.
Clearing eagerly logs the user out of your app even when they chose to stay.

## Migrating from v1

| v1                                      | v2                                              |
|-----------------------------------------|-------------------------------------------------|
| `get_user(payload)` (decrypt envelope)  | `begin_login()` + `complete_login()` (OIDC)     |
| `UtaUser.user_key`                       | `UtaSession.sub` (pairwise, stable per app)     |
| `get_version(user_key) -> str`           | `get_entitlement(access_token) -> Entitlement`  |
| RSA keys (`UTA_PRIVATE_KEY`, market key) | OAuth client (`UTA_CLIENT_ID`/`UTA_CLIENT_SECRET`)|
| `UTA_APP_ID`                             | (gone — the client id identifies your app)      |
| `uta_launch_view` Django decorator       | (gone — wire your own callback view)            |

Register an OAuth client and redirect URI in your usethatapp.com
developer dashboard to get `UTA_CLIENT_ID` / `UTA_CLIENT_SECRET`.

## License

MIT — see [LICENSE](./LICENSE).
