"""Tests for the integration options.

See "Integration Options" in the design.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haanim.automation_manager import AutomationManager
from custom_components.haanim.const import DOMAIN
from custom_components.haanim.options import NUMERIC_OPTIONS, EngineOptions, engine_options, numeric_option
from tests.integration.test_sensor import manager, root, write  # noqa: F401  pylint: disable=unused-import

COMPONENT = Path(__file__).parents[2] / "custom_components" / "haanim"

# The design's table: form field -> default
DESIGN_TABLE: dict[str, Any] = {
    "automation_path": "/config/haanim/automations",
    "automation_refresh_interval": 10,
    "max_concurrent_actions": 20,
    "action_queue_size": 100,
    "default_action_timeout": 0,
    "startup_timeout": 30,
    "shutdown_timeout": 10,
    "stop_grace_period": 0.5,
    "import_allowlist_str": "",
    "allow_all_imports": False,
}

CHANGED: dict[str, Any] = {
    "automation_refresh_interval": 3,
    "max_concurrent_actions": 4,
    "action_queue_size": 7,
    "default_action_timeout": 12.5,
    "startup_timeout": 5,
    "shutdown_timeout": 6,
    "stop_grace_period": 0,
    "import_allowlist_str": "colorsys, fractions",
    "allow_all_imports": True,
}


def current(hass: HomeAssistant, entry: MockConfigEntry) -> AutomationManager:
    """Return the automation manager the integration uses now."""
    return hass.data[DOMAIN][entry.entry_id]["manager"]


async def submit(hass: HomeAssistant, entry: MockConfigEntry, root: Path, **values: Any) -> Any:  # noqa: F811
    """Open the options form and submit it with some values changed."""
    form = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], user_input={"automation_path": str(root), **values}
    )
    await hass.async_block_till_done()
    return result


class TestDefaults:
    """Every option of the design's table, with its default."""

    def test_engine_defaults(self) -> None:
        """Test the limits default to the design's values."""
        assert EngineOptions() == EngineOptions(
            rescan_interval=10,
            concurrency_limit=20,
            action_queue_size=100,
            default_action_timeout=0,
            startup_timeout=30,
            shutdown_timeout=10,
            stop_grace_period=0.5,
        )
        assert engine_options({}) == EngineOptions()

    async def test_form_has_the_ten_options(
        self,
        hass: HomeAssistant,
        manager: AutomationManager,
        mock_config_entry: MockConfigEntry,  # noqa: F811
    ) -> None:
        """Test the options form shows the ten options with the documented defaults."""
        form = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
        assert form["type"] is FlowResultType.FORM
        defaults = {str(key): key.default() for key in form["data_schema"].schema}
        assert list(defaults) == list(DESIGN_TABLE)
        assert defaults == DESIGN_TABLE

    async def test_manager_uses_the_defaults(self, manager: AutomationManager) -> None:  # noqa: F811
        """Test without stored options the engine runs with the defaults."""
        assert manager._options == EngineOptions()  # pylint: disable=protected-access

    @pytest.mark.parametrize("filename", ["strings.json", "translations/en.json"])
    def test_strings(self, filename: str) -> None:
        """Test every option has a label and a description."""
        step = json.loads((COMPONENT / filename).read_text(encoding="utf-8"))["options"]["step"]["init"]
        assert list(step["data"]) == list(DESIGN_TABLE)
        assert list(step["data_description"]) == list(DESIGN_TABLE)
        assert all(step["data"].values()) and all(step["data_description"].values())


