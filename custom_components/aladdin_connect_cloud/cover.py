"""Expose each door as a Home Assistant garage cover."""

from typing import Any

from homeassistant.components.cover import CoverDeviceClass, CoverEntity, CoverEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Door, DoorStatus
from .coordinator import AladdinConfigEntry, AladdinCoordinator
from .entity import AladdinEntity, async_add_discovered_entities

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AladdinConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_discovered_entities(
        coordinator,
        entry,
        async_add_entities,
        lambda door: [AladdinGarageDoor(coordinator, door)],
    )


class AladdinGarageDoor(AladdinEntity, CoverEntity):
    """Only support operations present in the original cloud API."""

    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
    _attr_name = None

    def __init__(self, coordinator: AladdinCoordinator, door: Door) -> None:
        super().__init__(coordinator, door, "cover")

    @property
    def is_closed(self) -> bool | None:
        if self.door.status == DoorStatus.CLOSED:
            return True
        if self.door.status in (DoorStatus.OPEN, DoorStatus.OPENING, DoorStatus.CLOSING):
            return False
        return None

    @property
    def is_opening(self) -> bool:
        return self.door.status == DoorStatus.OPENING

    @property
    def is_closing(self) -> bool:
        return self.door.status == DoorStatus.CLOSING

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(self._door_key, open_door=True)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(self._door_key, open_door=False)
