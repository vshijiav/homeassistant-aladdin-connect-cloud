"""Async client ported from homebridge-plugins/homebridge-aladdin-connect.

Derived from src/aladdinConnect.ts at 2fe528a525ffacf5d435569d50a7cf2e4daa87f8.
Modified for Home Assistant: asyncio/aiohttp, token lifetime in seconds, safe
HTTP error handling, and strict response parsing. See the root NOTICE.
"""

import asyncio
import base64
import hashlib
import hmac
import re
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from aiohttp import (
    ClientConnectorDNSError,
    ClientError,
    ClientSession,
    ClientSSLError,
    ClientTimeout,
)

from .const import (
    API_BASE_URL,
    AUTH_CLIENT_ID,
    AUTH_CLIENT_SECRET,
    AUTH_URL,
    REQUEST_TIMEOUT,
)


class AladdinError(Exception):
    """An API or transport failure with a safe, credential-free message."""

    def __init__(
        self,
        message: str = "",
        *,
        stage: str = "unknown",
        reason: str = "unknown",
        status: int | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.reason = reason
        self.status = status
        self.field = field

    @property
    def safe_diagnostic(self) -> str:
        """Only emit code-owned labels; never echo an exception or API body."""
        stages = {"authentication", "devices", "command"}
        reasons = {
            "dns",
            "tls",
            "timeout",
            "connection",
            "http",
            "rate_limit",
            "permission",
            "invalid_json",
            "invalid_response",
            "credentials",
            "challenge",
        }
        fields = {
            "devices",
            "device",
            "device.id",
            "device.doors",
            "door",
            "door.id",
            "door.door_index",
            "door.status",
            "door.battery_level",
            "door.link_status",
            "door.identity",
            "AuthenticationResult",
            "AccessToken",
            "ExpiresIn",
        }
        stage = self.stage if self.stage in stages else "unknown"
        reason = self.reason if self.reason in reasons else "unknown"
        detail = f"stage={stage}; reason={reason}"
        if isinstance(self.status, int) and 100 <= self.status <= 599:
            detail += f"; HTTP={self.status}"
        if self.field in fields:
            detail += f"; field={self.field}"
        return detail


class AladdinAuthError(AladdinError):
    """The credentials or authorization are invalid."""


class AladdinChallengeError(AladdinAuthError):
    """Cognito requires a challenge this client cannot complete."""


class AladdinConnectionError(AladdinError):
    """The cloud cannot be reached or returned invalid data."""


class AladdinCommandError(AladdinError):
    """A command was rejected, or its delivery cannot be confirmed."""


class _UnauthorizedError(AladdinError):
    """The API rejected the current access token."""


class DoorStatus(IntEnum):
    """Status values reported by the Genie app API."""

    UNKNOWN = 0
    OPEN = 1
    OPENING = 2
    TIMEOUT_OPENING = 3
    CLOSED = 4
    CLOSING = 5
    TIMEOUT_CLOSING = 6
    NOT_CONFIGURED = 7


@dataclass(frozen=True, slots=True)
class Door:
    """A door and the device metadata needed by Home Assistant."""

    device_id: int | str
    door_id: str
    index: int
    serial_number: str
    name: str
    device_name: str
    model: str
    software_version: str | None
    ownership: str
    status: DoorStatus
    battery_level: int | None
    link_status: int | None
    fault: bool
    enabled: bool

    @property
    def unique_id(self) -> str:
        """Use the same stable device/door identity as the original plugin."""
        return f"{self.device_id}:{self.index}"

    @property
    def battery_percent(self) -> int | None:
        """Match upstream: zero also means this model has no battery."""
        if self.link_status != 3 or not self.battery_level:
            return None
        return self.battery_level

    @property
    def problem(self) -> bool:
        """Report a fault or a timed-out door movement."""
        return self.fault or self.status in (
            DoorStatus.TIMEOUT_OPENING,
            DoorStatus.TIMEOUT_CLOSING,
        )


def parse_doors(payload: Any) -> dict[str, Door]:
    """Parse cloud data; never turn malformed/missing data into a closed door."""
    if not isinstance(payload, dict) or not isinstance(payload.get("devices"), list):
        raise AladdinConnectionError(
            "Invalid device list returned by Genie",
            stage="devices",
            reason="invalid_response",
            field="devices",
        )
    result: dict[str, Door] = {}
    field = "device"
    try:
        for device in payload["devices"]:
            field = "device"
            if not isinstance(device, dict):
                raise TypeError
            field = "device.id"
            device_id = device["id"]
            # TypeScript's `id: number` annotation never coerced the upstream
            # JSON at runtime. Preserve numeric and opaque string identifiers.
            if isinstance(device_id, bool):
                raise ValueError
            if isinstance(device_id, int):
                if device_id < 0:
                    raise ValueError
            elif not isinstance(device_id, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9:_-]*",
                device_id,
            ):
                raise ValueError
            field = "device.doors"
            doors = device["doors"]
            if not isinstance(doors, list):
                raise TypeError
            for raw in doors:
                field = "door"
                if not isinstance(raw, dict):
                    raise TypeError
                field = "door.door_index"
                index = int(raw["door_index"])
                if index < 0:
                    raise ValueError
                field = "door.id"
                door_id = str(raw["id"])
                if not door_id or raw["id"] is None:
                    raise ValueError
                field = "door.status"
                try:
                    status = DoorStatus(int(raw.get("status") or 0))
                except ValueError:
                    status = DoorStatus.UNKNOWN
                field = "door.battery_level"
                battery = raw.get("battery_level")
                battery = None if battery is None else max(0, min(100, int(battery)))
                field = "door.link_status"
                link_status = (
                    int(raw["link_status"]) if raw.get("link_status") is not None else None
                )
                door = Door(
                    device_id=device_id,
                    door_id=door_id,
                    index=index,
                    serial_number=str(device.get("serial_number") or device_id),
                    name=str(raw.get("name") or "Garage door"),
                    device_name=str(device.get("name") or "Aladdin Connect"),
                    model=str(device.get("model") or "Aladdin Connect"),
                    software_version=device.get("software_version") or None,
                    ownership=str(device.get("ownership") or "unknown"),
                    status=status,
                    battery_level=battery,
                    link_status=link_status,
                    fault=bool(raw.get("fault")),
                    enabled=(
                        device.get("is_enabled", True) is not False
                        and raw.get("is_enabled", True) is not False
                    ),
                )
                field = "door.identity"
                if door.unique_id in result:
                    raise ValueError
                result[door.unique_id] = door
    except (KeyError, TypeError, ValueError, OverflowError) as err:
        raise AladdinConnectionError(
            "Invalid door data returned by Genie",
            stage="devices",
            reason="invalid_response",
            field=field,
        ) from err
    return result


