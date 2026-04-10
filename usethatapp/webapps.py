from typing import Union
import json

from .encryption import Keys, decrypt_message, verify_signature


def _normalize_hex(h: str) -> str:
    if h is None:
        raise ValueError("hex input is None")
    h = h.strip()
    if h.startswith("0x") or h.startswith("0X"):
        h = h[2:]
    if len(h) % 2 != 0:
        # hex strings must have an even length
        raise ValueError("invalid hex string (odd length)")
    return h


def get_version(
    envelope,
    public_key_path: str,
    private_key_path: str,
    encoding: str = "utf-8",
) -> Union[str, bytes]:
    """Verify and decrypt an access-level response from ``requestAccessLevel()``.

    The *envelope* is the object resolved by the ``requestAccessLevel()``
    JavaScript function exposed by **usethatapp.js**.  It has the shape::

        {
            "type": "level",
            "responseTo": "<request-id>",
            "message": {
                "contents": "<hex-encrypted-license>",
                "signature": "<hex-signature>"
            }
        }

    If the envelope carries an error (``type`` == ``"error"``), a
    ``ValueError`` is raised with the server's error description.

    Args:
        envelope: a dict or JSON string — the full postMessage envelope
                  returned by ``requestAccessLevel()``.
        public_key_path: path to the UseThatApp PEM public key file used
                         to verify the signature.
        private_key_path: path to the developer's PEM private key file
                          used to decrypt the message.
        encoding: the decrypted bytes will be decoded to a string using
                  this encoding; if decoding fails the raw bytes are
                  returned.

    Returns:
        The decrypted product name as a string (when decoding succeeds)
        or bytes.

    Raises:
        ValueError: on invalid envelope, error responses, missing keys,
                    or failed signature verification.
    """
    # ── parse input ──────────────────────────────────────────────────
    if isinstance(envelope, str):
        try:
            envelope = json.loads(envelope)
        except Exception as e:
            raise ValueError(f"failed to parse envelope JSON: {e}")
    elif not isinstance(envelope, dict):
        raise ValueError("envelope must be a dict or JSON string")

    # ── check envelope type ──────────────────────────────────────────
    msg_type = envelope.get("type")
    if msg_type == "error":
        error_detail = envelope.get("message", "Unknown error")
        raise ValueError(f"server error: {error_detail}")
    if msg_type != "level":
        raise ValueError(
            f"unexpected envelope type '{msg_type}': expected 'level'"
        )

    # ── extract payload from envelope.message ────────────────────────
    payload = envelope.get("message")
    if not isinstance(payload, dict):
        raise ValueError("envelope 'message' field must be a dict")

    signature_hex = payload.get("signature")
    encrypted_message_hex = payload.get("contents")

    if signature_hex is None:
        raise ValueError("payload missing 'signature' field")
    if encrypted_message_hex is None:
        raise ValueError("payload missing 'contents' field")

    # ── hex → bytes ──────────────────────────────────────────────────
    try:
        sig_hex = _normalize_hex(signature_hex)
        msg_hex = _normalize_hex(encrypted_message_hex)
        signature = bytes.fromhex(sig_hex)
        encrypted_message = bytes.fromhex(msg_hex)
    except ValueError as e:
        raise ValueError(f"invalid hex input: {e}")

    # ── load keys ────────────────────────────────────────────────────
    try:
        public_key = Keys.read_public_key_from_file(public_key_path)
    except Exception as e:
        raise ValueError(f"failed to read public key from '{public_key_path}': {e}")

    try:
        private_key = Keys.read_private_key_from_file(private_key_path)
    except Exception as e:
        raise ValueError(f"failed to read private key from '{private_key_path}': {e}")

    # ── verify signature ─────────────────────────────────────────────
    if not verify_signature(public_key, signature, encrypted_message):
        raise ValueError("signature verification failed")

    # ── decrypt ──────────────────────────────────────────────────────
    decrypted = decrypt_message(private_key, encrypted_message)

    try:
        return decrypted.decode(encoding)
    except Exception:
        return decrypted


__all__ = ["get_version"]
