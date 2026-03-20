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


def get_product(
    message,
    public_key_path: str,
    private_key_path: str,
    encoding: str = "utf-8",
) -> Union[str, bytes]:
    """Verify a hex signature and decrypt a hex-encoded encrypted message from a JSON message.

    Args:
        message: a dict or JSON string containing two keys: "signature" and "contents",
                 both values should be hex strings (optionally prefixed with 0x).
        public_key_path: path to the PEM public key file used to verify the signature
        private_key_path: path to the PEM private key file used to decrypt the message
        encoding: if provided, the decrypted bytes will be decoded to a string using this encoding;
                  if decoding fails, the raw bytes are returned.

    Returns:
        The decrypted message as a string (when decoding succeeds) or bytes.

    Raises:
        ValueError: on invalid inputs, missing keys, or failed signature verification.
    """
    # accept either a dict or a JSON string
    if isinstance(message, str):
        try:
            message_obj = json.loads(message)
        except Exception as e:
            raise ValueError(f"failed to parse message JSON: {e}")
    elif isinstance(message, dict):
        message_obj = message
    else:
        raise ValueError("message must be a dict or JSON string")

    # extract expected fields
    try:
        signature_hex = message_obj["signature"]
        encrypted_message_hex = message_obj.get("contents") or message_obj.get("content")
    except Exception as e:
        raise ValueError(f"message must contain 'signature' and 'contents' fields: {e}")

    if encrypted_message_hex is None:
        raise ValueError("message missing 'contents' field")

    # normalize and convert hex inputs to bytes
    try:
        sig_hex = _normalize_hex(signature_hex)
        msg_hex = _normalize_hex(encrypted_message_hex)
        signature = bytes.fromhex(sig_hex)
        encrypted_message = bytes.fromhex(msg_hex)
    except ValueError as e:
        raise ValueError(f"invalid hex input: {e}")

    # load keys from files using the Keys helpers in encryption.py
    try:
        public_key = Keys.read_public_key_from_file(public_key_path)
    except Exception as e:
        raise ValueError(f"failed to read public key from '{public_key_path}': {e}")

    try:
        private_key = Keys.read_private_key_from_file(private_key_path)
    except Exception as e:
        raise ValueError(f"failed to read private key from '{private_key_path}': {e}")

    # verify the signature against the encrypted message
    verified = verify_signature(public_key, signature, encrypted_message)
    if not verified:
        raise ValueError("signature verification failed")

    # decrypt the message
    decrypted = decrypt_message(private_key, encrypted_message)

    # try to decode to text; if decoding fails, return raw bytes
    try:
        return decrypted.decode(encoding)
    except Exception:
        return decrypted


__all__ = ["get_product"]
