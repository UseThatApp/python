"""Minimal FastAPI integration for the UseThatApp SDK.

Run:
    pip install usethatapp fastapi uvicorn
    export UTA_APP_ID=...
    export UTA_PRIVATE_KEY="$(cat dev_priv.pem)"
    export UTA_MARKET_PUBLIC_KEY="$(cat market_pub.pem)"
    uvicorn app:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from usethatapp import (
    UtaError,
    UtaSessionRevokedError,
    get_user_from_request_async,
    get_version_async,
)

app = FastAPI()

# Demo only — in production persist user_keys per-session (Redis, signed
# cookies, your auth layer, etc.).
_DEMO_SESSIONS: dict[str, str] = {}


@app.post("/uta/launch/")
async def launch(request: Request):
    # FastAPI/Starlette: get_user_from_request_async awaits request.form() for you.
    try:
        uta_user = await get_user_from_request_async(request)
    except UtaError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Tie uta_user.user_key to your own session id however you want.
    session_id = request.headers.get("x-session-id", "demo-session")
    _DEMO_SESSIONS[session_id] = uta_user.user_key

    return {
        "user_key": uta_user.user_key,
        "app_id": uta_user.app_id,
        "version_hint": uta_user.version_hint,  # first-paint only
    }


@app.get("/me/version/")
async def me_version(request: Request):
    session_id = request.headers.get("x-session-id", "demo-session")
    user_key = _DEMO_SESSIONS.get(session_id)
    if not user_key:
        raise HTTPException(status_code=401, detail="not launched")
    try:
        version = await get_version_async(user_key)
    except UtaSessionRevokedError:
        _DEMO_SESSIONS.pop(session_id, None)
        raise HTTPException(status_code=401, detail="session revoked")
    except UtaError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"version": version}

