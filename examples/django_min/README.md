# django_min — minimal UseThatApp Django example

A single-file Django app wiring the OIDC login flow: `/login/` starts it,
`/callback/` finishes it, `/` shows the user's live entitlement, and
`/logout/` does RP-initiated sign-out.

Documentation only — the SDK ships no Django-specific code. This demo runs
locally with `DEBUG=True` and a throwaway session key; don't deploy it.

## Run

```bash
pip install usethatapp django

export UTA_CLIENT_ID=...
export UTA_CLIENT_SECRET=...        # omit for a public/PKCE client
export UTA_REDIRECT_URI=http://localhost:8000/callback/

python app.py runserver
```

Register `http://localhost:8000/callback/` as a redirect URI for your
OAuth client in the usethatapp.com developer dashboard first, or the
provider rejects the login.

## What to look at

| Where | The framework-specific bit |
|-------|----------------------------|
| `login()` | Stash `flow_state` from `begin_login()` in the session, redirect to the returned URL. |
| `callback()` | Read `code`/`state` off `request.GET` (and handle `?error=` on cancel), pass them plus `flow_state` to `complete_login()`. |
| `home()` | Call `get_entitlement(access_token)`; on `UtaTokenError` drop the token and fall back to the logged-out view. |
| `logout()` | Redirect to `logout_url(...)` **without** clearing the session — see the sign-out note in the root [README](../../README.md). |

Identity is `session.sub`, the pairwise pseudonymous user id — stable
within your app, never correlatable across apps, never PII. Key your user
records off it.
