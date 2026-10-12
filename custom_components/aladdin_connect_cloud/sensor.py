"""Battery sensors for doors that report a non-zero battery level."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Door
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
        lambda door: [AladdinBatterySensor(coordinator, door)] if door.battery_level else [],
    )


class AladdinBatterySensor(AladdinEntity, SensorEntity):
    """A battery reading is unknown when the sensor is disconnected."""

    _attr_translation_key = "battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AladdinCoordinator, door: Door) -> None:
        super().__init__(coordinator, door, "battery")

    @property
    def native_value(self) -> int | None:
        return self.door.battery_percent
