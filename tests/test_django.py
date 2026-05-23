"""Tests for the @uta_launch_view Django decorator.

These tests configure Django minimally before importing the helper.
"""
from __future__ import annotations

import pytest

django = pytest.importorskip("django")

from django.conf import settings as django_settings

if not django_settings.configured:
    django_settings.configure(
        DEBUG=True,
        SECRET_KEY="test-secret",
        ALLOWED_HOSTS=["*"],
        DATABASES={},
        INSTALLED_APPS=[],
        ROOT_URLCONF=__name__,
        MIDDLEWARE=[],
    )
    django.setup()

from django.test import RequestFactory  # noqa: E402

from usethatapp import UtaUser  # noqa: E402
from usethatapp.django_helpers import uta_launch_view  # noqa: E402


def test_launch_view_happy(make_envelope):
    rf = RequestFactory()

    captured = {}

    @uta_launch_view
    def view(request, uta_user: UtaUser):
        captured["user"] = uta_user
        captured["from_request"] = request.uta_user
        from django.http import HttpResponse
        return HttpResponse("ok")

    payload = make_envelope()
    request = rf.post("/uta/launch/", data={"uta_payload": payload})
    response = view(request)
    assert response.status_code == 200
    assert captured["user"].user_key == "opaque-user-key-xyz"
    assert captured["from_request"] is captured["user"]


def test_launch_view_rejects_get(make_envelope):
    rf = RequestFactory()

    @uta_launch_view
    def view(request, uta_user: UtaUser):  # pragma: no cover
        raise AssertionError("should not be called")

    response = view(rf.get("/uta/launch/"))
    assert response.status_code == 405


def test_launch_view_bad_payload():
    rf = RequestFactory()

    @uta_launch_view
    def view(request, uta_user: UtaUser):  # pragma: no cover
        raise AssertionError("should not be called")

    response = view(rf.post("/uta/launch/", data={"uta_payload": "{garbage"}))
    assert response.status_code == 400


def test_launch_view_missing_payload():
    rf = RequestFactory()

    @uta_launch_view
    def view(request, uta_user: UtaUser):  # pragma: no cover
        raise AssertionError("should not be called")

    response = view(rf.post("/uta/launch/", data={}))
    assert response.status_code == 400

