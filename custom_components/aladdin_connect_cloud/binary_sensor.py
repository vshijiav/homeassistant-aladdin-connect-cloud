"""Fault and low-battery entities."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Door
from .const import CONF_BATTERY_LOW_LEVEL, DEFAULT_BATTERY_LOW_LEVEL
from .coordinator import AladdinConfigEntry, AladdinCoordinator
from .entity import AladdinEntity, async_add_discovered_entities

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AladdinConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    threshold = entry.options.get(CONF_BATTERY_LOW_LEVEL, DEFAULT_BATTERY_LOW_LEVEL)

    def factory(door: Door) -> list[BinarySensorEntity]:
        entities: list[BinarySensorEntity] = [AladdinProblemSensor(coordinator, door)]
        if door.battery_level:
            entities.append(AladdinLowBatterySensor(coordinator, door, threshold))
        return entities

    async_add_discovered_entities(coordinator, entry, async_add_entities, factory)


class AladdinProblemSensor(AladdinEntity, BinarySensorEntity):
    """The API reports faults and timeouts, not a physical obstruction sensor."""

    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AladdinCoordinator, door: Door) -> None:
        super().__init__(coordinator, door, "problem")

    @property
    def is_on(self) -> bool:
        return self.door.problem


class AladdinLowBatterySensor(AladdinEntity, BinarySensorEntity):
    """Expose the configurable upstream low-battery threshold."""

    _attr_translation_key = "low_battery"
    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AladdinCoordinator, door: Door, threshold: int) -> None:
        super().__init__(coordinator, door, "low_battery")
        self._threshold = threshold

    @property
    def is_on(self) -> bool | None:
        if (level := self.door.battery_percent) is None:
            return None
        return level <= self._threshold
