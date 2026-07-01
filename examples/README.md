# Examples

`usethatapp` is **framework-agnostic** — the package ships no
framework-specific code. These examples are documentation only: they show
the three bits you wire yourself in any stack.

The only runtime deps are `httpx` and `joserfc`. Drop the SDK into Django,
Flask, FastAPI/Starlette, Pyramid, Bottle, AIOHTTP, a plain WSGI app, or a
CLI — anywhere you can read a request and make an outbound HTTPS call.

## The three framework-specific bits

The SDK takes/returns primitives; you provide:

1. **Read callback params** — pull `code` and `state` off the redirect
   request (`request.GET` / `request.args` / `request.query_params`).
2. **Store `flow_state`** — persist the dict from `begin_login()` in your
   session between the redirect and the callback.
3. **Issue redirects** — send the browser to the authorization URL, and to
   `logout_url(...)`.

## Configuration

The SDK reads from `django.conf.settings` if Django is configured,
otherwise `os.environ`:

```bash
export UTA_CLIENT_ID=...
export UTA_CLIENT_SECRET=...        # omit for a public/PKCE client
export UTA_REDIRECT_URI=https://yourapp.example/callback
# optional: UTA_ISSUER, UTA_API_URL, UTA_SCOPES, UTA_CLOCK_SKEW_SECONDS
```

## The flow, in any framework

```python
from usethatapp import begin_login, complete_login, get_entitlement

auth_url, flow_state = begin_login()        # 1. start
save_to_session("uta_flow", flow_state)     # 2. stash
redirect(auth_url)                          # 3. redirect

# ...callback (request has ?code=&state=, or ?error= on cancel/deny)...
if read_query("error"):
    redirect("/")                           # login was canceled
session = complete_login(
    code=read_query("code"),
    state=read_query("state"),
    flow_state=load_from_session("uta_flow"),
)
ent = get_entitlement(session.access_token) # Entitlement(...)
```

## Runnable demos

| Folder           | Framework | Notes                                        |
|------------------|-----------|----------------------------------------------|
| `django_min/`    | Django    | Session-backed login / callback / logout.    |
| `flask_min/`     | Flask     | The same, in Flask.                          |
| `fastapi_min/`   | FastAPI   | Async hot path via `get_entitlement_async`.  |

> Identity is the pairwise pseudonymous `session.sub` — stable for a user
> within your app, never correlatable across apps, and never PII. Key your
> user records off `sub`.