class TestEffect:
    """Changing an option reloads the integration, and the new value is used."""

    async def test_change_reloads_with_the_new_values(
        self,
        hass: HomeAssistant,
        manager: AutomationManager,  # noqa: F811
        mock_config_entry: MockConfigEntry,
        root: Path,  # noqa: F811
    ) -> None:
        """Test each option reaches the part of the engine it sets."""
        result = await submit(hass, mock_config_entry, root, **CHANGED)
        assert result["type"] is FlowResultType.CREATE_ENTRY

        new = current(hass, mock_config_entry)
        assert new is not manager
        assert new._options == EngineOptions(  # pylint: disable=protected-access
            rescan_interval=3,
            concurrency_limit=4,
            action_queue_size=7,
            default_action_timeout=12.5,
            startup_timeout=5,
            shutdown_timeout=6,
            stop_grace_period=0,
        )
        # pylint: disable=protected-access
        assert new._action_pool.max_workers == 4
        assert new._dispatcher._queue_size == 7
        assert new._dispatcher._default_timeout == 12.5
        assert new._lifecycle_settings.startup_timeout == 5
        assert new._lifecycle_settings.shutdown_timeout == 6
        assert new._lifecycle_settings.stop_grace_period == 0
        assert new._reloader._interval == 3
        assert new._import_allowlist == ["colorsys", "fractions"]
        assert new._allow_all_imports is True

    async def test_stored_options(
        self,
        hass: HomeAssistant,
        manager: AutomationManager,  # noqa: F811
        mock_config_entry: MockConfigEntry,
        root: Path,  # noqa: F811
    ) -> None:
        """Test the entry stores every option under its key."""
        await submit(hass, mock_config_entry, root, **CHANGED)
        assert mock_config_entry.options == {
            "automation_path": str(root),
            "automation_refresh_interval": 3,
            "max_concurrent_actions": 4,
            "action_queue_size": 7,
            "default_action_timeout": 12.5,
            "startup_timeout": 5.0,
            "shutdown_timeout": 6.0,
            "stop_grace_period": 0.0,
            "import_allowlist": ["colorsys", "fractions"],
            "allow_all_imports": True,
        }

    async def test_automations_run_again_after_the_reload(
        self,
        hass: HomeAssistant,
        manager: AutomationManager,  # noqa: F811
        mock_config_entry: MockConfigEntry,
        root: Path,  # noqa: F811
    ) -> None:
        """Test the old manager is stopped and the automations are loaded and started by the new one."""
        await submit(hass, mock_config_entry, root, max_concurrent_actions=2)

        assert manager.automation_ids() == []
        new = current(hass, mock_config_entry)
        assert new.automation_ids() == ["broken", "lights", "plain"]
        assert hass.states.get("sensor.haanim_lights").state == "on"
        assert await new.async_call_action("lights", "ok") == "done"

    async def test_automations_folder(
        self,
        hass: HomeAssistant,
        manager: AutomationManager,  # noqa: F811
        mock_config_entry: MockConfigEntry,
        tmp_path: Path,
    ) -> None:
        """Test the folder option decides where automations are discovered."""
        elsewhere = tmp_path / "elsewhere"
        write(elsewhere, "moved", "x = 1\n")
        await submit(hass, mock_config_entry, elsewhere)
        assert mock_config_entry.options["automation_path"] == str(elsewhere)

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("automation_refresh_interval", 0),
            ("max_concurrent_actions", 0),
            ("action_queue_size", -1),
            ("default_action_timeout", -1),
            ("startup_timeout", 0),
            ("shutdown_timeout", 0),
            ("stop_grace_period", -0.1),
            ("max_concurrent_actions", "many"),
        ],
    )
    async def test_invalid_value(
        self,
        hass: HomeAssistant,
        manager: AutomationManager,  # noqa: F811
        mock_config_entry: MockConfigEntry,
        root: Path,  # noqa: F811
        key: str,
        value: Any,
    ) -> None:
        """Test a value out of range is refused by the form and nothing is reloaded."""
        with pytest.raises(InvalidData):
            await submit(hass, mock_config_entry, root, **{key: value})
        assert current(hass, mock_config_entry) is manager


class TestStoredValues:
    """Reading the stored options."""

    def test_stored_values_are_used(self) -> None:
        """Test each key sets its limit."""
        assert engine_options(
            {
                "automation_refresh_interval": 15,
                "max_concurrent_actions": 3,
                "action_queue_size": 5,
                "default_action_timeout": 2,
                "startup_timeout": 1,
                "shutdown_timeout": 2.5,
                "stop_grace_period": 0,
            }
        ) == EngineOptions(15, 3, 5, 2.0, 1.0, 2.5, 0.0)

    @pytest.mark.parametrize("key", sorted(NUMERIC_OPTIONS))
    def test_invalid_stored_value_gives_the_default(self, key: str) -> None:
        """Test a stored value that is not valid is replaced by the default."""
        assert numeric_option({key: "nonsense"}, key) == NUMERIC_OPTIONS[key][0]
        assert numeric_option({key: -5}, key) == NUMERIC_OPTIONS[key][0]

    def test_validators(self) -> None:
        """Test the timeouts that must be positive refuse zero, and the others accept it."""
        with pytest.raises(vol.Invalid):
            NUMERIC_OPTIONS["startup_timeout"][1](0)
        assert NUMERIC_OPTIONS["default_action_timeout"][1](0) == 0
        assert NUMERIC_OPTIONS["stop_grace_period"][1](0) == 0
