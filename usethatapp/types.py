"""Public dataclasses for the UseThatApp SDK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class UtaUser:
    """An authenticated launch from usethatapp.com.

    The v1 launch envelope deliberately carries only an opaque
    ``user_key`` — no email, username, or other PII. Persist
    ``user_key`` against your own session and pass it to
    :func:`usethatapp.get_version` whenever you need the user's
    current license tier.
    """

    user_key: str
    """Opaque identifier for the user/license. Persist; pass to ``get_version()``."""

    app_id: str
    """Echoed app id; equals ``UTA_APP_ID``."""

    issued_at: int
    """Unix seconds — ``iat`` from the envelope."""

    expires_at: int
    """Unix seconds — ``exp`` from the envelope."""

    version_hint: Optional[str] = None
    """Non-authoritative product name; for first paint only.

    The contract is: developers MAY use this for first paint but MUST
    call :func:`usethatapp.get_version` for the real, current value.
    """


__all__ = ["UtaUser"]

