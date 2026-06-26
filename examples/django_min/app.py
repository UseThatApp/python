"""Minimal Django app demonstrating the UseThatApp OIDC login + entitlement flow.

Docs only — the SDK ships no Django-specific code. This shows the three
framework-specific bits you wire yourself: read callback params, store
``flow_state`` in the session, issue redirects.

Run:
    pip install usethatapp django
    export UTA_CLIENT_ID=... UTA_CLIENT_SECRET=... UTA_REDIRECT_URI=http://localhost:8000/callback/
    python app.py runserver
"""
from __future__ import annotations

import os

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import path

from usethatapp import (
    UtaError,
    begin_login,
    complete_login,
    get_entitlement,
    logout_url,
)

if not settings.configured:
    settings.configure(
        DEBUG=True,
        SECRET_KEY=os.environ.get("DJANGO_SECRET_KEY", "dev-only"),
        ALLOWED_HOSTS=["*"],
        ROOT_URLCONF=__name__,
        # signed-cookie sessions keep this example DB-free.
        SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
        INSTALLED_APPS=["django.contrib.sessions"],
        MIDDLEWARE=["django.contrib.sessions.middleware.SessionMiddleware"],
    )


def login(request):
    auth_url, flow_state = begin_login()
    request.session["uta_flow"] = flow_state          # stash for the callback
    return redirect(auth_url)


def callback(request):
    # On cancel/deny, OAuth redirects back with ?error=... and no code.
    if request.GET.get("error"):
        request.session.pop("uta_flow", None)
        return redirect("home")
    try:
        session = complete_login(
            code=request.GET.get("code"),
            state=request.GET.get("state"),
            flow_state=request.session.pop("uta_flow", {}),
        )
    except UtaError as e:
        return HttpResponse(f"login failed: {e}", status=400)
    # Persist what you need against your own session.
    request.session["uta_sub"] = session.sub
    request.session["uta_access_token"] = session.access_token
    request.session["uta_id_token"] = session.id_token
    return redirect("home")


def home(request):
    token = request.session.get("uta_access_token")
    if not token:
        return HttpResponse('<a href="/login/">Log in with UseThatApp</a>')
    ent = get_entitlement(token)
    return JsonResponse({"sub": request.session.get("uta_sub"), "entitlement": ent.raw})


def logout(request):
    id_token = request.session.get("uta_id_token")
    request.session.flush()
    return redirect(logout_url(id_token=id_token, post_logout_redirect_uri="http://localhost:8000/"))


urlpatterns = [
    path("", home, name="home"),
    path("login/", login, name="login"),
    path("callback/", callback, name="callback"),
    path("logout/", logout, name="logout"),
]


if __name__ == "__main__":  # pragma: no cover
    import sys
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
