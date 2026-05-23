"""Minimal Streamlit integration for the UseThatApp SDK.

Streamlit does not expose raw POST routes, so the recommended pattern
is to run a tiny POST-receiver alongside Streamlit. Two options:

A. **Sidecar receiver (recommended).** Run a small FastAPI/Flask
   process that owns ``/uta/launch/``. It verifies the envelope, stores
   ``user_key`` in shared storage (Redis / DB / signed cookie), and
   redirects the browser to the Streamlit URL. Streamlit then reads
   the stored ``user_key`` from ``st.session_state`` (set via a signed
   cookie/query param) and calls ``get_version``.

B. **Streamlit + reverse proxy.** Put nginx/Caddy in front; route POST
   ``/uta/launch/`` to a sidecar, everything else to Streamlit. Same
   as (A) for the SDK code.

Either way, the only SDK calls you make inside Streamlit are
``get_user`` (if you forwarded the raw envelope as a
query string — possible but ugly) or, much more commonly, just
``get_version(user_key)`` once you have ``user_key`` in session.

Run:
    pip install usethatapp streamlit
    export UTA_APP_ID=...
    export UTA_PRIVATE_KEY="$(cat dev_priv.pem)"
    export UTA_MARKET_PUBLIC_KEY="$(cat market_pub.pem)"
    streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

from usethatapp import (
    UtaError,
    UtaSessionRevokedError,
    get_user,
    get_version,
)

st.set_page_config(page_title="UseThatApp + Streamlit")
st.title("UseThatApp demo (Streamlit)")

# ── 1) Bootstrapping the user_key ─────────────────────────────────────
# Pick ONE of these two patterns:

# (A) Sidecar receiver wrote the user_key into a signed cookie / query
#     param that you read on the Streamlit side. Pseudo-code:
#
#     user_key = read_signed_cookie("uta_user_key")
#     st.session_state["uta_user_key"] = user_key

# (B) Demo only — accept an already-verified launch payload pasted in
#     by the developer for local testing.
with st.expander("Dev: paste a launch envelope"):
    raw = st.text_area("uta_payload (JSON envelope)", height=120)
    if st.button("Verify & store") and raw:
        try:
            user = get_user(raw)
        except UtaError as e:
            st.error(f"Rejected: {e}")
        else:
            st.session_state["uta_user_key"] = user.user_key
            st.session_state["uta_version_hint"] = user.version_hint
            st.success(f"Stored user_key for app {user.app_id}.")


# ── 2) Using the user_key ─────────────────────────────────────────────
user_key = st.session_state.get("uta_user_key")
if not user_key:
    st.info("No active launch session. Use the panel above or your sidecar.")
    st.stop()

# Show the (non-authoritative) hint for instant first paint.
hint = st.session_state.get("uta_version_hint")
if hint:
    st.caption(f"Initial hint (not authoritative): {hint}")

# Call get_version for the real, current tier. Cached automatically.
try:
    version = get_version(user_key)
except UtaSessionRevokedError:
    st.session_state.pop("uta_user_key", None)
    st.error("Your session was revoked. Please re-launch from usethatapp.com.")
    st.stop()
except UtaError as e:
    st.error(f"License check failed: {e}")
    st.stop()

st.metric("Current license tier", version or "—")

if version and version.lower() == "pro":
    st.success("Pro features unlocked.")
else:
    st.info("Free tier — upgrade for Pro features.")

