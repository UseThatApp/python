"""Minimal Dash integration for the UseThatApp SDK.

Dash sits on top of Flask. We attach the launch endpoint to Dash's
underlying Flask server (``app.server``), persist the ``user_key`` in
the Flask session, then read it from any Dash callback.

Run:
    pip install usethatapp dash
    export UTA_APP_ID=...
    export UTA_PRIVATE_KEY="$(cat dev_priv.pem)"
    export UTA_MARKET_PUBLIC_KEY="$(cat market_pub.pem)"
    python app.py
"""
from __future__ import annotations

from dash import Dash, Input, Output, dcc, html
from flask import jsonify, request, session

from usethatapp import UtaError, get_user_from_request, get_version

dash_app = Dash(__name__)
flask_server = dash_app.server
flask_server.secret_key = "dev-only-change-me"


# ── Launch endpoint (Flask route on Dash's underlying server) ────────
@flask_server.post("/uta/launch/")
def launch():
    try:
        uta_user = get_user_from_request(request)  # reads request.form["uta_payload"]
    except UtaError as e:
        return jsonify({"error": str(e)}), 400
    session["uta_user_key"] = uta_user.user_key
    session["uta_version_hint"] = uta_user.version_hint
    # Bounce the browser into the Dash UI.
    return jsonify({"ok": True, "next": "/"}), 200


# ── Dash UI ─────────────────────────────────────────────────────────
dash_app.layout = html.Div([
    html.H1("UseThatApp demo (Dash)"),
    html.Div(id="status"),
    dcc.Interval(id="poll", interval=30_000, n_intervals=0),
])


@dash_app.callback(Output("status", "children"), Input("poll", "n_intervals"))
def refresh(_):
    user_key = session.get("uta_user_key")
    if not user_key:
        return "Not launched — POST a launch envelope to /uta/launch/ first."
    try:
        version = get_version(user_key)
    except UtaError as e:
        return f"License check failed: {e}"
    return f"Current license tier: {version!r}"


if __name__ == "__main__":  # pragma: no cover
    dash_app.run(host="0.0.0.0", port=8000, debug=True)

