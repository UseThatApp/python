"""Top-level public API for the ``usethatapp`` SDK (v1 webhook handoff).

Two functions:

* :func:`get_user` — verify+decrypt the launch envelope POSTed by
  usethatapp.com. Returns a :class:`UtaUser`. Framework-agnostic; takes
  the raw payload. See :func:`get_user_from_request` /
  :func:`get_user_from_request_async` for helpers that pull
  ``uta_payload`` straight out of a Django/Flask/Starlette request.
* :func:`get_version` — server-to-server pull of the user's current
  license tier (signed POST to ``/licensing/getversion/``).

Plus a Django-only helper :func:`uta_launch_view` (gated import).
"""

from __future__ import annotations

from .client import (
    clear_version_cache,
    get_user,
    get_user_from_request,
    get_user_from_request_async,
    get_version,
    get_version_async,
)
from .errors import (
    UtaAppMismatchError,
    UtaBadRequestError,
    UtaConfigError,
    UtaError,
    UtaPayloadExpiredError,
    UtaServerError,
    UtaSessionRevokedError,
    UtaSignatureError,
    UtaUnknownSessionError,
)
from .types import UtaUser

# Django helper — optional import. Only available when Django is installed.
try:  # pragma: no cover - exercised in Django-equipped envs
    import django  # noqa: F401

    from .django_helpers import uta_launch_view  # noqa: F401
except Exception:  # pragma: no cover
    pass

__version__ = "1.0.0"

__all__ = [
    "__version__",
    # functions
    "get_user",
    "get_user_from_request",
    "get_user_from_request_async",
    "get_version",
    "get_version_async",
    "clear_version_cache",
    # types
    "UtaUser",
    # errors
    "UtaError",
    "UtaConfigError",
    "UtaSignatureError",
    "UtaPayloadExpiredError",
    "UtaAppMismatchError",
    "UtaBadRequestError",
    "UtaSessionRevokedError",
    "UtaUnknownSessionError",
    "UtaServerError",
]

