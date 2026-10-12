"""Set up the Aladdin Connect Cloud custom integration."""

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AladdinClient
from .coordinator import AladdinConfigEntry, AladdinCoordinator

PLATFORMS = [Platform.COVER, Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: AladdinConfigEntry) -> bool:
    """Validate the account, then set up its entities."""
    client = AladdinClient(
        async_get_clientsession(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = AladdinCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: AladdinConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AladdinConfigEntry) -> bool:
    """Unload entities and their coordinator subscriptions."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
