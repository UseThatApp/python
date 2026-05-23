# Examples

`usethatapp` is **framework-agnostic**. The only runtime deps are
`cryptography` and `httpx`; Django is an *optional* extra. Drop the
SDK into Flask, FastAPI, Dash, Streamlit, Pyramid, Bottle, AIOHTTP, a
plain WSGI app, or even a CLI — anywhere you can receive a POST and
make an outbound HTTPS call.

## Which entry point should I use?

| You have…                                | Call this                                       |
|------------------------------------------|-------------------------------------------------|
| A Django `HttpRequest`                   | `get_user_from_request(request)` or `@uta_launch_view`       |
| A Flask `request`                        | `get_user_from_request(request)`                             |
| A Starlette/FastAPI `Request`            | `await get_user_from_request_async(request)`                 |
| The raw `uta_payload` string (any stack) | `get_user(payload)`                |
| Any framework — license tier lookup      | `get_version(user_key)` / `get_version_async`   |

`get_user_from_request(request)` auto-detects Django (`request.POST`), Flask
(`request.form`), and Werkzeug-style callable forms. For async
frameworks, use `get_user_from_request_async`. If your stack is exotic, just pull
the `uta_payload` field out of the body yourself and call
`get_user`.

## Configuration

The SDK reads from `django.conf.settings` **only if** Django is
installed and configured; otherwise it reads `os.environ`. So a
non-Django app just sets:

```bash
export UTA_APP_ID=...
export UTA_PRIVATE_KEY="$(cat dev_priv.pem)"
export UTA_MARKET_PUBLIC_KEY="$(cat market_pub.pem)"
# optional:
export UTA_API_URL=https://usethatapp.com
export UTA_CLOCK_SKEW_SECONDS=60
export UTA_REQUEST_TIMEOUT_SECONDS=10
```

## Examples in this directory

| Folder              | Framework  | Notes                                                                  |
|---------------------|------------|------------------------------------------------------------------------|
| `django_min/`       | Django     | Uses the `@uta_launch_view` decorator.                                 |
| `flask_min/`        | Flask      | Bare `get_user_from_request(request)` + `get_version`.                              |
| `fastapi_min/`      | FastAPI    | Async path: `await get_user_from_request_async(request)` + `await get_version_async`. |
| `dash_min/`         | Dash       | Registers the launch route on Dash's underlying Flask server.          |
| `streamlit_min/`    | Streamlit  | Documents the sidecar pattern; demonstrates `get_user` for local dev. |

Each example is a single file you can `python app.py` (or
`uvicorn app:app`, `streamlit run app.py`) after exporting the three
required env vars.

## Adapting to other frameworks

For any framework not covered here, the recipe is always the same:

```python
from usethatapp import get_user, get_version, UtaError

# 1. In your POST handler — however that's spelled in your framework:
raw_payload = read_form_field("uta_payload")  # str
try:
    uta_user = get_user(raw_payload)
except UtaError as e:
    return bad_request(str(e))

# 2. Persist uta_user.user_key against your session somehow.
save_to_session("uta_user_key", uta_user.user_key)

# 3. Whenever you need the current license tier:
version = get_version(load_from_session("uta_user_key"))  # str | None
```

That's the entire integration surface — three calls.

