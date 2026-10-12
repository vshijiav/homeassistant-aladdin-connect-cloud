"""Exercise the cloud HTTP contract using Home Assistant's HTTP mocker."""

import asyncio
import base64
import hashlib
import hmac
import ssl
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import (
    ClientConnectionError,
    ClientConnectorCertificateError,
    ClientConnectorDNSError,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse
from yarl import URL

from custom_components.aladdin_connect_cloud.api import (
    AladdinAuthError,
    AladdinChallengeError,
    AladdinClient,
    AladdinCommandError,
    AladdinConnectionError,
    AladdinError,
    DoorStatus,
    parse_doors,
)
from custom_components.aladdin_connect_cloud.const import (
    API_BASE_URL,
    AUTH_CLIENT_ID,
    AUTH_CLIENT_SECRET,
    AUTH_URL,
)


def auth_payload(token="test-access-token", expires=3600):
    return {"AuthenticationResult": {"AccessToken": token, "ExpiresIn": expires}}


def calls(mocked, method, url):
    return [call for call in mocked.mock_calls if call[0] == method and call[1] == URL(url)]


def sequence(mocked, method, url, *responses):
    """Queue responses to test expired tokens without a real socket."""
    mocked.request(
        method,
        url,
        side_effect=AsyncMock(
            side_effect=[
                AiohttpClientMockResponse(method, URL(url), **response) for response in responses
            ]
        ),
    )


async def test_login_contract_and_concurrent_token_cache(hass, aioclient_mock, devices_payload):
    """Concurrent reads share login; the secret hash matches the Cognito contract."""
    mocked = aioclient_mock
    mocked.post(AUTH_URL, json=auth_payload())
    mocked.get(f"{API_BASE_URL}/devices", json=devices_payload)
    client = AladdinClient(async_get_clientsession(hass), "owner@example.com", "example-password")
    results = await asyncio.gather(*(client.async_get_doors() for _ in range(4)))
    assert all(len(result) == 3 for result in results)
    auth_calls = calls(mocked, "POST", AUTH_URL)
    assert len(auth_calls) == 1
    params = auth_calls[0][2]
    assert params["AuthFlow"] == "USER_PASSWORD_AUTH"
    assert params["AuthParameters"] == {
        "USERNAME": "owner@example.com",
        "PASSWORD": "example-password",
        "SECRET_HASH": base64.b64encode(
            hmac.new(
                AUTH_CLIENT_SECRET.encode(),
                ("owner@example.com" + AUTH_CLIENT_ID).encode(),
                hashlib.sha256,
            ).digest()
        ).decode(),
    }
    read_calls = calls(mocked, "GET", f"{API_BASE_URL}/devices")
    assert read_calls[0][3]["Authorization"] == "Bearer test-access-token"


async def test_token_expiration_relogs_in(hass, aioclient_mock, devices_payload):
    sequence(
        aioclient_mock,
        "POST",
        AUTH_URL,
        {"json": auth_payload("first")},
        {"json": auth_payload("second")},
    )
    aioclient_mock.get(f"{API_BASE_URL}/devices", json=devices_payload)
    client = AladdinClient(async_get_clientsession(hass), "owner", "password")
    await client.async_get_doors()
    client._expires_at = 0
    await client.async_get_doors()
    assert len(calls(aioclient_mock, "POST", AUTH_URL)) == 2
    assert (
        calls(aioclient_mock, "GET", f"{API_BASE_URL}/devices")[-1][3]["Authorization"]
        == "Bearer second"
    )


async def test_read_401_renews_once(hass, aioclient_mock, devices_payload):
    aioclient_mock.post(AUTH_URL, json=auth_payload())
    sequence(
        aioclient_mock, "GET", f"{API_BASE_URL}/devices", {"status": 401}, {"json": devices_payload}
    )
    result = await AladdinClient(
        async_get_clientsession(hass), "owner", "password"
    ).async_get_doors()
    assert result["101:1"].status == DoorStatus.CLOSED
    assert len(calls(aioclient_mock, "GET", f"{API_BASE_URL}/devices")) == 2
    assert len(calls(aioclient_mock, "POST", AUTH_URL)) == 2


async def test_read_persistent_401_is_auth_failure(hass, aioclient_mock):
    aioclient_mock.post(AUTH_URL, json=auth_payload())
    aioclient_mock.get(f"{API_BASE_URL}/devices", status=401)
    with pytest.raises(AladdinAuthError):
        await AladdinClient(async_get_clientsession(hass), "owner", "password").async_get_doors()
    assert len(calls(aioclient_mock, "POST", AUTH_URL)) == 2


@pytest.mark.parametrize("open_door,command", [(True, "OPEN_DOOR"), (False, "CLOSE_DOOR")])
async def test_door_commands_use_index_and_accept_empty_success(
    hass,
    aioclient_mock,
    doors,
    open_door,
    command,
):
    aioclient_mock.post(AUTH_URL, json=auth_payload())
    url = f"{API_BASE_URL}/command/devices/101/doors/1"
    aioclient_mock.post(url, status=204)
    await AladdinClient(async_get_clientsession(hass), "owner", "password").async_set_door(
        doors["101:1"],
        open_door=open_door,
    )
    requests = calls(aioclient_mock, "POST", url)
    assert len(requests) == 1
    assert requests[0][2] == {"command": command}


@pytest.mark.parametrize("failure", [TimeoutError(), ClientConnectionError(), 500, 401, 403])
async def test_failed_command_is_never_replayed(hass, aioclient_mock, doors, failure):
    aioclient_mock.post(AUTH_URL, json=auth_payload())
    url = f"{API_BASE_URL}/command/devices/101/doors/1"
    aioclient_mock.post(
        url, **({"exc": failure} if isinstance(failure, Exception) else {"status": failure})
    )
    expected = AladdinAuthError if failure == 401 else AladdinCommandError
    with pytest.raises(expected):
        await AladdinClient(async_get_clientsession(hass), "owner", "password").async_set_door(
            doors["101:1"],
            open_door=True,
        )
    assert len(calls(aioclient_mock, "POST", url)) == 1
    assert len(calls(aioclient_mock, "POST", AUTH_URL)) == 1


@pytest.mark.parametrize(
    "status,payload,error",
    [
        (400, {"__type": "NotAuthorizedException", "message": "secret"}, AladdinAuthError),
        (400, {"__type": "TooManyRequestsException"}, AladdinConnectionError),
        (200, {"ChallengeName": "SMS_MFA"}, AladdinChallengeError),
        (200, {}, AladdinConnectionError),
        (200, auth_payload(expires=-1), AladdinConnectionError),
        (200, auth_payload(token=""), AladdinConnectionError),
        (200, [], AladdinConnectionError),
        (503, {}, AladdinConnectionError),
    ],
)
async def test_auth_failures_are_distinct_and_redacted(
    hass, aioclient_mock, status, payload, error
):
    aioclient_mock.post(AUTH_URL, status=status, json=payload)
    with pytest.raises(error) as exc:
        await AladdinClient(async_get_clientsession(hass), "owner", "password").async_get_doors()
    assert "secret" not in str(exc.value)
    assert "password" not in str(exc.value)


@pytest.mark.parametrize(
    "response",
    [
        {"status": 503},
        {"status": 403},
        {"text": "not json"},
        {"exc": ClientConnectionError()},
    ],
)
async def test_read_transport_and_response_failures(hass, aioclient_mock, response):
    aioclient_mock.post(AUTH_URL, json=auth_payload())
    aioclient_mock.get(f"{API_BASE_URL}/devices", **response)
    with pytest.raises(AladdinConnectionError):
        await AladdinClient(async_get_clientsession(hass), "owner", "password").async_get_doors()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"devices": None},
        {"devices": [None]},
        {"devices": [{"id": 1, "doors": None}]},
        {"devices": [{"id": 1, "doors": [None]}]},
        {"devices": [{"id": 1, "doors": [{"id": None, "door_index": 1}]}]},
    ],
)
def test_malformed_device_data_is_not_an_empty_success(payload):
    with pytest.raises(AladdinConnectionError):
        parse_doors(payload)


