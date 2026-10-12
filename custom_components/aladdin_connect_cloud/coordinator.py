"""Shared polling and command handling for an Aladdin Connect account."""

import asyncio
import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AladdinAuthError, AladdinClient, AladdinError, Door, DoorStatus
from .const import (
    COMMAND_TRACKING_SECONDS,
    CONF_IGNORED_DOORS,
    CONF_SHOW_SHARED,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MOVING_POLL_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class AladdinCoordinator(DataUpdateCoordinator[dict[str, Door]]):
    """Keep a single uncached cloud snapshot for all entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: AladdinClient,
    ) -> None:
        self.client = client
        self.all_doors: dict[str, Door] = {}
        self.poll_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_POLL_INTERVAL)
        self._show_shared = entry.options.get(CONF_SHOW_SHARED, False)
        self._ignored = set(entry.options.get(CONF_IGNORED_DOORS, []))
        self._command_lock = asyncio.Lock()
        self._pending: dict[str, tuple[DoorStatus, float]] = {}
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=self.poll_interval),
            always_update=False,
        )

    async def _async_update_data(self) -> dict[str, Door]:
        try:
            all_doors = await self.client.async_get_doors()
        except AladdinAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AladdinError as err:
            raise UpdateFailed(str(err)) from err
        self.all_doors = all_doors
        doors = {
            key: door
            for key, door in all_doors.items()
            if (self._show_shared or door.ownership == "owned")
            and door.door_id not in self._ignored
        }
        now = time.monotonic()
        self._pending = {
            key: (target, deadline)
            for key, (target, deadline) in self._pending.items()
            if key in doors and now < deadline and doors[key].status != target
        }
        moving = any(
            door.status in (DoorStatus.OPENING, DoorStatus.CLOSING) for door in doors.values()
        )
        self.update_interval = timedelta(
            seconds=min(self.poll_interval, MOVING_POLL_INTERVAL)
            if moving or self._pending
            else self.poll_interval
        )
        return doors

    async def async_command(self, unique_id: str, *, open_door: bool) -> None:
        """Send a command, trigger reauth when needed, then refresh real state."""
        async with self._command_lock:
            door = self.data.get(unique_id)
            if not self.last_update_success or door is None or not door.enabled:
                raise HomeAssistantError("This garage door is unavailable")
            try:
                await self.client.async_set_door(door, open_door=open_door)
            except AladdinAuthError as err:
                self.config_entry.async_start_reauth(self.hass)
                self.async_set_update_error(UpdateFailed("Authentication required"))
                raise HomeAssistantError("Reauthenticate the Aladdin Connect account") from err
            except AladdinError as err:
                raise HomeAssistantError(str(err)) from err
            self._pending[unique_id] = (
                DoorStatus.OPEN if open_door else DoorStatus.CLOSED,
                time.monotonic() + COMMAND_TRACKING_SECONDS,
            )
            self.update_interval = timedelta(seconds=min(self.poll_interval, MOVING_POLL_INTERVAL))
            await self.async_request_refresh()


type AladdinConfigEntry = ConfigEntry[AladdinCoordinator]
