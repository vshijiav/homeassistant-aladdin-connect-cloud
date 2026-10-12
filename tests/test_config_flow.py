"""Test setup, duplicate detection, options, and credential updates in HA."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aladdin_connect_cloud.api import (
    AladdinAuthError,
    AladdinChallengeError,
    AladdinConnectionError,
)
from custom_components.aladdin_connect_cloud.const import (
    CONF_BATTERY_LOW_LEVEL,
    CONF_IGNORED_DOORS,
    CONF_SHOW_SHARED,
    DOMAIN,
)

CONFIG = {CONF_USERNAME: "Owner@example.com", CONF_PASSWORD: "sample-password"}


async def test_user_flow_validates_devices_and_creates_account(hass, doors):
    with (
        patch("custom_components.aladdin_connect_cloud.config_flow.AladdinClient") as client,
        patch("custom_components.aladdin_connect_cloud.async_setup_entry", return_value=True),
    ):
        client.return_value.async_get_doors = AsyncMock(return_value=doors)
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        assert result["type"] == FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CONFIG)
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == CONFIG
    assert result["result"].unique_id == "owner@example.com"
    client.return_value.async_get_doors.assert_awaited_once()


@pytest.mark.parametrize(
    "failure,expected",
    [
        (AladdinAuthError(), "invalid_auth"),
        (AladdinChallengeError(), "auth_challenge"),
        (AladdinConnectionError(), "cannot_connect"),
        (None, "no_doors"),
    ],
)
async def test_user_flow_recovers_from_validation_errors(hass, doors, failure, expected):
    with patch("custom_components.aladdin_connect_cloud.config_flow.AladdinClient") as client:
        client.return_value.async_get_doors = AsyncMock(side_effect=failure, return_value={})
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=CONFIG,
        )
        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {"base": expected}
        # A retry in the same form can succeed.
        client.return_value.async_get_doors = AsyncMock(return_value=doors)
        with patch("custom_components.aladdin_connect_cloud.async_setup_entry", return_value=True):
            result = await hass.config_entries.flow.async_configure(result["flow_id"], CONFIG)
            await hass.async_block_till_done()
        assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_duplicate_account_is_rejected_without_network(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="owner@example.com", data=CONFIG)
    entry.add_to_hass(hass)
    with patch("custom_components.aladdin_connect_cloud.config_flow.AladdinClient") as client:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={**CONFIG, CONF_USERNAME: " owner@EXAMPLE.com "},
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    client.assert_not_called()


@pytest.mark.parametrize(
    "source,step,reason",
    [
        (config_entries.SOURCE_REAUTH, "reauth_confirm", "reauth_successful"),
        (config_entries.SOURCE_RECONFIGURE, "reconfigure", "reconfigure_successful"),
    ],
)
async def test_password_update_preserves_entry_and_account(hass, doors, source, step, reason):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="owner@example.com", data=CONFIG)
    entry.add_to_hass(hass)
    with (
        patch("custom_components.aladdin_connect_cloud.config_flow.AladdinClient") as client,
        patch.object(hass.config_entries, "async_reload", return_value=True) as reload_entry,
    ):
        client.return_value.async_get_doors = AsyncMock(return_value=doors)
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": source, "entry_id": entry.entry_id},
            data=CONFIG if source == config_entries.SOURCE_REAUTH else None,
        )
        assert result["step_id"] == step
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "updated-password"},
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == reason
    assert entry.data == {**CONFIG, CONF_PASSWORD: "updated-password"}
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    reload_entry.assert_awaited_once_with(entry.entry_id)


async def test_reauth_wrong_password_keeps_existing_data(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="owner@example.com", data=CONFIG)
    entry.add_to_hass(hass)
    with patch("custom_components.aladdin_connect_cloud.config_flow.AladdinClient") as client:
        client.return_value.async_get_doors = AsyncMock(side_effect=AladdinAuthError())
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
            data=CONFIG,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "wrong-password"},
        )
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data == CONFIG


async def test_options_flow_without_loaded_coordinator(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="owner@example.com", data=CONFIG)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    options = {
        CONF_SCAN_INTERVAL: 30,
        CONF_SHOW_SHARED: True,
        CONF_IGNORED_DOORS: ["ABCDEF123456_1"],
        CONF_BATTERY_LOW_LEVEL: 20,
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], options)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options == options