def test_unknown_status_and_disconnected_battery(devices_payload):
    raw = devices_payload["devices"][0]["doors"][0]
    raw["status"] = 999
    raw["link_status"] = 2
    door = parse_doors(devices_payload)["101:1"]
    assert door.status == DoorStatus.UNKNOWN
    assert door.battery_percent is None
    assert door.battery_level == 60


def test_empty_device_list_is_valid():
    assert parse_doors({"devices": []}) == {}


@pytest.mark.parametrize(
    "device_id", ["101", "F0AD4E1BC74D", "01ab23cd-4567-89ab-cdef-0123456789ab"]
)
async def test_string_device_ids_preserve_identity_and_command_path(
    hass, aioclient_mock, devices_payload, device_id
):
    """Opaque IDs are accepted without an integer conversion during discovery."""
    devices_payload["devices"][0]["id"] = device_id
    aioclient_mock.post(AUTH_URL, json=auth_payload())
    aioclient_mock.get(f"{API_BASE_URL}/devices", json=devices_payload)
    client = AladdinClient(async_get_clientsession(hass), "owner", "password")
    doors = await client.async_get_doors()
    door = doors[f"{device_id}:1"]
    assert door.device_id == device_id
    url = f"{API_BASE_URL}/command/devices/{device_id}/doors/1"
    aioclient_mock.post(url, status=204)
    await client.async_set_door(door, open_door=True)
    assert len(calls(aioclient_mock, "POST", url)) == 1


