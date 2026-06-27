"""Minimal FastAPI app: UseThatApp OIDC login + async entitlement (docs only).

Shows the async hot path: `get_entitlement_async`. The one-time callback
calls the sync `complete_login` (fine for a login round-trip).

Run:
    pip install usethatapp fastapi uvicorn itsdangerous
    export UTA_CLIENT_ID=... UTA_CLIENT_SECRET=... UTA_REDIRECT_URI=http://localhost:8000/callback
    uvicorn app:app
"""
from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from usethatapp import (
    UtaError,
    UtaTokenError,
    begin_login,
    complete_login,
    get_entitlement_async,
    logout_url,
)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET", "dev-only"))


@app.get("/login")
def login(request: Request):
    auth_url, flow_state = begin_login()
    request.session["uta_flow"] = flow_state
    return RedirectResponse(auth_url)


@app.get("/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    # On cancel/deny, OAuth redirects back with ?error=... and no code.
    if error:
        request.session.pop("uta_flow", None)
        return RedirectResponse("/")
    try:
        s = complete_login(
            code=code, state=state, flow_state=request.session.pop("uta_flow", {})
        )
    except UtaError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    request.session["uta_sub"] = s.sub
    request.session["uta_access_token"] = s.access_token
    request.session["uta_id_token"] = s.id_token
    return RedirectResponse("/")


@app.get("/")
async def home(request: Request):
    token = request.session.get("uta_access_token")
    if token:
        try:
            ent = await get_entitlement_async(token)
            return {"sub": request.session.get("uta_sub"), "entitlement": ent.raw}
        except UtaTokenError:
            # Token revoked/expired (signed out of UseThatApp). Reconcile.
            for k in ("uta_access_token", "uta_sub", "uta_id_token"):
                request.session.pop(k, None)
    return HTMLResponse('<a href="/login">Log in with UseThatApp</a>')


@app.get("/logout")
def logout(request: Request):
    # Don't clear the session yet — the user may choose "Stay signed in". A
    # real logout revokes the token, so the next get_entitlement (home) 401s
    # and we drop it then.
    id_token = request.session.get("uta_id_token")
    return RedirectResponse(
        logout_url(id_token=id_token, post_logout_redirect_uri="http://localhost:8000/")
    )
