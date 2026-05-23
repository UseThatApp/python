"""Minimal Flask integration for the UseThatApp SDK.

Run:
    pip install usethatapp flask
    export UTA_APP_ID=...
    export UTA_PRIVATE_KEY="$(cat dev_priv.pem)"
    export UTA_MARKET_PUBLIC_KEY="$(cat market_pub.pem)"
    python app.py
"""
from __future__ import annotations

from flask import Flask, jsonify, request, session

from usethatapp import (
    UtaError,
    get_user_from_request,
    get_version,
)

app = Flask(__name__)
app.secret_key = "dev-only-change-me"


@app.post("/uta/launch/")
def launch():
    # The marketplace POSTs cross-origin; Flask has no CSRF by default,
    # so nothing extra to disable. The envelope's signature is the auth.
    try:
        uta_user = get_user_from_request(request)  # reads request.form["uta_payload"]
    except UtaError as e:
        return jsonify({"error": str(e)}), 400

    # Persist the opaque key against your own session.
    session["uta_user_key"] = uta_user.user_key

    return jsonify({
        "user_key": uta_user.user_key,
        "app_id": uta_user.app_id,
        # version_hint is for first paint only — don't trust it long-term.
        "version_hint": uta_user.version_hint,
    })


@app.get("/me/version/")
def me_version():
    user_key = session.get("uta_user_key")
    if not user_key:
        return jsonify({"error": "not launched"}), 401
    try:
        version = get_version(user_key)
    except UtaError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"version": version})


if __name__ == "__main__":  # pragma: no cover
    app.run(host="0.0.0.0", port=8000, debug=True)