class AladdinClient:
    """Use the HA-managed session, keeping credentials and tokens out of logs."""

    def __init__(self, session: ClientSession, username: str, password: str) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._auth_lock = asyncio.Lock()

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        auth: bool = False,
        command: bool = False,
    ) -> Any:
        """Send one request, without logging bodies or retrying door commands."""
        stage = "authentication" if auth else "command" if command else "devices"
        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=payload,
                timeout=ClientTimeout(total=REQUEST_TIMEOUT),
                allow_redirects=False,
            ) as response:
                if response.status == 401 and not auth:
                    raise _UnauthorizedError("Access token rejected", stage=stage, status=401)
                if response.status == 403 and not auth:
                    # A permission denial must not cause credential re-entry or
                    # automatically resubmit a physical door command.
                    if command:
                        raise AladdinCommandError(
                            "No permission to operate this door",
                            stage=stage,
                            reason="permission",
                            status=403,
                        )
                    raise AladdinConnectionError(
                        "Genie denied access to the device list",
                        stage=stage,
                        reason="permission",
                        status=403,
                    )
                if response.status >= 400 or 300 <= response.status < 400:
                    if auth and response.status in (400, 401, 403):
                        try:
                            data = await response.json(content_type=None)
                        except (ValueError, ClientError):
                            data = {}
                        code = str(data.get("__type", "")) if isinstance(data, dict) else ""
                        if code.endswith(("TooManyRequestsException", "LimitExceededException")):
                            raise AladdinConnectionError(
                                "Cognito request limit reached",
                                stage=stage,
                                reason="rate_limit",
                                status=response.status,
                            )
                        raise AladdinAuthError(
                            "Cognito rejected the account credentials",
                            stage=stage,
                            reason="credentials",
                            status=response.status,
                        )
                    error_type = AladdinCommandError if command else AladdinConnectionError
                    raise error_type(
                        f"Cloud request failed (HTTP {response.status})",
                        stage=stage,
                        reason="http",
                        status=response.status,
                    )
                if command:
                    # Upstream does not depend on the response body. Accept a
                    # successful HTTP status, including an empty 204 response.
                    return None
                try:
                    return await response.json(content_type=None)
                except (ValueError, ClientError) as err:
                    raise AladdinConnectionError(
                        "Cloud returned invalid JSON",
                        stage=stage,
                        reason="invalid_json",
                        status=response.status,
                    ) from err
        except (ClientError, TimeoutError) as err:
            if isinstance(err, ClientConnectorDNSError):
                reason = "dns"
            elif isinstance(err, ClientSSLError):
                reason = "tls"
            elif isinstance(err, TimeoutError):
                reason = "timeout"
            else:
                reason = "connection"
            if command:
                raise AladdinCommandError(
                    "Command delivery is uncertain; check the door before trying again",
                    stage=stage,
                    reason=reason,
                ) from err
            raise AladdinConnectionError(
                "Unable to reach the Genie cloud service",
                stage=stage,
                reason=reason,
            ) from err

    async def _get_access_token(self) -> str:
        """Re-login only when needed; serialize simultaneous token requests."""
        async with self._auth_lock:
            if self._access_token and time.monotonic() < self._expires_at:
                return self._access_token
            secret_hash = base64.b64encode(
                hmac.new(
                    AUTH_CLIENT_SECRET.encode(),
                    (self._username + AUTH_CLIENT_ID).encode(),
                    hashlib.sha256,
                ).digest()
            ).decode()
            data = await self._request_json(
                "POST",
                AUTH_URL,
                headers={
                    "Content-Type": "application/x-amz-json-1.1",
                    "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
                },
                payload={
                    "ClientId": AUTH_CLIENT_ID,
                    "AuthFlow": "USER_PASSWORD_AUTH",
                    "AuthParameters": {
                        "USERNAME": self._username,
                        "PASSWORD": self._password,
                        "SECRET_HASH": secret_hash,
                    },
                },
                auth=True,
            )
            if not isinstance(data, dict):
                raise AladdinConnectionError(
                    "Invalid authentication response",
                    stage="authentication",
                    reason="invalid_response",
                    field="AuthenticationResult",
                )
            if data.get("ChallengeName"):
                raise AladdinChallengeError(
                    "Complete the account challenge in the Aladdin Connect app",
                    stage="authentication",
                    reason="challenge",
                )
            field = "AuthenticationResult"
            try:
                result = data["AuthenticationResult"]
                field = "AccessToken"
                token = result["AccessToken"]
                if not isinstance(token, str) or not token:
                    raise ValueError
                field = "ExpiresIn"
                lifetime = float(result["ExpiresIn"])
                if not 0 < lifetime < float("inf"):
                    raise ValueError
            except (KeyError, TypeError, ValueError) as err:
                raise AladdinConnectionError(
                    "Invalid authentication result",
                    stage="authentication",
                    reason="invalid_response",
                    field=field,
                ) from err
            self._access_token = token
            self._expires_at = time.monotonic() + max(0, lifetime - 30)
            return token

    async def _invalidate_token(self, rejected_token: str) -> None:
        async with self._auth_lock:
            if self._access_token == rejected_token:
                self._access_token = None
                self._expires_at = 0.0

    async def async_get_doors(self) -> dict[str, Door]:
        """Read devices; retry a rejected token once because this is read-only."""
        for attempt in range(2):
            token = await self._get_access_token()
            try:
                data = await self._request_json(
                    "GET",
                    f"{API_BASE_URL}/devices",
                    headers={"Authorization": f"Bearer {token}"},
                )
                return parse_doors(data)
            except _UnauthorizedError as err:
                await self._invalidate_token(token)
                if attempt:
                    raise AladdinAuthError(
                        "Genie rejected a new access token",
                        stage="devices",
                        reason="credentials",
                        status=401,
                    ) from err
        raise AssertionError("Unreachable")

    async def async_set_door(self, door: Door, *, open_door: bool) -> None:
        """Issue one physical command; never replay a failed/ambiguous POST."""
        token = await self._get_access_token()
        try:
            await self._request_json(
                "POST",
                f"{API_BASE_URL}/command/devices/{door.device_id}/doors/{door.index}",
                headers={"Authorization": f"Bearer {token}"},
                payload={"command": "OPEN_DOOR" if open_door else "CLOSE_DOOR"},
                command=True,
            )
        except _UnauthorizedError as err:
            await self._invalidate_token(token)
            raise AladdinAuthError(
                "Genie rejected the access token",
                stage="command",
                reason="credentials",
                status=401,
            ) from err