@pytest.mark.parametrize("device_id", [True, 1.5, None, "", "../private@example.com", -1])
def test_invalid_device_id_reports_field_without_echoing_value(devices_payload, device_id):
    devices_payload["devices"][0]["id"] = device_id
    with pytest.raises(AladdinConnectionError) as exc:
        parse_doors(devices_payload)
    assert exc.value.safe_diagnostic == "stage=devices; reason=invalid_response; field=device.id"


def test_missing_door_index_reports_field(devices_payload):
    del devices_payload["devices"][0]["doors"][0]["door_index"]
    with pytest.raises(AladdinConnectionError) as exc:
        parse_doors(devices_payload)
    assert exc.value.safe_diagnostic == (
        "stage=devices; reason=invalid_response; field=door.door_index"
    )


@pytest.mark.parametrize(
    "failure,reason",
    [
        (ClientConnectorDNSError(Mock(), OSError("private@example.com")), "dns"),
        (ClientConnectorCertificateError(Mock(), ssl.CertificateError("private-token")), "tls"),
        (TimeoutError("private-password"), "timeout"),
        (ClientConnectionError("private-token"), "connection"),
    ],
)
@pytest.mark.parametrize("stage", ["authentication", "devices"])
async def test_transport_diagnostic_distinguishes_stage_and_reason(
    hass, aioclient_mock, failure, reason, stage
):
    if stage == "authentication":
        aioclient_mock.post(AUTH_URL, exc=failure)
    else:
        aioclient_mock.post(AUTH_URL, json=auth_payload())
        aioclient_mock.get(f"{API_BASE_URL}/devices", exc=failure)
    with pytest.raises(AladdinConnectionError) as exc:
        await AladdinClient(async_get_clientsession(hass), "owner", "password").async_get_doors()
    assert exc.value.safe_diagnostic == f"stage={stage}; reason={reason}"
    assert "private" not in str(exc.value)


def test_diagnostic_allowlist_never_echoes_exception_or_untrusted_labels():
    err = AladdinError(
        "private-password",
        stage="private@example.com",
        reason="private-token",
        field="private-device-id",
        status=1000,
    )
    assert err.safe_diagnostic == "stage=unknown; reason=unknown"
