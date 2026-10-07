"""Tests for the automation entity: one enum sensor per automation.

See "Automation Entity" in the design.
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haanim.automation_manager import AutomationManager
from custom_components.haanim.config.config_manager import ConfigManager
from custom_components.haanim.const import DOMAIN
from custom_components.haanim.sensor import AutomationSensor

LIGHTS = """
from haanim import haa, action, on_event

@action
def ok(event):
    return "done"

@action
def say(event):
    haa.set_message("working")

@on_event("haanim_test_boom")
def boom(event):
    raise ValueError("bad value")
"""


def write(root: Path, name: str, source: str, metadata: str | None = None) -> Path:
    """Create an automation folder."""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "main.py").write_text(source, encoding="utf-8")
    if metadata is not None:
        (folder / "metadata.json").write_text(metadata, encoding="utf-8")
    return folder


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """The automations folder with three automations: one good, one plain, one broken."""
    write(tmp_path, "lights", LIGHTS, '{"name": "Hall Lights"}')
    write(tmp_path, "plain", "x = 1\n")
    write(tmp_path, "broken", "def broken(:\n")
    return tmp_path


@pytest.fixture
async def manager(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, root: Path
) -> AsyncGenerator[AutomationManager, None]:
    """The integration set up on the automations folder, with Home Assistant started."""
    mock_config_entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, "haanim_gone", suggested_object_id="haanim_gone", config_entry=mock_config_entry
    )
    with (
        patch.object(ConfigManager, "get_automation_path", return_value=str(root)),
        patch("custom_components.haanim.async_register_api"),
        patch("custom_components.haanim._async_register_panel", new=AsyncMock()),
        patch("custom_components.haanim._async_unregister_panel", new=AsyncMock()),
        patch("custom_components.haanim.automation_manager.HotReloader.run", new=AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()
        yield hass.data[DOMAIN][mock_config_entry.entry_id]["manager"]


def attributes(hass: HomeAssistant, automation_id: str = "lights") -> dict[str, Any]:
    """Return the attributes of an automation's entity."""
    state = hass.states.get(f"sensor.haanim_{automation_id}")
    assert state is not None
    return dict(state.attributes)


class TestEntity:
    """One sensor per automation, with the documented IDs, class and name."""

    async def test_entity_per_automation(self, hass: HomeAssistant, manager: AutomationManager) -> None:
        """Test every automation folder has an entity sensor.haanim_<automation_id>."""
        assert sorted(hass.states.async_entity_ids("sensor")) == [
            "sensor.haanim_broken",
            "sensor.haanim_lights",
            "sensor.haanim_plain",
        ]

    async def test_unique_id(self, hass: HomeAssistant, manager: AutomationManager) -> None:
        """Test the unique ID is haanim_<automation_id>."""
        registered = er.async_get(hass).async_get("sensor.haanim_lights")
        assert registered is not None
        assert registered.unique_id == "haanim_lights"
        assert registered.platform == DOMAIN

    async def test_enum_device_class(self, hass: HomeAssistant, manager: AutomationManager) -> None:
        """Test the sensor is an enum with the options on, off and error."""
        attrs = attributes(hass)
        assert attrs["device_class"] == "enum"
        assert attrs["options"] == ["on", "off", "error"]

    async def test_friendly_name(self, hass: HomeAssistant, manager: AutomationManager) -> None:
        """Test the friendly name is the metadata's name, or the folder's without one."""
        assert attributes(hass, "lights")["friendly_name"] == "Hall Lights"
        assert attributes(hass, "plain")["friendly_name"] == manager.automation_name("plain")

    async def test_read_only(self, hass: HomeAssistant, manager: AutomationManager) -> None:
        """Test the integration registers no service that sets the entity."""
        assert not hass.services.has_service("sensor", "set_value")
        assert not hasattr(AutomationSensor, "async_set_native_value")


class TestState:
    """The state follows the lifecycle state; unavailable when not loaded."""

    async def test_on(self, hass: HomeAssistant, manager: AutomationManager) -> None:
        """Test a started automation is on."""
        assert hass.states.get("sensor.haanim_lights").state == "on"
        assert hass.states.get("sensor.haanim_plain").state == "on"

    async def test_error(self, hass: HomeAssistant, manager: AutomationManager) -> None:
        """Test an automation that cannot be loaded is in error, with the reason as message."""
        assert hass.states.get("sensor.haanim_broken").state == "error"
        assert "main.py:1" in attributes(hass, "broken")["message"]

    async def test_off(self, hass: HomeAssistant, manager: AutomationManager) -> None:
        """Test a stopped automation is off, and on again when started."""
        await manager.async_stop_automation("lights")
        await hass.async_block_till_done()
        assert hass.states.get("sensor.haanim_lights").state == "off"
        assert attributes(hass)["enabled"] is True

        await manager.async_start_automation("lights")
        await hass.async_block_till_done()
        assert hass.states.get("sensor.haanim_lights").state == "on"

    async def test_unavailable_when_not_loaded(
        self, hass: HomeAssistant, manager: AutomationManager, root: Path
    ) -> None:
        """Test an unloaded automation's entity stays and is unavailable; loading brings it back."""
        await manager.async_unload_automation(str(root / "lights"))
        await hass.async_block_till_done()
        assert hass.states.get("sensor.haanim_lights").state == "unavailable"

        await manager.async_load_automation(str(root / "lights"))
        await hass.async_block_till_done()
        assert hass.states.get("sensor.haanim_lights").state == "on"

    async def test_fixed_automation_leaves_error(
        self, hass: HomeAssistant, manager: AutomationManager, root: Path
    ) -> None:
        """Test a reloaded automation that now loads goes from error to on."""
        folder = write(root, "broken", "x = 1\n")
        await manager.async_load_automation(str(folder))
        await hass.async_block_till_done()
        assert hass.states.get("sensor.haanim_broken").state == "on"
        assert attributes(hass, "broken")["message"] is None


