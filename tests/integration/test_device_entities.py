"""Tests for automation devices in Home Assistant: the device, its declared entities and their commands."""

from __future__ import annotations

import shutil
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
    for entity_id in (
        "sensor.haanim_climate_average_temp",
        "binary_sensor.haanim_climate_door",
        "sensor.haanim_climate",
    ):
        entry = registry.async_get(entity_id)
        assert entry is not None and entry.device_id == device.id, entity_id
    assert registry.async_get("sensor.haanim_climate_average_temp").unique_id == "haanim_climate.average_temp"  # type: ignore[union-attr]


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
    hass_storage["haanim.devices"] = {
        "version": 1,
        "minor_version": 1,
        "key": "haanim.devices",
        "data": ["climate"],
    }
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
                    "options": {
                        "name": "average temp",
                        "icon": None,
                        "initial": 20,
                        "initial_attributes": {},
                        "unit": "°C",
                    },
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
    shutil.rmtree(tmp_path / "climate")
    await manager.remove(tmp_path / "climate")
    await hass.async_block_till_done()
    assert device_of(hass, "climate") is None
    assert er.async_get(hass).async_get("sensor.haanim_climate_average_temp") is None
    assert manager.devices.automation_ids() == []


async def test_folder_gone_while_stopped_removes_device(
    hass: HomeAssistant, setup: Setup, hass_storage: dict[str, Any]
) -> None:
    hass_storage["haanim.devices"] = {
        "version": 1,
        "minor_version": 1,
        "key": "haanim.devices",
        "data": ["gone"],
    }
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
    assert (
        hass.states.get("sensor.haanim_gone_x") is None
        or er.async_get(hass).async_get("sensor.haanim_gone_x") is None
    )


CONTROLS = """
from haanim import button_entity, haa, number_entity, select_entity, switch_entity, text_entity

@switch_entity(initial=False)
class boost:
    def turn_on(self, entity, event):
        entity.set_state(True)

    def turn_off(self, entity, event):
        entity.set_state(False)

@switch_entity(initial=False)
class lazy:
    pass

@number_entity(min=0, max=30, step=0.5, unit="°C", mode="box", initial=20)
class target:
    def set_value(self, entity, event):
        entity.set_state(event.value)

@select_entity(options=["eco", "comfort"], initial="eco")
class mode:
    def select_option(self, entity, event):
        entity.set_state(event.value)

@button_entity
class ring:
    def press(self, entity, event):
        haa.set_variable("rang", True)

@text_entity(max_length=10, pattern="[a-z]*", initial="")
class note:
    def set_value(self, entity, event):
        entity.set_state(event.value)
"""


async def test_switch_runs_hooks(hass: HomeAssistant, setup: Setup) -> None:
    await setup({"heat": CONTROLS})
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.haanim_heat_boost"}, blocking=True
    )
    assert hass.states.get("switch.haanim_heat_boost").state == "on"  # type: ignore[union-attr]
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.haanim_heat_boost"}, blocking=True
    )
    assert hass.states.get("switch.haanim_heat_boost").state == "off"  # type: ignore[union-attr]


async def test_switch_without_hook_stays_off(
    hass: HomeAssistant, setup: Setup, caplog: pytest.LogCaptureFixture
) -> None:
    await setup({"heat": CONTROLS})
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.haanim_heat_lazy"}, blocking=True
    )
    assert hass.states.get("switch.haanim_heat_lazy").state == "off"  # type: ignore[union-attr]
    assert '"lazy" has no turn_on hook; command ignored' in caplog.text


async def test_number_runs_hook(hass: HomeAssistant, setup: Setup) -> None:
    await setup({"heat": CONTROLS})
    state = hass.states.get("number.haanim_heat_target")
    assert state is not None
    assert (state.attributes["min"], state.attributes["max"], state.attributes["step"]) == (0, 30, 0.5)
    assert state.attributes["mode"] == "box"
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.haanim_heat_target", "value": 22.5}, blocking=True
    )
    assert hass.states.get("number.haanim_heat_target").state == "22.5"  # type: ignore[union-attr]


async def test_select_runs_hook(hass: HomeAssistant, setup: Setup) -> None:
    await setup({"heat": CONTROLS})
    assert hass.states.get("select.haanim_heat_mode").attributes["options"] == ["eco", "comfort"]  # type: ignore[union-attr]
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.haanim_heat_mode", "option": "comfort"},
        blocking=True,
    )
    assert hass.states.get("select.haanim_heat_mode").state == "comfort"  # type: ignore[union-attr]


async def test_button_runs_hook(hass: HomeAssistant, setup: Setup) -> None:
    manager = await setup({"heat": CONTROLS})
    await hass.services.async_call("button", "press", {"entity_id": "button.haanim_heat_ring"}, blocking=True)
    context = manager.get_context_by_name("heat")
    assert context is not None and context.variables is not None
    assert context.variables.get("rang") is True


