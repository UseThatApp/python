"""Tests for the launch-envelope flow: get_user_from_request / get_user."""
from __future__ import annotations

import json
import time

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from usethatapp import (
    UtaAppMismatchError,
    UtaError,
    UtaPayloadExpiredError,
    UtaSignatureError,
    UtaUser,
    get_user,
)
from usethatapp.payloads import build_payload, unpack_payload


def test_roundtrip_basic(make_envelope, app_id):
    envelope = make_envelope(version_hint="Pro")
    user = get_user(envelope)
    assert isinstance(user, UtaUser)
    assert user.user_key == "opaque-user-key-xyz"
    assert user.app_id == app_id
    assert user.version_hint == "Pro"
    assert user.expires_at > user.issued_at


def test_roundtrip_accepts_dict(make_envelope):
    envelope_str = make_envelope()
    envelope_dict = json.loads(envelope_str)
    user = get_user(envelope_dict)
    assert user.user_key == "opaque-user-key-xyz"


def test_roundtrip_no_version_hint(make_envelope):
    user = get_user(make_envelope())
    assert user.version_hint is None


def test_reject_tampered_ciphertext(make_envelope):
    envelope = json.loads(make_envelope())
    ct = bytes.fromhex(envelope["ct"])
    # flip a byte
    tampered = bytearray(ct)
    tampered[-1] ^= 0x01
    envelope["ct"] = tampered.hex()
    # re-encode (signature now won't cover this — should fail signature first)
    with pytest.raises(UtaSignatureError):
        get_user(json.dumps(envelope))


def test_reject_tampered_signature(make_envelope):
    envelope = json.loads(make_envelope())
    sig = bytearray(bytes.fromhex(envelope["signature"]))
    sig[0] ^= 0xFF
    envelope["signature"] = sig.hex()
    with pytest.raises(UtaSignatureError):
        get_user(json.dumps(envelope))


def test_reject_expired_payload(make_envelope):
    # iat 10 hours ago, exp 10 hours ago + 1s -> definitely expired beyond skew
    long_ago = int(time.time()) - 36000
    envelope = make_envelope(iat=long_ago, exp_seconds=1)
    with pytest.raises(UtaPayloadExpiredError):
        get_user(envelope)


def test_reject_mismatched_app_id(make_envelope):
    envelope = make_envelope(app_id="ffffffff-ffff-ffff-ffff-ffffffffffff")
    with pytest.raises(UtaAppMismatchError):
        get_user(envelope)


def test_reject_wrong_kind(make_envelope):
    envelope = make_envelope(kind="something-else")
    with pytest.raises(UtaError):
        get_user(envelope)


def test_reject_missing_fields(make_envelope):
    envelope = json.loads(make_envelope())
    del envelope["ek"]
    with pytest.raises(UtaError, match="missing fields"):
        get_user(json.dumps(envelope))


def test_reject_bad_hex(make_envelope):
    envelope = json.loads(make_envelope())
    envelope["iv"] = "zzzz"  # not valid hex
    with pytest.raises(UtaError, match="not valid hex"):
        get_user(json.dumps(envelope))


def test_reject_malformed_json():
    with pytest.raises(UtaError, match="not valid JSON"):
        get_user("{not json")


def test_reject_wrong_envelope_version(make_envelope):
    envelope = json.loads(make_envelope())
    envelope["v"] = 99
    with pytest.raises(UtaError, match="unsupported envelope version"):
        get_user(json.dumps(envelope))


def test_reject_wrong_developer_key(developer_keypair, market_keypair, app_id):
    # Build for a *different* developer key — OAEP unwrap will fail.
    wrong_dev = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    envelope = build_payload(
        user_key="x",
        app_id=app_id,
        developer_public_key=wrong_dev.public_key(),
        market_private_key=market_keypair,
    )
    with pytest.raises(UtaError):
        get_user(envelope)


def test_get_user_from_request_django_request(make_envelope):
    """``get_user_from_request`` extracts uta_payload from a Django-style request.POST."""
    from usethatapp import get_user_from_request

    class DjangoLikePOST(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class DjangoLikeRequest:
        def __init__(self, payload):
            self.POST = DjangoLikePOST({"uta_payload": payload})

    request = DjangoLikeRequest(make_envelope())
    user = get_user_from_request(request)
    assert user.user_key == "opaque-user-key-xyz"


def test_get_user_from_request_flask_request(make_envelope):
    from usethatapp import get_user_from_request

    class FlaskLikeForm(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class FlaskLikeRequest:
        def __init__(self, payload):
            self.form = FlaskLikeForm({"uta_payload": payload})

    user = get_user_from_request(FlaskLikeRequest(make_envelope()))
    assert user.user_key == "opaque-user-key-xyz"


def test_get_user_from_request_missing_payload():
    from usethatapp import get_user_from_request

    class Req:
        POST = {}

    with pytest.raises(UtaError, match="uta_payload"):
        get_user_from_request(Req())


def test_unpack_payload_direct(make_envelope, developer_keypair, market_keypair):
    """Direct unpack_payload returns the inner JSON dict."""
    inner = unpack_payload(
        make_envelope(),
        developer_private_key=developer_keypair,
        market_public_key=market_keypair.public_key(),
    )
    assert inner["kind"] == "launch"
    assert inner["user_key"] == "opaque-user-key-xyz"