class TestAttributes:
    """Every row of the attribute table."""

    async def test_idle_attributes(self, hass: HomeAssistant, manager: AutomationManager) -> None:
        """Test the attributes of an automation that has started and done nothing."""
        attrs = attributes(hass)
        assert attrs["enabled"] is True
        assert attrs["message"] is None
        assert attrs["last_run"] == manager.automation_times("lights").run_time.isoformat()
        assert attrs["running_actions"] == []
        assert attrs["last_action"] is None
        assert attrs["last_action_time"] is None
        assert attrs["last_error"] is None

    async def test_enabled(self, hass: HomeAssistant, manager: AutomationManager) -> None:
        """Test a disabled automation is off and not enabled; enabling starts it."""
        await manager.async_disable_automation("lights")
        await hass.async_block_till_done()
        assert hass.states.get("sensor.haanim_lights").state == "off"
        assert attributes(hass)["enabled"] is False

        await manager.async_enable_automation("lights")
        await hass.async_block_till_done()
        assert hass.states.get("sensor.haanim_lights").state == "on"
        assert attributes(hass)["enabled"] is True

    async def test_message(self, hass: HomeAssistant, manager: AutomationManager) -> None:
        """Test the message set with haa.set_message() is shown."""
        await manager.async_call_action("lights", "say")
        await hass.async_block_till_done()
        assert attributes(hass)["message"] == "working"

    async def test_last_run_changes_on_restart(self, hass: HomeAssistant, manager: AutomationManager) -> None:
        """Test last_run is when the automation was last started."""
        await manager.async_restart_automation("lights")
        await hass.async_block_till_done()
        assert attributes(hass)["last_run"] == manager.automation_times("lights").run_time.isoformat()

    async def test_actions(self, hass: HomeAssistant, manager: AutomationManager) -> None:
        """Test running_actions, last_action and last_action_time follow an action."""
        seen: list[list[str]] = []

        def record(event: Event) -> None:
            new_state = event.data["new_state"]
            if event.data["entity_id"] == "sensor.haanim_lights" and new_state is not None:
                seen.append(new_state.attributes.get("running_actions"))

        hass.bus.async_listen("state_changed", record)
        assert await manager.async_call_action("lights", "ok") == "done"
        await hass.async_block_till_done()

        assert ["ok"] in seen
        attrs = attributes(hass)
        assert attrs["running_actions"] == []
        assert attrs["last_action"] == "ok"
        assert attrs["last_action_time"] == manager.automation_times("lights").last_action_time.isoformat()

    async def test_last_error(self, hass: HomeAssistant, manager: AutomationManager) -> None:
        """Test a failing trigger-fired action is in last_error and the automation stays on."""
        hass.bus.async_fire("haanim_test_boom")
        # The engine's own tasks deliver the event and run the action
        for _ in range(100):
            await hass.async_block_till_done()
            if manager.automation_last_error("lights") is not None:
                break

        failure = manager.automation_last_error("lights")
        assert failure is not None
        assert attributes(hass)["last_error"] == {
            "time": failure.time.isoformat(),
            "action": "boom",
            "error_type": "ValueError",
            "message": "bad value",
        }
        assert hass.states.get("sensor.haanim_lights").state == "on"

    def test_unrecorded_attributes(self) -> None:
        """Test the fast-changing attributes are excluded from the recorder, the others are not."""
        assert AutomationSensor._unrecorded_attributes == frozenset(
            {"running_actions", "last_action", "last_action_time", "message"}
        )
        combined = getattr(AutomationSensor, "_Entity__combined_unrecorded_attributes")
        assert {"running_actions", "last_action", "last_action_time", "message"} <= combined
        assert not {"enabled", "last_run", "last_error"} & combined


class TestRemoval:
    """Rule: the entity is removed when the folder is removed."""

    async def test_removed_with_the_folder(
        self, hass: HomeAssistant, manager: AutomationManager, root: Path
    ) -> None:
        """Test removing the folder removes the entity and its registry entry."""
        shutil.rmtree(root / "lights")
        await manager.remove(root / "lights")
        await hass.async_block_till_done()

        assert hass.states.get("sensor.haanim_lights") is None
        assert er.async_get(hass).async_get("sensor.haanim_lights") is None
        assert hass.states.get("sensor.haanim_plain") is not None

    async def test_folder_removed_while_not_running(
        self, hass: HomeAssistant, manager: AutomationManager
    ) -> None:
        """Test an entity left from a folder that went away earlier is removed after loading."""
        assert er.async_get(hass).async_get("sensor.haanim_gone") is None

    async def test_new_folder_gets_an_entity(
        self, hass: HomeAssistant, manager: AutomationManager, root: Path
    ) -> None:
        """Test an automation that appears later gets its entity."""
        folder = write(root, "later", "x = 1\n", '{"name": "Later"}')
        await manager.async_load_automation(str(folder))
        await hass.async_block_till_done()
        assert hass.states.get("sensor.haanim_later").state == "on"
        assert attributes(hass, "later")["friendly_name"] == "Later"

    async def test_unload_entry_removes_the_entities(
        self, hass: HomeAssistant, manager: AutomationManager, mock_config_entry: MockConfigEntry
    ) -> None:
        """Test unloading the integration makes the entities unavailable and stops updates."""
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get("sensor.haanim_lights").state == "unavailable"
        manager._status_manager.notify("lights")
