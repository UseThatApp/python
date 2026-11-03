"""Minimal Flask app: sell with UseThatApp, verify with license keys (docs only).

Your app keeps its own login; UseThatApp only sells. The buyer clicks Buy,
pays on usethatapp.com, and returns to /thanks?uta_order=... where the key
is stored on the signed-in user. /pro is a paid feature gated on that key.

Run:
    pip install usethatapp flask
    export UTA_CLIENT_ID=... UTA_CLIENT_SECRET=...
    export UTA_PRICE_ID=prc_...   UTA_PRO_PRODUCT=prod_...
    export FLASK_SECRET_KEY=dev-only
    python app.py

Set the buy link's ``next`` to http://localhost:5000/thanks (loopback is
allowed in development). Users live in memory so the example stays short.

Opening your own buy link while signed in to usethatapp.com as the app's
developer runs a no-charge walkthrough that creates no license key, so test
this flow with one real purchase from a second account.
"""
from __future__ import annotations

import os

from flask import Flask, redirect, request, session, url_for

from usethatapp import (
    UtaError,
    UtaOrderProcessingError,
    get_order,
    purchase_url,
    validate_license_key,
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only")

PRICE_ID = os.environ["UTA_PRICE_ID"]          # prc_… from get_prices() or the dashboard
PRO_PRODUCT = os.environ["UTA_PRO_PRODUCT"]    # prod_… the price belongs to
USERS: dict[str, dict] = {}                    # stand-in for your user table


def current_user():
    return USERS.get(session.get("user", ""))


@app.route("/login", methods=["GET", "POST"])
def login():
    # Stand-in for YOUR auth (Auth0, Clerk, Django auth, ...).
    if request.method == "POST":
        name = request.form["name"]
        USERS.setdefault(name, {"license_key": None, "license_id": None})
        session["user"] = name
        return redirect(session.pop("after_login", url_for("home")))
    return '<form method="post"><input name="name" placeholder="your name"><button>Sign in</button></form>'


@app.route("/")
def home():
    if not current_user():
        return redirect(url_for("login"))
    buy = purchase_url(PRICE_ID, next=url_for("thanks", _external=True))
    return f'<a href="{buy}">Buy Pro</a> · <a href="{url_for("pro")}">Pro feature</a>'


@app.route("/thanks")
def thanks():
    ref = request.args.get("uta_order")
    if not ref:
        return redirect(url_for("home"))
    if not current_user():
        # Never drop the ref: finish linking it after the user signs in.
        session["after_login"] = request.full_path
        return redirect(url_for("login"))
    try:
        order = get_order(ref)
    except UtaOrderProcessingError:
        # Paid, key not stored yet. Reload shortly.
        return '<meta http-equiv="refresh" content="2">Finishing up your purchase…'
    except UtaError as e:
        return f"Could not confirm the purchase: {e}", 502
    current_user().update(license_key=order.license_key, license_id=order.license_id)
    return redirect(url_for("pro"))


@app.route("/pro")
def pro():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    if user["license_key"]:
        try:
            state = validate_license_key(user["license_key"])
        except UtaError as e:
            return f"Could not verify your license: {e}", 502
        if state.entitled and state.product_public_id == PRO_PRODUCT:
            return "Welcome to Pro."
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)
