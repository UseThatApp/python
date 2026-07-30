"""Tests for the purchase-support helpers (purchase/manage URLs + public APIs)."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from usethatapp import (
    get_app_info,
    get_app_info_async,
    get_prices,
    get_prices_async,
    manage_url,
    purchase_url,
)
from usethatapp.errors import UtaConfigError, UtaError, UtaServerError
from tests.conftest import API_URL, CLIENT_ID

APP_INFO_URL = API_URL + f"/api/v1/public/apps/{CLIENT_ID}/"
PRICES_URL = APP_INFO_URL + "prices/"

APP_INFO_JSON = {
    "client_id": CLIENT_ID,
    "name": "Test App",
    "tagline": "Does the thing",
    "listing_mode": "external",
    "url": "https://app.test.example",
    "marketplace_url": "https://api.test.example/apps/test-app/",
}

PRICES_JSON = {
    "client_id": CLIENT_ID,
    "app_name": "Test App",
    "has_free_tier": True,
    "prices": [
        {
            "public_id": "prc_monthly",
            "product_id": "11111111-1111-1111-1111-111111111111",
            "product_name": "Pro",
            "amount": "10.00",
            "currency": "usd",
            "is_recurring": True,
            "frequency": "month",
            "buy_url": API_URL + "/buy/prc_monthly/",
        },
        {
            "public_id": "prc_lifetime",
            "product_id": "22222222-2222-2222-2222-222222222222",
            "product_name": "Lifetime",
            "amount": "99.00",
            "currency": "usd",
            "is_recurring": False,
            "frequency": None,
            "buy_url": API_URL + "/buy/prc_lifetime/",
        },
    ],
}


# ── purchase_url ──────────────────────────────────────────────────────

def test_purchase_url_bare():
    assert purchase_url("prc_123") == API_URL + "/buy/prc_123/"


def test_purchase_url_all_params_in_order():
    url = purchase_url(
        "prc_123",
        next="https://app.test.example/after?plan=pro&x=1",
        ref="AFF42",
        email="buyer@example.com",
    )
    parsed = urlparse(url)
    assert url.startswith(API_URL + "/buy/prc_123/?")
    # Params appear in the documented order: next, ref, email.
    keys = [pair.split("=")[0] for pair in parsed.query.split("&")]
    assert keys == ["next", "ref", "email"]
    q = parse_qs(parsed.query)
    # Special characters in next round-trip through urlencoding.
    assert q["next"] == ["https://app.test.example/after?plan=pro&x=1"]
    assert q["ref"] == ["AFF42"]
    assert q["email"] == ["buyer@example.com"]
    assert "https%3A%2F%2Fapp.test.example%2Fafter%3Fplan%3Dpro%26x%3D1" in url


def test_purchase_url_omits_none_params():
    url = purchase_url("prc_123", ref="AFF42")
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert set(q) == {"ref"}


@pytest.mark.parametrize("bad", ["", "   "])
def test_purchase_url_empty_price_id_raises(bad):
    with pytest.raises(ValueError, match="price_id"):
        purchase_url(bad)


def test_purchase_url_default_api_url(monkeypatch):
    monkeypatch.delenv("UTA_API_URL", raising=False)
    assert purchase_url("prc_123") == "https://www.usethatapp.com/buy/prc_123/"


# ── manage_url ────────────────────────────────────────────────────────

def test_manage_url_bare():
    assert manage_url() == API_URL + f"/manage/{CLIENT_ID}/"


def test_manage_url_with_next():
    url = manage_url(next="https://app.test.example/account?tab=billing")
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert url.startswith(API_URL + f"/manage/{CLIENT_ID}/?")
    assert q["next"] == ["https://app.test.example/account?tab=billing"]


def test_manage_url_missing_client_id(monkeypatch):
    monkeypatch.delenv("UTA_CLIENT_ID", raising=False)
    with pytest.raises(UtaConfigError, match="UTA_CLIENT_ID"):
        manage_url()


# ── get_app_info ──────────────────────────────────────────────────────

def test_get_app_info(respx_mock):
    respx_mock.get(APP_INFO_URL).mock(
        return_value=httpx.Response(200, json=APP_INFO_JSON)
    )
    info = get_app_info()
    assert info.client_id == CLIENT_ID and info.name == "Test App"
    assert info.tagline == "Does the thing"
    assert info.listing_mode == "external"
    assert info.url == "https://app.test.example"
    assert info.marketplace_url == "https://api.test.example/apps/test-app/"
    assert info.raw == APP_INFO_JSON
    # Anonymous endpoint — no Authorization header is sent.
    assert "Authorization" not in respx_mock.calls.last.request.headers


@pytest.mark.parametrize("status,exc", [
    (404, UtaError),
    (429, UtaServerError),
    (500, UtaServerError),
    (503, UtaServerError),
])
def test_get_app_info_status_mapping(respx_mock, status, exc):
    respx_mock.get(APP_INFO_URL).mock(return_value=httpx.Response(status, text="nope"))
    with pytest.raises(exc):
        get_app_info()


@pytest.mark.asyncio
async def test_get_app_info_async(respx_mock):
    respx_mock.get(APP_INFO_URL).mock(
        return_value=httpx.Response(200, json=APP_INFO_JSON)
    )
    info = await get_app_info_async()
    assert info.name == "Test App" and info.listing_mode == "external"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,exc", [
    (404, UtaError),
    (429, UtaServerError),
    (500, UtaServerError),
])
async def test_get_app_info_async_status_mapping(respx_mock, status, exc):
    respx_mock.get(APP_INFO_URL).mock(return_value=httpx.Response(status, text="nope"))
    with pytest.raises(exc):
        await get_app_info_async()


# ── get_prices ────────────────────────────────────────────────────────

def test_get_prices(respx_mock):
    respx_mock.get(PRICES_URL).mock(return_value=httpx.Response(200, json=PRICES_JSON))
    result = get_prices()
    assert result.client_id == CLIENT_ID and result.app_name == "Test App"
    assert result.has_free_tier is True
    assert len(result.prices) == 2
    monthly, lifetime = result.prices
    assert monthly.public_id == "prc_monthly"
    assert monthly.product_id == "11111111-1111-1111-1111-111111111111"
    assert monthly.amount == "10.00" and monthly.currency == "usd"
    assert monthly.is_recurring is True and monthly.frequency == "month"
    assert monthly.buy_url == API_URL + "/buy/prc_monthly/"
    assert lifetime.is_recurring is False and lifetime.frequency is None
    assert result.raw == PRICES_JSON
    assert "Authorization" not in respx_mock.calls.last.request.headers


@pytest.mark.parametrize("status,exc", [
    (404, UtaError),
    (429, UtaServerError),
    (500, UtaServerError),
    (503, UtaServerError),
])
def test_get_prices_status_mapping(respx_mock, status, exc):
    respx_mock.get(PRICES_URL).mock(return_value=httpx.Response(status, text="nope"))
    with pytest.raises(exc):
        get_prices()


def test_get_prices_404_message_mentions_external_sales(respx_mock):
    respx_mock.get(PRICES_URL).mock(return_value=httpx.Response(404, text="nope"))
    with pytest.raises(UtaError, match="external sales"):
        get_prices()


@pytest.mark.asyncio
async def test_get_prices_async(respx_mock):
    respx_mock.get(PRICES_URL).mock(return_value=httpx.Response(200, json=PRICES_JSON))
    result = await get_prices_async()
    assert result.app_name == "Test App" and len(result.prices) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status,exc", [
    (404, UtaError),
    (429, UtaServerError),
    (500, UtaServerError),
])
async def test_get_prices_async_status_mapping(respx_mock, status, exc):
    respx_mock.get(PRICES_URL).mock(return_value=httpx.Response(status, text="nope"))
    with pytest.raises(exc):
        await get_prices_async()
