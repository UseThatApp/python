"""Launch-envelope crypto wire format.

The marketplace ships a JSON-encoded envelope in the ``uta_payload``
field of the launch POST::

    {
      "v": 1,
      "alg": "RSA-OAEP-SHA256+AES-256-GCM+RSA-PSS-SHA256",
      "ek": "<hex>",       # RSA-OAEP-SHA256(developer_pub, aes_key)
      "iv": "<hex>",       # 12-byte AES-GCM nonce
      "ct": "<hex>",       # AES-256-GCM(aes_key, iv, plaintext, aad = ek || iv)
      "signature": "<hex>" # RSA-PSS-SHA256(market_priv, ek || iv || ct)
    }

This module provides:

* :func:`unpack_payload` — verify + decrypt + parse. Used by ``get_user_from_request``.
* :func:`build_payload` — build an envelope; useful for tests / fixtures.
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any, Dict, Mapping, Optional, Union

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import (
    RSAPrivateKey,
    RSAPublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .errors import UtaError, UtaSignatureError

ENVELOPE_VERSION = 1
ALG_LABEL = "RSA-OAEP-SHA256+AES-256-GCM+RSA-PSS-SHA256"

_REQUIRED_ENVELOPE_FIELDS = ("v", "alg", "ek", "iv", "ct", "signature")


def _oaep() -> padding.OAEP:
    return padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=None,
    )


def _pss() -> padding.PSS:
    return padding.PSS(
        mgf=padding.MGF1(hashes.SHA256()),
        salt_length=padding.PSS.MAX_LENGTH,
    )


def _from_hex(name: str, value: Any) -> bytes:
    if not isinstance(value, str):
        raise UtaError(f"envelope field '{name}' must be a hex string")
    try:
        return bytes.fromhex(value)
    except ValueError as e:
        raise UtaError(f"envelope field '{name}' is not valid hex: {e}")


def unpack_payload(
    envelope: Union[str, Mapping[str, Any]],
    *,
    developer_private_key: RSAPrivateKey,
    market_public_key: RSAPublicKey,
) -> Dict[str, Any]:
    """Verify + decrypt + JSON-parse a launch envelope.

    Verification order:
        1. JSON-decode the envelope and check required fields.
        2. Hex-decode ``ek``, ``iv``, ``ct``, ``signature``.
        3. PSS-verify ``signature`` over ``ek || iv || ct`` with
           ``market_public_key``.
        4. RSA-OAEP-unwrap ``ek`` with ``developer_private_key`` to
           obtain the 32-byte AES key.
        5. AES-256-GCM decrypt ``ct`` with ``aad = ek || iv``.
        6. JSON-parse the plaintext and return the dict.

    Raises:
        UtaSignatureError: PSS verification failed.
        UtaError: any other envelope/crypto/JSON failure. (Callers
            (``get_user_from_request``) catch this and re-raise as appropriate.)
    """
    # 1. JSON decode
    if isinstance(envelope, str):
        try:
            env = json.loads(envelope)
        except json.JSONDecodeError as e:
            raise UtaError(f"envelope is not valid JSON: {e}")
    elif isinstance(envelope, Mapping):
        env = dict(envelope)
    else:
        raise UtaError(
            f"envelope must be a JSON string or mapping, got "
            f"{type(envelope).__name__}. If you have a Django / Flask / "
            f"Starlette / FastAPI request object, call "
            f"get_user_from_request(request) (or "
            f"get_user_from_request_async for async views) instead."
        )

    # Field presence
    missing = [f for f in _REQUIRED_ENVELOPE_FIELDS if f not in env]
    if missing:
        raise UtaError(f"envelope missing fields: {', '.join(missing)}")

    if env.get("v") != ENVELOPE_VERSION:
        raise UtaError(f"unsupported envelope version: {env.get('v')!r}")
    if env.get("alg") != ALG_LABEL:
        raise UtaError(f"unsupported envelope alg: {env.get('alg')!r}")

    # 2. hex decode
    ek = _from_hex("ek", env["ek"])
    iv = _from_hex("iv", env["iv"])
    ct = _from_hex("ct", env["ct"])
    signature = _from_hex("signature", env["signature"])

    if len(iv) != 12:
        raise UtaError(f"iv must be 12 bytes, got {len(iv)}")

    # 3. PSS verify
    signed = ek + iv + ct
    try:
        market_public_key.verify(signature, signed, _pss(), hashes.SHA256())
    except InvalidSignature:
        raise UtaSignatureError("launch envelope signature verification failed")

    # 4. OAEP unwrap
    try:
        aes_key = developer_private_key.decrypt(ek, _oaep())
    except Exception as e:
        raise UtaError(f"failed to unwrap AES key: {e}")
    if len(aes_key) != 32:
        raise UtaError(f"unwrapped AES key has wrong length: {len(aes_key)}")

    # 5. AES-GCM decrypt
    try:
        plaintext = AESGCM(aes_key).decrypt(iv, ct, ek + iv)
    except InvalidTag:
        raise UtaError("AES-GCM authentication failed (ciphertext tampered)")

    # 6. JSON parse
    try:
        inner = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise UtaError(f"decrypted plaintext is not valid JSON: {e}")
    if not isinstance(inner, dict):
        raise UtaError("decrypted plaintext is not a JSON object")
    return inner


def build_payload(
    *,
    user_key: str,
    app_id: str,
    developer_public_key: RSAPublicKey,
    market_private_key: RSAPrivateKey,
    iat: Optional[int] = None,
    exp_seconds: int = 300,
    nonce: Optional[str] = None,
    version_hint: Optional[str] = None,
    kind: str = "launch",
) -> str:
    """Build a launch envelope (JSON string).

    Intended for tests and for the marketplace-side implementation. The
    SDK itself only ever *unpacks* envelopes in production.

    Returns:
        JSON-encoded envelope string suitable for the ``uta_payload``
        POST field.
    """
    now = int(time.time()) if iat is None else iat
    inner = {
        "kind": kind,
        "user_key": user_key,
        "app_id": app_id,
        "iat": now,
        "exp": now + exp_seconds,
        "nonce": nonce if nonce is not None else secrets.token_hex(16),
    }
    if version_hint is not None:
        inner["version_hint"] = version_hint

    plaintext = json.dumps(inner, separators=(",", ":")).encode("utf-8")

    aes_key = secrets.token_bytes(32)
    iv = secrets.token_bytes(12)

    ek = developer_public_key.encrypt(aes_key, _oaep())
    ct = AESGCM(aes_key).encrypt(iv, plaintext, ek + iv)
    signature = market_private_key.sign(ek + iv + ct, _pss(), hashes.SHA256())

    envelope = {
        "v": ENVELOPE_VERSION,
        "alg": ALG_LABEL,
        "ek": ek.hex(),
        "iv": iv.hex(),
        "ct": ct.hex(),
        "signature": signature.hex(),
    }
    return json.dumps(envelope, separators=(",", ":"))


__all__ = [
    "ENVELOPE_VERSION",
    "ALG_LABEL",
    "unpack_payload",
    "build_payload",
]

