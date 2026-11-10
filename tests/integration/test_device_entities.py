"""Tests for automation devices in Home Assistant: the device, its declared entities and their commands."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable, Coroutine
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haanim.automation_manager import AutomationManager
from custom_components.haanim.config.config_manager import ConfigManager
from custom_components.haanim.const import DOMAIN

CLIMATE = """
from haanim import action, binary_sensor_entity, haa, sensor_entity

@sensor_entity(unit="°C", device_class="temperature", state_class="measurement", initial=20)
class average_temp:
    pass

@binary_sensor_entity(device_class="door")
class door:
    pass

@action
def warm(event):
    haa.device.entity("average_temp").set_state(event.data["value"])
    haa.device.entity("average_temp").set_attributes(source="test")
"""

def device_of(hass: HomeAssistant, automation_id: str) -> dr.DeviceEntry | None:
    """Return an automation's device, or None."""
    devices = dr.async_get(hass).async_get_devices(identifiers={(DOMAIN, automation_id)})
    return devices[0] if devices else None


Setup = Callable[..., Coroutine[Any, Any, AutomationManager]]


def write(root: Path, name: str, source: str) -> Path:
    """Create an automation folder."""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "main.py").write_text(source, encoding="utf-8")
    return folder


@pytest.fixture
async def setup(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, tmp_path: Path
) -> AsyncGenerator[Setup, None]:
    """Set up the integration on a folder of automations; started=False leaves Home Assistant starting."""
    mock_config_entry.add_to_hass(hass)
    patches = [
        patch.object(ConfigManager, "get_automation_path", return_value=str(tmp_path)),
        patch("custom_components.haanim.async_register_api"),
        patch("custom_components.haanim._async_register_panel", new=AsyncMock()),
        patch("custom_components.haanim._async_unregister_panel", new=AsyncMock()),
        patch("custom_components.haanim.automation_manager.HotReloader.run", new=AsyncMock()),
    ]
    for started in patches:
        started.start()

    async def go(automations: dict[str, str], *, started: bool = True) -> AutomationManager:
        for name, source in automations.items():
            write(tmp_path, name, source)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        if started:
            hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
            await hass.async_block_till_done()
        manager: AutomationManager = hass.data[DOMAIN][mock_config_entry.entry_id]["manager"]
        return manager

    yield go
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    for started in patches:
        started.stop()


async def test_device_and_entities_created(hass: HomeAssistant, setup: Setup) -> None:
    await setup({"climate": CLIMATE})
    state = hass.states.get("sensor.haanim_climate_average_temp")
    assert state is not None
    assert state.state == "20.0"
    assert state.attributes["unit_of_measurement"] == "°C"
    assert state.attributes["device_class"] == "temperature"
    assert state.attributes["state_class"] == "measurement"
    # Home Assistant puts the device's name before the name of an entity on a device
    assert state.attributes["friendly_name"] == "climate average temp"
    door = hass.states.get("binary_sensor.haanim_climate_door")
    assert door is not None and door.attributes["device_class"] == "door"

    device = device_of(hass, "climate")
    assert device is not None
    assert device.manufacturer == "HAAnim"
    assert device.name == "climate"
    registry = er.async_get(hass)
    for entity_id in ("sensor.haanim_climate_average_temp", "binary_sensor.haanim_climate_door", "sensor.haanim_climate"):
        entry = registry.async_get(entity_id)
        assert entry is not None and entry.device_id == device.id, entity_id
    assert registry.async_get("sensor.haanim_climate_average_temp").unique_id == "haanim_climate_average_temp"  # type: ignore[union-attr]


async def test_set_state_writes_ha_state(hass: HomeAssistant, setup: Setup) -> None:
    manager = await setup({"climate": CLIMATE})
    await manager.async_call_action("climate", "warm", {"value": 23})
    await hass.async_block_till_done()
    state = hass.states.get("sensor.haanim_climate_average_temp")
    assert state is not None
    assert state.state == "23.0"
    assert state.attributes["source"] == "test"


