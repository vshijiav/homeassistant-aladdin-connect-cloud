"""Common entity identity and availability."""

from collections.abc import Callable
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Door
from .const import DOMAIN
from .coordinator import AladdinCoordinator


class AladdinEntity(CoordinatorEntity[AladdinCoordinator]):
    """Read entity properties from a coordinator snapshot only."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AladdinCoordinator, door: Door, suffix: str) -> None:
        super().__init__(coordinator, context=door.unique_id)
        self._door_key = door.unique_id
        self._initial_door = door
        self._attr_unique_id = f"{door.unique_id}_{suffix}"
        # One HA device per logical door: a controller can have multiple doors.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, door.unique_id)},
            manufacturer="Genie",
            model=door.model,
            name=door.name,
            serial_number=f"{door.serial_number}:{door.index}",
            sw_version=door.software_version,
        )

    @property
    def door(self) -> Door:
        """Retain metadata while a removed door is marked unavailable."""
        return self.coordinator.data.get(self._door_key, self._initial_door)

    @property
    def available(self) -> bool:
        return super().available and self._door_key in self.coordinator.data and self.door.enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "door_id": self.door.door_id,
            "device_id": self.door.device_id,
            "door_index": self.door.index,
            "ownership": self.door.ownership,
            "aladdin_status": self.door.status.name.lower(),
        }


def async_add_discovered_entities(
    coordinator: AladdinCoordinator,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[Door], list[Entity]],
) -> None:
    """Add newly discovered doors and late-appearing battery entities once."""
    known_entities: set[str] = set()

    @callback
    def add_entities() -> None:
        new_entities = []
        for door in coordinator.data.values():
            for entity in factory(door):
                if (unique_id := entity.unique_id) not in known_entities:
                    known_entities.add(unique_id)
                    new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(add_entities))
    add_entities()