async def test_text_runs_hook(hass: HomeAssistant, setup: Setup) -> None:
    await setup({"heat": CONTROLS})
    state = hass.states.get("text.haanim_heat_note")
    assert state is not None
    assert (state.attributes["max"], state.attributes["pattern"]) == (10, "[a-z]*")
    await hass.services.async_call(
        "text", "set_value", {"entity_id": "text.haanim_heat_note", "value": "hello"}, blocking=True
    )
    assert hass.states.get("text.haanim_heat_note").state == "hello"  # type: ignore[union-attr]


async def test_command_while_stopped_is_noop(
    hass: HomeAssistant, setup: Setup, caplog: pytest.LogCaptureFixture
) -> None:
    manager = await setup({"heat": CONTROLS})
    await manager.async_stop_automation("heat")
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.haanim_heat_boost"}, blocking=True
    )
    assert hass.states.get("switch.haanim_heat_boost").state == "off"  # type: ignore[union-attr]
    assert '"boost" ignored turn_on: automation is not running' in caplog.text


async def test_command_for_an_entity_no_longer_declared_is_ignored(
    hass: HomeAssistant, setup: Setup, caplog: pytest.LogCaptureFixture
) -> None:
    """A command that arrives for an entity a reload just dropped is logged and does nothing."""
    manager = await setup({"heat": CONTROLS})
    await manager.async_entity_command("heat", "gone", "turn_on")
    await manager.async_entity_command("heat", "boost", "press")
    assert '"gone" ignored turn_on: the automation does not declare it' in caplog.text
    assert '"boost" ignored press: the automation does not declare it' in caplog.text


# --- Final review fixes -----------------------------------------------------------

KITCHEN = """
from haanim import sensor_entity

@sensor_entity
class lights:
    pass
"""

KITCHEN_LIGHTS = """
from haanim import sensor_entity

@sensor_entity
class level:
    pass
"""


async def test_removing_an_automation_keeps_another_with_a_longer_id(
    hass: HomeAssistant, setup: Setup, tmp_path: Path
) -> None:
    """Deleting 'kitchen' leaves the entities of 'kitchen_lights' alone."""
    manager = await setup({"kitchen": KITCHEN, "kitchen_lights": KITCHEN_LIGHTS})
    for path in (tmp_path / "kitchen").iterdir():
        path.unlink()
    (tmp_path / "kitchen").rmdir()
    await manager.remove(tmp_path / "kitchen")
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    assert registry.async_get("sensor.haanim_kitchen_lights_level") is not None
    assert registry.async_get_entity_id("sensor", DOMAIN, "haanim_kitchen_lights") is not None
    assert device_of(hass, "kitchen") is None


async def test_entity_and_status_sensor_with_the_same_name(hass: HomeAssistant, setup: Setup) -> None:
    """'kitchen' declaring 'lights' and an automation 'kitchen_lights' both get their sensor."""
    await setup({"kitchen": KITCHEN, "kitchen_lights": KITCHEN_LIGHTS})
    registry = er.async_get(hass)
    declared = registry.async_get_entity_id("sensor", DOMAIN, "haanim_kitchen.lights")
    status = registry.async_get_entity_id("sensor", DOMAIN, "haanim_kitchen_lights")
    assert declared is not None and status is not None and declared != status
    assert hass.states.get(declared) is not None


async def test_missing_main_py_keeps_the_device(hass: HomeAssistant, setup: Setup, tmp_path: Path) -> None:
    """A folder whose main.py is gone for a moment (an editor saving) keeps its device and entities."""
    manager = await setup({"climate": CLIMATE})
    (tmp_path / "climate" / "main.py").unlink()
    await manager.remove(tmp_path / "climate")
    await hass.async_block_till_done()
    assert device_of(hass, "climate") is not None
    assert manager.devices.automation_ids() == ["climate"]


async def test_no_automations_found_at_start_keeps_stored_devices(
    hass: HomeAssistant, setup: Setup, hass_storage: dict[str, Any]
) -> None:
    """An empty automations folder (a share not mounted yet) does not wipe the stored devices."""
    hass_storage["haanim.devices"] = {
        "version": 1,
        "minor_version": 1,
        "key": "haanim.devices",
        "data": ["climate"],
    }
    hass_storage["haanim.device.climate"] = {
        "version": 1,
        "minor_version": 1,
        "key": "haanim.device.climate",
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
    manager = await setup({})
    await hass.async_block_till_done()
    assert manager.devices.automation_ids() == ["climate"]


async def test_without_recorder_no_statistics_provider(hass: HomeAssistant) -> None:
    """A Home Assistant without the recorder gives HAAnim no statistics provider."""
    from custom_components.haanim.ha.host import build_host  # pylint: disable=import-outside-toplevel

    assert build_host(hass, None, None).statistics is None  # type: ignore[arg-type]
