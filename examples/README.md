# Examples

Runnable apps showing where the SDK's calls go. They are documentation
only: the package ships no framework code, and these apps keep users in
memory or in the session to stay short.

| Folder | Framework | Shows |
|---|---|---|
| `license_keys/` | Flask | **The default integration.** Your own login, a buy link, the return route that exchanges `uta_order` for the license key, and a gate that validates it. |
| `flask_min/` | Flask | Hosted sign-in add-on: login, callback, entitlement, sign-out. |
| `django_min/` | Django | The same, in Django. |
| `fastapi_min/` | FastAPI | The same, async via `get_entitlement_async`. |

Every app reads its settings from the environment:

```bash
export UTA_CLIENT_ID=...       # Manage app → Integration
export UTA_CLIENT_SECRET=...   # server-side only; never optional
# Hosted sign-in apps also need:
export UTA_REDIRECT_URI=http://localhost:5000/callback
```

Each app's docstring has its run command. Integration guide:
<https://docs.usethatapp.com>.
