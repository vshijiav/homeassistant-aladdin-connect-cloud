"""Exercise actual HA setup, cover services, discovery, and unavailable states."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aladdin_connect_cloud.api import (
    AladdinAuthError,
    AladdinClient,
    AladdinCommandError,
    AladdinConnectionError,
    DoorStatus,
)
from custom_components.aladdin_connect_cloud.const import (
    CONF_BATTERY_LOW_LEVEL,
    CONF_IGNORED_DOORS,
    CONF_SHOW_SHARED,
    DOMAIN,
)


@pytest.fixture
def entry(hass):
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="owner@example.com",
        title="Aladdin Connect Cloud",
        data={CONF_USERNAME: "owner@example.com", CONF_PASSWORD: "sample-password"},
    )
    config_entry.add_to_hass(hass)
    return config_entry


@pytest.fixture
async def loaded(hass, entry, doors):
    client = AsyncMock(spec=AladdinClient)
    client.async_get_doors.return_value = doors
    with patch("custom_components.aladdin_connect_cloud.AladdinClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry, client
        if entry.state == ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_setup_entities_and_device_identity(hass, loaded):
    entry, _ = loaded
    assert entry.state == ConfigEntryState.LOADED
    main = hass.states.get("cover.main_garage")
    assert main.state == "closed"
    assert main.attributes["supported_features"] == 3
    assert main.attributes["device_class"] == "garage"
    assert main.attributes["door_index"] == 1
    assert hass.states.get("cover.side_garage").state == "open"
    assert hass.states.get("cover.shared_garage") is None
    assert hass.states.get("sensor.main_garage_battery").state == "60"
    assert hass.states.get("binary_sensor.main_garage_low_battery").state == "off"
    assert hass.states.get("binary_sensor.main_garage_door_fault").state == "off"
    assert hass.states.get("sensor.side_garage_battery") is None


@pytest.mark.parametrize(
    "status,expected,problem",
    [
        (DoorStatus.OPEN, "open", "off"),
        (DoorStatus.OPENING, "opening", "off"),
        (DoorStatus.CLOSED, "closed", "off"),
        (DoorStatus.CLOSING, "closing", "off"),
        (DoorStatus.UNKNOWN, "unknown", "off"),
        (DoorStatus.NOT_CONFIGURED, "unknown", "off"),
        (DoorStatus.TIMEOUT_OPENING, "unknown", "on"),
        (DoorStatus.TIMEOUT_CLOSING, "unknown", "on"),
    ],
)
async def test_cover_states_do_not_guess_position(hass, loaded, status, expected, problem):
    entry, _ = loaded
    coordinator = entry.runtime_data
    coordinator.async_set_updated_data(
        {
            **coordinator.data,
            "101:1": replace(coordinator.data["101:1"], status=status),
        }
    )
    assert hass.states.get("cover.main_garage").state == expected
    assert hass.states.get("binary_sensor.main_garage_door_fault").state == problem


@pytest.mark.parametrize("service,open_door", [("open_cover", True), ("close_cover", False)])
async def test_cover_service_posts_then_polls_confirmed_state(hass, loaded, service, open_door):
    entry, client = loaded
    door = entry.runtime_data.data["101:1"]
    await hass.services.async_call(
        "cover",
        service,
        {"entity_id": "cover.main_garage"},
        blocking=True,
    )
    client.async_set_door.assert_awaited_once_with(door, open_door=open_door)
    assert client.async_get_doors.await_count == 2
    assert hass.states.get("cover.main_garage").state == "closed"
    if open_door:
        assert entry.runtime_data.update_interval == timedelta(seconds=5)
        client.async_get_doors.return_value = {
            **client.async_get_doors.return_value,
            "101:1": replace(door, status=DoorStatus.OPEN),
        }
        await entry.runtime_data.async_refresh()
        assert hass.states.get("cover.main_garage").state == "open"
        assert entry.runtime_data.update_interval == timedelta(seconds=15)


async def test_failed_command_surfaces_error_without_fake_state(hass, loaded):
    entry, client = loaded
    client.async_set_door.side_effect = AladdinCommandError("Command delivery is uncertain")
    with pytest.raises(HomeAssistantError, match="uncertain"):
        await hass.services.async_call(
            "cover",
            "open_cover",
            {"entity_id": "cover.main_garage"},
            blocking=True,
        )
    assert hass.states.get("cover.main_garage").state == "closed"
    assert client.async_set_door.await_count == 1
    assert entry.runtime_data.update_interval == timedelta(seconds=15)


async def test_poll_failure_marks_entities_unavailable_and_recovers(hass, loaded):
    entry, client = loaded
    doors = client.async_get_doors.return_value
    client.async_get_doors.side_effect = AladdinConnectionError("Cannot reach cloud")
    await entry.runtime_data.async_refresh()
    assert hass.states.get("cover.main_garage").state == "unavailable"
    assert hass.states.get("sensor.main_garage_battery").state == "unavailable"
    client.async_get_doors.side_effect = None
    client.async_get_doors.return_value = doors
    await entry.runtime_data.async_refresh()
    assert hass.states.get("cover.main_garage").state == "closed"


async def test_removed_and_disabled_doors_become_unavailable(hass, loaded):
    entry, _ = loaded
    data = entry.runtime_data.data
    entry.runtime_data.async_set_updated_data(
        {
            "101:2": replace(data["101:2"], enabled=False),
        }
    )
    assert hass.states.get("cover.main_garage").state == "unavailable"
    assert hass.states.get("cover.side_garage").state == "unavailable"
    with pytest.raises(HomeAssistantError, match="unavailable"):
        await entry.runtime_data.async_command("101:1", open_door=True)


async def test_discovery_adds_doors_and_late_battery_once(hass, loaded):
    entry, client = loaded
    data = client.async_get_doors.return_value
    client.async_get_doors.return_value = {
        **data,
        "101:2": replace(data["101:2"], battery_level=10),
        "101:3": replace(data["101:2"], index=3, door_id="ABCDEF123456_3", name="New garage"),
    }
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("cover.new_garage").state == "open"
    assert hass.states.get("sensor.side_garage_battery").state == "10"
    assert hass.states.get("binary_sensor.side_garage_low_battery").state == "on"
    count = len(hass.states.async_all())
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert len(hass.states.async_all()) == count


async def test_disconnected_battery_is_unknown(hass, loaded):
    entry, _ = loaded
    data = entry.runtime_data.data
    entry.runtime_data.async_set_updated_data(
        {
            **data,
            "101:1": replace(data["101:1"], link_status=2),
        }
    )
    assert hass.states.get("sensor.main_garage_battery").state == "unknown"
    assert hass.states.get("binary_sensor.main_garage_low_battery").state == "unknown"


async def test_shared_and_ignore_options(hass, entry, doors):
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_SHOW_SHARED: True,
            CONF_IGNORED_DOORS: ["ABCDEF123456_1"],
            CONF_SCAN_INTERVAL: 30,
            CONF_BATTERY_LOW_LEVEL: 80,
        },
    )
    client = AsyncMock(spec=AladdinClient)
    client.async_get_doors.return_value = doors
    with patch("custom_components.aladdin_connect_cloud.AladdinClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get("cover.main_garage") is None
        assert hass.states.get("cover.shared_garage").state == "closed"
        assert entry.runtime_data.update_interval == timedelta(seconds=30)
        await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_temporary_failure_retries(hass, entry):
    client = AsyncMock(spec=AladdinClient)
    client.async_get_doors.side_effect = AladdinConnectionError("Network offline")
    with patch("custom_components.aladdin_connect_cloud.AladdinClient", return_value=client):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state == ConfigEntryState.SETUP_RETRY


async def test_setup_auth_failure_starts_reauth(hass, entry):
    client = AsyncMock(spec=AladdinClient)
    client.async_get_doors.side_effect = AladdinAuthError("Invalid password")
    with patch("custom_components.aladdin_connect_cloud.AladdinClient", return_value=client):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_command_auth_failure_starts_reauth(hass, loaded):
    entry, client = loaded
    client.async_set_door.side_effect = AladdinAuthError("Rejected token")
    with pytest.raises(HomeAssistantError, match="Reauthenticate"):
        await entry.runtime_data.async_command("101:1", open_door=True)
    await hass.async_block_till_done()
    assert hass.states.get("cover.main_garage").state == "unavailable"
    assert any(
        flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress()
    )


async def test_options_update_reloads_entry(hass, loaded):
    entry, _ = loaded
    with patch.object(hass.config_entries, "async_reload", return_value=True) as reload_entry:
        hass.config_entries.async_update_entry(entry, options={CONF_SCAN_INTERVAL: 25})
        await hass.async_block_till_done()
    reload_entry.assert_awaited_once_with(entry.entry_id)


async def test_unload_cleans_up_coordinator_listeners(hass, loaded):
    entry, _ = loaded
    coordinator = entry.runtime_data
    assert coordinator._listeners
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not coordinator._listeners
