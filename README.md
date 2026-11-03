# usethatapp

Python SDK for [UseThatApp](https://www.usethatapp.com), the merchant of
record for web apps. You put Buy buttons on your own website; UseThatApp
runs checkout, charges the card, collects and remits tax, handles refunds,
and pays you through Stripe. This SDK lets your server show live prices,
build checkout links, and check what each customer bought.

- Docs: <https://docs.usethatapp.com>
- AI agents: read <https://docs.usethatapp.com/llms-full.txt> (the whole
  site as one Markdown file) and follow its "Rules for AI agents".

## Install

```bash
pip install usethatapp
```

Python 3.9+. Runtime dependencies: `httpx`, `joserfc`. The SDK is
**server-side only**: it holds your client secret, so never run it in a
browser or ship it inside a desktop app. It never touches your web
framework — it takes and returns plain values, and you wire it into your
routes.

## Configure

Settings come from `django.conf.settings` when Django is configured,
otherwise from environment variables. `configure(...)` overrides either in
code.

| Variable | Needed for |
|---|---|
| `UTA_CLIENT_ID` | Everything except `purchase_url` |
| `UTA_CLIENT_SECRET` (or `UTA_CLIENT_SECRET_PATH` for a mounted file) | License keys, Hosted sign-in |
| `UTA_REDIRECT_URI` | Hosted sign-in only |
| `UTA_SCOPES`, `UTA_API_URL`, `UTA_ISSUER`, `UTA_REQUEST_TIMEOUT_SECONDS`, `UTA_CLOCK_SKEW_SECONDS` | Optional; defaults point at production |

The client id and secret are on your app's *Manage → Integration* page.
The secret is shown once; keep it in your host's secret store.

## Verify purchases with license keys (the default)

Each purchase creates one license key. When checkout finishes, the buyer
returns to your buy link's `next` URL with `?uta_order=…` appended. Your
server exchanges that once for the key, stores it on the user signed in to
*your* app, and validates it wherever you gate a paid feature. Your login
stays yours.

```python
from usethatapp import UtaOrderProcessingError, get_order, validate_license_key

# Return route, e.g. /thanks?uta_order=...
try:
    order = get_order(request.args["uta_order"])
except UtaOrderProcessingError:
    ...  # paid, key not stored yet: show "finishing up" and retry in a second or two
current_user.license_key = order.license_key
current_user.license_id = order.license_id

# Any gate:
state = validate_license_key(current_user.license_key)
if state.entitled and state.product_public_id == "prod_<your-pro-id>":
    ...  # paid feature
```

- Gate on `entitled` and `product_public_id` (the plan's `prod_…` id;
  `product_id` holds the same value). Never on the plan's display name.
- A cancellation keeps `entitled=True` until `period_end`; the buyer paid
  for that period. Cache the answer for a session or up to a day, never past
  `period_end`.
- A buyer who already holds a plan is sent back to `next` with no
  `uta_order`; treat its absence as nothing to link.
- A canceled key returns `entitled=False`; it does not raise.
  `UtaNotFoundError` means the string was never a key for your app.
- A lost key is always visible on the buyer's manage page. Rotate only a
  leaked one: `regenerate_license_key(license_id)` returns the new key once
  and kills the old one.

Walkthrough, statuses and edge cases: <https://docs.usethatapp.com/license-keys>.

## Show prices and link to checkout

```python
from usethatapp import get_prices, manage_url, purchase_url

for price in get_prices().prices:          # anonymous; needs only UTA_CLIENT_ID
    show_plan(price.product_name, price.amount, price.currency,
              price.frequency, price.buy_url)

purchase_url("prc_...", next="https://yourapp.example/thanks")   # no network call
manage_url(next="https://yourapp.example/account")              # buyer's subscription page
```

Never hardcode prices: render them from `get_prices()` and use each
price's `buy_url`. `amount` is a decimal string (`"10.00"`). `next` must be
HTTPS on your app's registered domain (loopback hosts such as `localhost`
are accepted for local testing). Until the seller is verified, the app is
published and the product is active, a buy link shows the buyer a "not
available" page instead of checkout; it answers 404 only for an unknown
price id or an app whose sales UseThatApp has suspended. Details:
<https://docs.usethatapp.com/sell>.

## Hosted sign-in (optional add-on)

Only if your app has no accounts of its own: UseThatApp runs login over
OpenID Connect, and `get_entitlement` reports what the signed-in user
bought. The entitlement call needs the Hosted sign-in add-on, switched on
in the dashboard.

```python
from usethatapp import begin_login, complete_login, get_entitlement

auth_url, flow_state = begin_login()          # /login: keep flow_state in the session
s = complete_login(code=..., state=..., flow_state=flow_state)   # /callback
ent = get_entitlement(s.access_token)         # gate on ent.entitled + ent.product_public_id
```

Users are identified by `s.sub`, a pairwise pseudonymous id with no email or
name. Setup, sign-out and stack notes: <https://docs.usethatapp.com/hosted-sign-in>.

## Errors

Every exception subclasses `UtaError`.

| Exception | When |
|---|---|
| `UtaConfigError` | Missing settings, or the client id/secret was rejected |
| `UtaNotFoundError` (`.code`) | A key, order or license id never issued for your app |
| `UtaOrderProcessingError` | Order paid, key not stored yet: retry shortly |
| `UtaLicenseCanceledError` | Rotating a key whose license has ended |
| `UtaServerError` (`.retry_after`) | Rate limited (429) or a server error: back off and retry |
| `UtaTokenError`, `UtaPermissionError`, `UtaServiceNotEnabledError`, `UtaAuthError`, `UtaDiscoveryError` | Hosted sign-in only |

Full table: <https://docs.usethatapp.com/rest-api#errors>.

## API

| Function | Returns |
|---|---|
| `get_order(ref)` / `validate_license_key(key)` / `regenerate_license_key(license_id)` | `LicenseState` |
| `get_prices()` / `get_prices_async()` | `AppPrices` (with `Price` entries) |
| `get_app_info()` / `get_app_info_async()` | `AppInfo` |
| `purchase_url(price_id, *, next=, ref=, email=)` / `manage_url(*, next=)` | `str` (no network) |
| `begin_login()` / `complete_login(code=, state=, flow_state=)` / `refresh(refresh_token)` | `(url, flow_state)` / `UtaSession` |
| `get_entitlement(access_token)` / `get_entitlement_async(...)` | `Entitlement` |
| `userinfo(access_token)` / `logout_url(id_token=, post_logout_redirect_uri=)` | `{"sub": …}` / `str` |
| `configure(**settings)` / `load_config()` / `reset_config()` | Configuration |

Every call is plain HTTPS underneath, documented at
<https://docs.usethatapp.com/rest-api>.

## Examples

[`examples/`](./examples/) holds runnable apps: `license_keys` (Flask,
the default integration) and Hosted sign-in apps for Flask, Django and
FastAPI.

## Changelog and license

[CHANGELOG.md](./CHANGELOG.md), including how to migrate from 1.x. MIT —
see [LICENSE](./LICENSE).
