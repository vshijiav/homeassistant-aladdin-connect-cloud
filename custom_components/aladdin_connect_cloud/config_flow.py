"""UI setup, reauthentication, and options for Aladdin Connect Cloud."""

from collections.abc import Mapping
from typing import Any

try:
    import probatio as vol
except ImportError:  # HA releases before the schema library migration.
    import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AladdinAuthError, AladdinChallengeError, AladdinClient, AladdinError
from .const import (
    CONF_BATTERY_LOW_LEVEL,
    CONF_IGNORED_DOORS,
    CONF_SHOW_SHARED,
    DEFAULT_BATTERY_LOW_LEVEL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    NAME,
)


def _password_selector() -> selector.TextSelector:
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )


class AladdinConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Validate credentials and the devices API before persisting an account."""

    VERSION = 1

    async def _validate(self, username: str, password: str) -> str | None:
        client = AladdinClient(async_get_clientsession(self.hass), username, password)
        try:
            doors = await client.async_get_doors()
        except AladdinChallengeError:
            return "auth_challenge"
        except AladdinAuthError:
            return "invalid_auth"
        except AladdinError:
            return "cannot_connect"
        return None if doors else "no_doors"

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        errors = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.casefold())
            self._abort_if_unique_id_configured()
            if error := await self._validate(username, user_input[CONF_PASSWORD]):
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=f"{NAME} ({username})",
                    data={CONF_USERNAME: username, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
                    ),
                    vol.Required(CONF_PASSWORD): _password_selector(),
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],
    ) -> config_entries.ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            if error := await self._validate(entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]):
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): _password_selector()}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            if error := await self._validate(entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]):
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): _password_selector()}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "AladdinOptionsFlow":
        return AladdinOptionsFlow()


class AladdinOptionsFlow(config_entries.OptionsFlow):
    """Set polling, shared-door visibility, ignored IDs, and battery threshold."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        options = self.config_entry.options
        coordinator = getattr(self.config_entry, "runtime_data", None)
        door_options = [
            {"value": door.door_id, "label": f"{door.name} ({door.door_id})"}
            for door in (coordinator.all_doors.values() if coordinator else [])
        ]
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_POLL_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=5, max=60)),
                    vol.Optional(
                        CONF_SHOW_SHARED,
                        default=options.get(CONF_SHOW_SHARED, False),
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_IGNORED_DOORS,
                        default=options.get(CONF_IGNORED_DOORS, []),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=door_options,
                            multiple=True,
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_BATTERY_LOW_LEVEL,
                        default=options.get(CONF_BATTERY_LOW_LEVEL, DEFAULT_BATTERY_LOW_LEVEL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                }
            ),
        )
