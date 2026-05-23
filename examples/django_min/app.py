"""Minimal Django app demonstrating the UseThatApp launch + license flow.

Run:
    pip install usethatapp django
    # Generate a throwaway developer keypair and set UTA_APP_ID
    python manage.py runserver

Then POST a hand-crafted envelope (see scripts/handcraft_payload.py in
the tests/ directory of the SDK repo) to /uta/launch/.
"""
from __future__ import annotations

import os

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.urls import path

from usethatapp import UtaUser, get_version, uta_launch_view


# ── settings ─────────────────────────────────────────────────────────
if not settings.configured:
    settings.configure(
        DEBUG=True,
        SECRET_KEY=os.environ.get("DJANGO_SECRET_KEY", "dev-only"),
        ALLOWED_HOSTS=["*"],
        ROOT_URLCONF=__name__,
        DATABASES={},
        INSTALLED_APPS=[],
        MIDDLEWARE=[],
        UTA_APP_ID=os.environ["UTA_APP_ID"],
        UTA_PRIVATE_KEY=os.environ["UTA_PRIVATE_KEY"],
        UTA_MARKET_PUBLIC_KEY=os.environ["UTA_MARKET_PUBLIC_KEY"],
    )


# ── views ────────────────────────────────────────────────────────────
@uta_launch_view
def launch(request, uta_user: UtaUser):
    # In a real app you'd persist user_key into your own session.
    try:
        version = get_version(uta_user.user_key)
    except Exception as e:  # pragma: no cover
        version = f"<error: {e}>"
    return JsonResponse({
        "user_key": uta_user.user_key,
        "app_id": uta_user.app_id,
        "version_hint": uta_user.version_hint,
        "version": version,
    })


def index(request):
    return HttpResponse("usethatapp django_min example. POST to /uta/launch/.")


urlpatterns = [
    path("", index),
    path("uta/launch/", launch, name="uta-launch"),
]


# ── manage.py-style entrypoint ───────────────────────────────────────
if __name__ == "__main__":  # pragma: no cover
    import sys
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)

