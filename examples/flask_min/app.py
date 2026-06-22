"""Minimal Flask app: UseThatApp OIDC login + entitlement (docs only).

Run:
    pip install usethatapp flask
    export UTA_CLIENT_ID=... UTA_CLIENT_SECRET=... UTA_REDIRECT_URI=http://localhost:5000/callback
    export FLASK_SECRET_KEY=dev-only
    python app.py
"""
from __future__ import annotations

import os

from flask import Flask, redirect, request, session, url_for

from usethatapp import UtaError, begin_login, complete_login, get_entitlement, logout_url

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only")


@app.route("/login")
def login():
    auth_url, flow_state = begin_login()
    session["uta_flow"] = flow_state
    return redirect(auth_url)


@app.route("/callback")
def callback():
    try:
        s = complete_login(
            code=request.args.get("code"),
            state=request.args.get("state"),
            flow_state=session.pop("uta_flow", {}),
        )
    except UtaError as e:
        return f"login failed: {e}", 400
    session["uta_sub"] = s.sub
    session["uta_access_token"] = s.access_token
    session["uta_id_token"] = s.id_token
    return redirect(url_for("home"))


@app.route("/")
def home():
    token = session.get("uta_access_token")
    if not token:
        return '<a href="/login">Log in with UseThatApp</a>'
    ent = get_entitlement(token)
    return {"sub": session.get("uta_sub"), "entitlement": ent.raw}


@app.route("/logout")
def logout():
    id_token = session.get("uta_id_token")
    session.clear()
    return redirect(logout_url(id_token=id_token, post_logout_redirect_uri="http://localhost:5000/"))


if __name__ == "__main__":  # pragma: no cover
    app.run(port=5000)
