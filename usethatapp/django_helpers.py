"""Django integration helpers.

Importing this module requires Django. The top-level
``usethatapp.__init__`` gates the import so the package works fine
without Django installed.
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable

from django.http import HttpResponseBadRequest, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt

from .client import get_user_from_request
from .errors import UtaError
from .types import UtaUser

logger = logging.getLogger("usethatapp")


def uta_launch_view(view_func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorate a Django view to handle UseThatApp launch POSTs.

    The wrapped view receives the verified :class:`UtaUser` as its
    second positional argument and also as ``request.uta_user``.

    Behaviors:
        * ``@csrf_exempt`` is applied — the marketplace POSTs
          cross-origin with a one-time payload; the envelope signature
          is the actual authentication.
        * Only POST is accepted; other methods return 405.
        * Any :class:`UtaError` results in 400 with a short reason
          and a WARNING-level log entry.
    """

    @csrf_exempt
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        try:
            user: UtaUser = get_user_from_request(request)
        except UtaError as e:
            logger.warning("uta_launch_view: rejecting launch: %s", e)
            return HttpResponseBadRequest(f"invalid launch payload: {e}")
        request.uta_user = user
        return view_func(request, user, *args, **kwargs)

    return wrapper


__all__ = ["uta_launch_view"]

