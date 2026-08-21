"""License Key API tests: bring-your-own-auth MoR verification."""
from __future__ import annotations

import base64

import httpx
import pytest

from usethatapp import (
    get_order,
    regenerate_license_key,
    validate_license_key,
)
from usethatapp.errors import (
    UtaConfigError,
    UtaError,
    UtaLicenseCanceledError,
    UtaNotFoundError,
    UtaOrderProcessingError,
    UtaServerError,
)

from .conftest import API_URL, CLIENT_ID, CLIENT_SECRET

STATE = {
    "entitled": True,
    "status": "active",
    "license_id": "11111111-2222-3333-4444-555555555555",
    "product_public_id": "prod_abc",
    "period_end": "2026-09-19",
    "canceled_at": None,
}


def _expected_basic() -> str:
    return "Basic " + base64.b64encode(
        f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
    ).decode()


def test_validate_sends_client_credentials(respx_mock):
    route = respx_mock.post(API_URL + "/api/v1/licenses/validate").mock(
        return_value=httpx.Response(200, json=STATE)
    )
    state = validate_license_key("key_abc")
    assert state.entitled and state.status == "active"
    assert state.license_id == STATE["license_id"]
    assert state.license_key is None
    request = route.calls.last.request
    assert request.headers["Authorization"] == _expected_basic()
    assert request.read() == b'{"key": "key_abc"}' or b"key_abc" in request.read()


def test_validate_canceled_is_an_answer_not_an_error(respx_mock):
    respx_mock.post(API_URL + "/api/v1/licenses/validate").mock(
        return_value=httpx.Response(200, json={
            **STATE, "entitled": False, "status": "canceled",
            "canceled_at": "2026-08-20T00:00:00+00:00",
        })
    )
    state = validate_license_key("key_abc")
    assert not state.entitled
    assert state.status == "canceled"


def test_validate_unknown_key(respx_mock):
    respx_mock.post(API_URL + "/api/v1/licenses/validate").mock(
        return_value=httpx.Response(404, json={"error": "unknown_key"})
    )
    with pytest.raises(UtaNotFoundError) as excinfo:
        validate_license_key("key_bogus")
    assert excinfo.value.code == "unknown_key"


def test_missing_client_secret_is_a_config_error(respx_mock, monkeypatch):
    from usethatapp import config as uta_config

    monkeypatch.delenv("UTA_CLIENT_SECRET", raising=False)
    uta_config.reset_cache()
    with pytest.raises(UtaConfigError, match="UTA_CLIENT_SECRET"):
        validate_license_key("key_abc")


def test_rejected_credentials_are_a_config_error(respx_mock):
    respx_mock.post(API_URL + "/api/v1/licenses/validate").mock(
        return_value=httpx.Response(401, json={"error": "invalid_client"})
    )
    with pytest.raises(UtaConfigError, match="credentials rejected"):
        validate_license_key("key_abc")


def test_get_order_returns_the_key(respx_mock):
    respx_mock.get(API_URL + "/api/v1/orders/REF123").mock(
        return_value=httpx.Response(
            200, json={**STATE, "license_key": "key_new"}
        )
    )
    state = get_order("REF123")
    assert state.license_key == "key_new"
    assert state.entitled


def test_get_order_processing_says_retry(respx_mock):
    respx_mock.get(API_URL + "/api/v1/orders/REF123").mock(
        return_value=httpx.Response(202, json={"status": "processing"})
    )
    with pytest.raises(UtaOrderProcessingError, match="retry"):
        get_order("REF123")


def test_get_order_unknown(respx_mock):
    respx_mock.get(API_URL + "/api/v1/orders/BAD").mock(
        return_value=httpx.Response(404, json={"error": "unknown_order"})
    )
    with pytest.raises(UtaNotFoundError) as excinfo:
        get_order("BAD")
    assert excinfo.value.code == "unknown_order"


def test_get_order_urlencodes_the_ref(respx_mock):
    route = respx_mock.get(
        API_URL + "/api/v1/orders/a%3Ab%3Ac"
    ).mock(return_value=httpx.Response(200, json=STATE))
    get_order("a:b:c")
    assert route.called


def test_regenerate_returns_the_new_key(respx_mock):
    lid = STATE["license_id"]
    respx_mock.post(
        API_URL + f"/api/v1/licenses/{lid}/regenerate-key"
    ).mock(return_value=httpx.Response(200, json={
        **STATE, "license_key": "key_rotated",
        "rotated_at": "2026-08-20T01:02:03+00:00",
    }))
    state = regenerate_license_key(lid)
    assert state.license_key == "key_rotated"
    assert state.rotated_at is not None


def test_regenerate_canceled_license(respx_mock):
    lid = STATE["license_id"]
    respx_mock.post(
        API_URL + f"/api/v1/licenses/{lid}/regenerate-key"
    ).mock(return_value=httpx.Response(409, json={"error": "license_canceled"}))
    with pytest.raises(UtaLicenseCanceledError):
        regenerate_license_key(lid)


def test_regenerate_unknown_license(respx_mock):
    lid = STATE["license_id"]
    respx_mock.post(
        API_URL + f"/api/v1/licenses/{lid}/regenerate-key"
    ).mock(return_value=httpx.Response(404, json={"error": "unknown_license"}))
    with pytest.raises(UtaNotFoundError) as excinfo:
        regenerate_license_key(lid)
    assert excinfo.value.code == "unknown_license"


def test_server_errors_are_retriable(respx_mock):
    respx_mock.post(API_URL + "/api/v1/licenses/validate").mock(
        return_value=httpx.Response(503, text="down")
    )
    with pytest.raises(UtaServerError):
        validate_license_key("key_abc")


def test_empty_inputs_are_rejected_locally():
    with pytest.raises(UtaError):
        validate_license_key("")
    with pytest.raises(UtaError):
        get_order("")
    with pytest.raises(UtaError):
        regenerate_license_key("")