async def test_entities_exist_from_storage_before_automations_load(
    hass: HomeAssistant, setup: Setup, hass_storage: dict[str, Any]
) -> None:
    hass_storage["haanim.devices"] = {"version": 1, "minor_version": 1, "key": "haanim.devices", "data": ["climate"]}
    hass_storage["haanim.device.climate"] = {
        "version": 1,
        "minor_version": 1,
        "key": "haanim.device.climate",
        "data": {
            "version": 1,
            "entities": {
                "average_temp": {
                    "object_id": "average_temp",
                    "platform": "sensor",
                    "options": {"name": "average temp", "icon": None, "initial": 20, "initial_attributes": {}, "unit": "°C"},
                    "state": 18.5,
                    "attributes": {},
                    "declared": True,
                    "last_changed": None,
                }
            },
        },
    }
    await setup({"climate": CLIMATE}, started=False)
    state = hass.states.get("sensor.haanim_climate_average_temp")
    assert state is not None and state.state == "18.5"


async def test_leftover_is_unavailable_and_kept(hass: HomeAssistant, setup: Setup, tmp_path: Path) -> None:
    manager = await setup({"climate": CLIMATE})
    write(tmp_path, "climate", CLIMATE.replace("@binary_sensor_entity", "# @binary_sensor_entity"))
    await manager.async_reload("climate")
    await hass.async_block_till_done()
    state = hass.states.get("binary_sensor.haanim_climate_door")
    assert state is not None and state.state == STATE_UNAVAILABLE
    assert er.async_get(hass).async_get("binary_sensor.haanim_climate_door") is not None


async def test_reload_keeps_entities_and_state(hass: HomeAssistant, setup: Setup) -> None:
    manager = await setup({"climate": CLIMATE})
    await manager.async_call_action("climate", "warm", {"value": 25})
    await manager.async_reload("climate")
    await hass.async_block_till_done()
    state = hass.states.get("sensor.haanim_climate_average_temp")
    assert state is not None and state.state == "25.0"
    assert er.async_get(hass).async_get("sensor.haanim_climate_average_temp") is not None


async def test_stopped_automation_keeps_entities_available(hass: HomeAssistant, setup: Setup) -> None:
    manager = await setup({"climate": CLIMATE})
    await manager.async_stop_automation("climate")
    await hass.async_block_till_done()
    state = hass.states.get("sensor.haanim_climate_average_temp")
    assert state is not None and state.state == "20.0"


async def test_folder_removal_removes_device(hass: HomeAssistant, setup: Setup, tmp_path: Path) -> None:
    manager = await setup({"climate": CLIMATE})
    await manager.remove(tmp_path / "climate")
    await hass.async_block_till_done()
    assert device_of(hass, "climate") is None
    assert er.async_get(hass).async_get("sensor.haanim_climate_average_temp") is None
    assert manager.devices.automation_ids() == []


async def test_folder_gone_while_stopped_removes_device(
    hass: HomeAssistant, setup: Setup, hass_storage: dict[str, Any]
) -> None:
    hass_storage["haanim.devices"] = {"version": 1, "minor_version": 1, "key": "haanim.devices", "data": ["gone"]}
    hass_storage["haanim.device.gone"] = {
        "version": 1,
        "minor_version": 1,
        "key": "haanim.device.gone",
        "data": {
            "version": 1,
            "entities": {
                "x": {
                    "object_id": "x",
                    "platform": "sensor",
                    "options": {"name": "x", "icon": None, "initial": None, "initial_attributes": {}},
                    "state": "a",
                    "attributes": {},
                    "declared": True,
                    "last_changed": None,
                }
            },
        },
    }
    manager = await setup({"climate": CLIMATE})
    await hass.async_block_till_done()
    assert manager.devices.automation_ids() == ["climate"]
    assert hass.states.get("sensor.haanim_gone_x") is None or er.async_get(hass).async_get("sensor.haanim_gone_x") is None
