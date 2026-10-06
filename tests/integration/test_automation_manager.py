"""Tests for the automation_manager.py module."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from pathlib import Path

import pytest

from haanim.engine.automation_context import AutomationContext
from haanim.engine.lifecycle import AutomationState
from haanim.testing import FakeClock, FakeFileSystem, LocalFileSystem, make_host

from custom_components.haanim.const import DOMAIN
from haanim.engine import HAAnimError
from haanim.engine.errors import (
    ActionNotFoundError,
    AutomationAlreadyRunningError,
    AutomationDisabledError,
    AutomationNotRunningError,
    NonExistingAutomationError,
)
from custom_components.haanim.automation_manager import AutomationManager, async_get_manager


class TestAutomationManager:
    """Tests for AutomationManager class."""

    @pytest.fixture
    def mock_hass(self, tmp_path: Path) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.config.path = MagicMock(side_effect=lambda *parts: str(tmp_path.joinpath(*parts)))
        hass.bus.async_listen_once = MagicMock()
        hass.bus.async_fire = MagicMock()
        hass.async_create_task = MagicMock(return_value=MagicMock())
        hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
        hass.data = {}
        return hass

    @pytest.fixture
    def mock_entry(self) -> MagicMock:
        """Create a mock config entry."""
        entry = MagicMock()
        entry.data = {}
        entry.options = {}
        return entry

    @pytest.fixture
    def mock_config_manager(self) -> MagicMock:
        """Create a mock config manager."""
        config = MagicMock()
        config.get_automation_path.return_value = "/tmp/haanim_test"
        config.get_import_allowlist.return_value = []
        config.get_allow_all_imports.return_value = False
        return config

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    def test_init(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        mock_config_manager: MagicMock,
    ) -> None:
        """Test AutomationManager initialization."""
        mock_get_config.return_value = mock_config_manager

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))

        assert manager.hass is mock_hass
        assert manager.entry is mock_entry
        assert not manager._contexts
        assert manager._started is False

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_async_setup_creates_folder(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        mock_config_manager: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test async_setup creates automation folder."""
        automation_path = tmp_path / "automations"
        mock_config_manager.get_automation_path.return_value = str(automation_path)
        mock_get_config.return_value = mock_config_manager

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        await manager.async_setup()

        assert automation_path.exists()

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_async_setup_registers_events(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        mock_config_manager: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test async_setup registers lifecycle events."""
        mock_config_manager.get_automation_path.return_value = str(tmp_path)
        mock_get_config.return_value = mock_config_manager

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        await manager.async_setup()

        # Should register for started and stop events
        assert mock_hass.bus.async_listen_once.call_count == 2

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_get_all_metadata_empty(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        mock_config_manager: MagicMock,
    ) -> None:
        """Test get_all_metadata returns empty list when no automations."""
        mock_config_manager.get_automation_path.return_value = "/nonexistent"
        mock_get_config.return_value = mock_config_manager

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        result = manager.get_all_metadata()

        assert result == []

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_get_all_actions_empty(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        mock_config_manager: MagicMock,
    ) -> None:
        """Test get_all_actions returns empty list when no automations."""
        mock_config_manager.get_automation_path.return_value = "/nonexistent"
        mock_get_config.return_value = mock_config_manager

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        result = manager.get_all_actions()

        assert not result

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_get_automation_status(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        mock_config_manager: MagicMock,
    ) -> None:
        """Test get_automation_status returns status."""
        mock_config_manager.get_automation_path.return_value = "/nonexistent"
        mock_get_config.return_value = mock_config_manager

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        result = manager.get_automation_status("test_automation")

        # Should return an AutomationStatus object
        assert result is not None


class TestAutomationManagerLoading:
    """Tests for automation loading functionality."""

    @pytest.fixture
    def mock_hass(self, tmp_path: Path) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.config.path = MagicMock(side_effect=lambda *parts: str(tmp_path.joinpath(*parts)))
        hass.bus.async_listen_once = MagicMock()
        hass.bus.async_fire = MagicMock()
        hass.async_create_task = MagicMock(return_value=MagicMock())
        hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
        hass.data = {}
        return hass

    @pytest.fixture
    def mock_entry(self) -> MagicMock:
        """Create a mock config entry."""
        entry = MagicMock()
        entry.data = {}
        entry.options = {}
        return entry

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_async_load_all_automations_empty_folder(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test loading from empty folder returns empty dict."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = str(tmp_path)
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        result = await manager.async_load_all_automations()

        assert result == {}

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_async_load_all_automations_ignores_flat_files(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test a Python file directly in the automations folder is not an automation."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = str(tmp_path)
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        (tmp_path / "flat.py").write_text("x = 1")
        (tmp_path / "no_main").mkdir()
        (tmp_path / "no_main" / "helper.py").write_text("x = 1")

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        result = await manager.async_load_all_automations()

        assert result == {}

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_async_load_all_automations_in_id_order_with_rejected_folders(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test folders are loaded in ascending ID order and unusable folder names are reported."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = str(tmp_path)
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        for name in ("Zeta", "My Automation", "my-automation", "---", "alpha"):
            (tmp_path / name).mkdir()
            (tmp_path / name / "main.py").write_text("x = 1\n")
        (tmp_path / "alpha" / "metadata.json").write_text('{"name": "Alpha", "version": "2.0"}')

        host = make_host(files=LocalFileSystem())
        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=host)
        result = await manager.async_load_all_automations()

        assert [metadata.id for metadata in result.values()] == ["alpha", "my_automation", "zeta"]
        assert list(result) == [str(tmp_path / name) for name in ("alpha", "My Automation", "Zeta")]
        alpha = result[str(tmp_path / "alpha")]
        assert (alpha.name, alpha.version) == ("Alpha", "2.0")
        assert manager.get_context_by_name("my_automation") is not None
        assert host.issues.issues == {
            "rejected_folder_---": ("folder_without_id", {"folder": "---"}),
            "rejected_folder_my-automation": (
                "folder_id_collision",
                {"folder": "my-automation", "automation_id": "my_automation", "winner": "My Automation"},
            ),
        }

        # Renaming the losing folder clears its issue on the next scan.
        (tmp_path / "my-automation").rename(tmp_path / "other")
        await manager.async_reload_all_automations()

        assert sorted(host.issues.issues) == ["rejected_folder_---"]
        assert manager.get_context_by_name("other") is not None

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_failed_automation_is_recorded(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test an automation with invalid metadata fails to load without stopping the others."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = str(tmp_path)
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        for name in ("bad", "good"):
            (tmp_path / name).mkdir()
            (tmp_path / name / "main.py").write_text("x = 1\n")
        (tmp_path / "bad" / "metadata.json").write_text('{"name": 5}')

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        result = await manager.async_load_all_automations()

        assert result[str(tmp_path / "bad")] == "metadata.json: field 'name' must be a string, not a number"
        assert not isinstance(result[str(tmp_path / "good")], str)
        assert manager.get_failed_automations() == {str(tmp_path / "bad"): result[str(tmp_path / "bad")]}

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_async_load_all_automations_loads_valid(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test loading valid automations."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = str(tmp_path)
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        # Create a valid automation
        automation = tmp_path / "test_automation"
        automation.mkdir()
        (automation / "main.py").write_text(
            """
from haanim import action
@action
def my_action():
    pass
"""
        )

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        result = await manager.async_load_all_automations()

        assert len(result) == 1
        assert str(automation) in result

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_async_load_all_automations_nonexistent_folder(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test loading from non-existent folder returns empty dict."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/nonexistent/path"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        result = await manager.async_load_all_automations()

        assert result == {}


class TestAsyncGetManager:
    """Tests for async_get_manager function."""

    async def test_get_manager_not_setup(self) -> None:
        """Test async_get_manager returns None when not set up."""
        hass = MagicMock()
        hass.data = {}

        result = await async_get_manager(hass)

        assert result is None

    async def test_get_manager_domain_not_in_data(self) -> None:
        """Test async_get_manager returns None when domain not in data."""
        hass = MagicMock()
        hass.data = {"other_domain": {}}

        result = await async_get_manager(hass)

        assert result is None

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_get_manager_returns_manager(
        self,
        mock_get_config: MagicMock,
    ) -> None:
        """Test async_get_manager returns the manager."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        hass = MagicMock()
        hass.bus.async_listen_once = MagicMock()
        hass.async_add_executor_job = AsyncMock()
        entry = MagicMock()
        entry.data = {}
        entry.options = {}

        manager = AutomationManager(hass=hass, entry=entry, host=make_host(files=LocalFileSystem()))
        hass.data = {"haanim": {"entry_id": {"manager": manager}}}

        result = await async_get_manager(hass)

        assert result is manager


class TestAutomationManagerActions:
    """Tests for action execution functionality."""

    @pytest.fixture
    def mock_hass(self, tmp_path: Path) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.config.path = MagicMock(side_effect=lambda *parts: str(tmp_path.joinpath(*parts)))
        hass.bus.async_listen_once = MagicMock()
        hass.bus.async_fire = MagicMock()
        hass.async_create_task = MagicMock(return_value=MagicMock())
        hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
        hass.data = {}
        return hass

    @pytest.fixture
    def mock_entry(self) -> MagicMock:
        """Create a mock config entry."""
        entry = MagicMock()
        entry.data = {}
        entry.options = {}
        return entry

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    def test_get_context_not_found(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test get_context returns None for non-existent automation."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        result = manager.get_context("nonexistent")

        assert result is None

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    def test_get_context_by_name_not_found(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test get_context_by_name returns None for non-existent automation."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        result = manager.get_context_by_name("nonexistent")

        assert result is None

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    def test_get_all_contexts_empty(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test get_all_contexts returns empty list when no automations."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        result = manager.get_all_contexts()

        assert result == []

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_async_unload_automation_not_loaded(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test unloading an automation that isn't loaded."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        result = await manager.async_unload_automation("nonexistent")
        # Returns False when automation not loaded
        assert result is False

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_async_unload_all_automations_empty(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test unloading all automations when none loaded."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        # Should not raise an error
        await manager.async_unload_all_automations()

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    def test_get_failed_automations(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test get_failed_automations returns failures."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._failed_automations["/tmp/bad.py"] = "Syntax error"

        result = manager.get_failed_automations()
        assert "/tmp/bad.py" in result
        assert result["/tmp/bad.py"] == "Syntax error"


class TestAutomationManagerProperties:
    """Tests for the manager's Home Assistant event handlers and its properties."""

    @pytest.fixture
    def mock_hass(self, tmp_path: Path) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.config.path = MagicMock(side_effect=lambda *parts: str(tmp_path.joinpath(*parts)))
        hass.bus.async_listen_once = MagicMock()
        hass.bus.async_fire = MagicMock()
        hass.async_create_task = MagicMock(return_value=MagicMock())
        hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
        hass.data = {}
        return hass

    @pytest.fixture
    def mock_entry(self) -> MagicMock:
        """Create a mock config entry."""
        entry = MagicMock()
        entry.data = {}
        entry.options = {}
        return entry

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_on_ha_started(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test _on_ha_started sets started flag and loads automations."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = str(tmp_path)
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        assert manager._started is False

        # Call _on_ha_started
        await manager._on_ha_started(MagicMock())

        assert manager._started is True
        assert mock_hass.async_create_task.called
        # The mock never runs the watcher it was handed
        mock_hass.async_create_task.call_args[0][0].close()

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_on_ha_stop(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test _on_ha_stop shuts the dispatcher down and unloads the automations."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = str(tmp_path)
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        assert not manager.dispatcher.is_shutting_down

        # Call _on_ha_stop
        await manager._on_ha_stop(MagicMock())

        assert manager.dispatcher.is_shutting_down
        assert manager.get_all_contexts() == []

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_dispatcher_property(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test the dispatcher property returns the dispatcher every action request goes through."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        assert manager.dispatcher is manager._dispatcher
        assert manager.dispatcher.pool is manager._action_pool

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    def test_get_all_automation_statuses(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test get_all_automation_statuses returns all statuses."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        result = manager.get_all_automation_statuses()

        assert isinstance(result, dict)


class TestAutomationManagerRunAction:
    """Tests for async_run_action method."""

    @pytest.fixture
    def mock_hass(self, tmp_path: Path) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.config.path = MagicMock(side_effect=lambda *parts: str(tmp_path.joinpath(*parts)))
        hass.bus.async_listen_once = MagicMock()
        hass.bus.async_fire = MagicMock()
        hass.async_create_task = MagicMock(return_value=MagicMock())
        hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
        hass.data = {}
        return hass

    @pytest.fixture
    def mock_entry(self) -> MagicMock:
        """Create a mock config entry."""
        entry = MagicMock()
        entry.data = {}
        entry.options = {}
        return entry

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_async_run_action_automation_not_found(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test async_run_action raises error for non-existent automation."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))

        with pytest.raises(NonExistingAutomationError):
            await manager.async_run_action("nonexistent", "some_action")

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_async_run_action_action_not_found(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test async_run_action raises error for non-existent action."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        # Create mock context
        mock_context = MagicMock()
        mock_context.automation_id = "test_automation"
        mock_context.get_actions.return_value = []

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._contexts["/tmp/test.py"] = mock_context
        running = MagicMock()
        running.automation_id = "test_automation"
        running.call_action = AsyncMock(side_effect=ActionNotFoundError("test_automation", "missing_action"))
        manager._automations["/tmp/test.py"] = running

        with pytest.raises(HAAnimError, match="not found"):
            await manager.async_run_action("test_automation", "missing_action")


class TestAutomationManagerReload:
    """Tests for automation reload functionality."""

    @pytest.fixture
    def mock_hass(self, tmp_path: Path) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.config.path = MagicMock(side_effect=lambda *parts: str(tmp_path.joinpath(*parts)))
        hass.bus.async_listen_once = MagicMock()
        hass.bus.async_fire = MagicMock()
        hass.async_create_task = MagicMock(return_value=MagicMock())
        hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
        hass.data = {}
        return hass

    @pytest.fixture
    def mock_entry(self) -> MagicMock:
        """Create a mock config entry."""
        entry = MagicMock()
        entry.data = {}
        entry.options = {}
        return entry

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_async_reload_all_automations(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test async_reload_all_automations reloads automations."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = str(tmp_path)
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        result = await manager.async_reload_all_automations()

        assert isinstance(result, dict)

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_async_reload_automation(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test async_reload_automation reloads a specific automation."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = str(tmp_path)
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        # Create automation file
        automation = tmp_path / "test"
        automation.mkdir()
        (automation / "main.py").write_text(
            """
from haanim import action
@action
def test_action():
    pass
"""
        )

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        result = await manager.async_reload_automation(str(automation))

        assert result is not None

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_async_call_action(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test async_call_action runs an action of a loaded automation and returns its result."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = str(tmp_path)
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        automation = tmp_path / "maths"
        automation.mkdir()
        (automation / "main.py").write_text(
            """
from haanim import action
@action(name="Add numbers", aliases=["add"])
async def add(event):
    return (event.data["a"] + event.data["b"], event.source, event.caller)
"""
        )

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        await manager.async_load_automation(str(automation))

        await manager.async_start_automation("maths")
        assert manager.get_automation_state("maths") is AutomationState.ON

        assert await manager.async_call_action("maths", "add", {"a": 2, "b": 3}) == (5, "manual", None)
        called = await manager.async_call_action("maths", "Add numbers", {"a": 4, "b": 5}, caller="lights")
        assert called == (9, "automation", "lights")
        assert await manager.async_run_action("maths", "add", {"a": 1, "b": 1}) == (2, "manual", None)

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_async_call_action_errors(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test async_call_action raises for an unknown automation and for an unknown action."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = str(tmp_path)
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        automation = tmp_path / "maths"
        automation.mkdir()
        (automation / "main.py").write_text("from haanim import action\n@action\ndef add():\n    return 1\n")

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        await manager.async_load_automation(str(automation))

        with pytest.raises(NonExistingAutomationError) as automation_error:
            await manager.async_call_action("nope", "add")
        assert automation_error.value.automation_id == "nope"

        with pytest.raises(AutomationNotRunningError):
            await manager.async_call_action("maths", "add")

        await manager.async_start_automation("maths")
        with pytest.raises(ActionNotFoundError) as action_error:
            await manager.async_call_action("maths", "missing")
        assert (action_error.value.automation_id, action_error.value.action_name) == ("maths", "missing")

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_get_context_by_name_found(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test get_context_by_name returns context when found."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        # Create mock context
        mock_context = MagicMock()
        mock_context.automation_id = "my_automation"

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._contexts["/tmp/my_automation.py"] = mock_context

        # Should find by automation ID
        result = manager.get_context_by_name("my_automation")
        assert result is mock_context

        # Unknown IDs are not found
        assert manager.get_context_by_name("My Automation") is None


class TestAutomationManagerStartupShutdown:
    """Tests for startup and shutdown action handling."""

    @pytest.fixture
    def mock_hass(self, tmp_path: Path) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.config.path = MagicMock(side_effect=lambda *parts: str(tmp_path.joinpath(*parts)))
        hass.bus.async_listen_once = MagicMock()
        hass.bus.async_fire = MagicMock()
        hass.async_create_task = MagicMock(return_value=MagicMock())
        hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
        hass.data = {}
        return hass

    @pytest.fixture
    def mock_entry(self) -> MagicMock:
        """Create a mock config entry."""
        entry = MagicMock()
        entry.data = {}
        entry.options = {}
        return entry

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_async_load_automation_exception(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test async_load_automation with invalid automation raises error."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = str(tmp_path)
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        # Create invalid automation file
        automation = tmp_path / "bad_automation"
        automation.mkdir()
        (automation / "main.py").write_text("def broken(")

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))

        with pytest.raises(HAAnimError):
            await manager.async_load_automation(str(automation))

        # Should be in failed automations
        assert str(automation) in manager.get_failed_automations()

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    def test_get_context_returns_context(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test get_context returns the correct context."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        mock_context = MagicMock()
        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._contexts["/tmp/test.py"] = mock_context

        result = manager.get_context("/tmp/test.py")
        assert result is mock_context

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    def test_get_all_contexts_with_automations(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test get_all_contexts returns all contexts."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        mock_context1 = MagicMock()
        mock_context2 = MagicMock()
        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._contexts["/tmp/test1.py"] = mock_context1
        manager._contexts["/tmp/test2.py"] = mock_context2

        result = manager.get_all_contexts()
        assert len(result) == 2

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    def test_get_all_actions_with_automations(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test get_all_actions returns actions from all automations."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        mock_action = MagicMock()
        mock_context = MagicMock()
        mock_context.get_actions.return_value = [mock_action]

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._contexts["/tmp/test.py"] = mock_context

        result = manager.get_all_actions()
        assert len(result) == 1
        assert result[0] is mock_action

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    def test_get_all_metadata_with_automations(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test get_all_metadata returns metadata from all automations."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        mock_metadata = MagicMock()
        mock_context = MagicMock()
        mock_context.get_metadata.return_value = mock_metadata

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._contexts["/tmp/test.py"] = mock_context

        result = manager.get_all_metadata()
        assert len(result) == 1
        assert result[0] is mock_metadata


class TestAutomationManagerActionsAdvanced:
    """Tests for action-related functionality (advanced)."""

    @pytest.fixture
    def mock_hass(self, tmp_path: Path) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.config.path = MagicMock(side_effect=lambda *parts: str(tmp_path.joinpath(*parts)))
        hass.bus.async_listen_once = MagicMock()
        hass.bus.async_fire = MagicMock()
        hass.async_create_task = MagicMock(return_value=MagicMock())
        hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
        hass.data = {}
        return hass

    @pytest.fixture
    def mock_entry(self) -> MagicMock:
        """Create a mock config entry."""
        entry = MagicMock()
        entry.data = {}
        entry.options = {}
        return entry

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    def test_get_all_automation_statuses(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test get_all_automation_statuses returns status dict."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        result = manager.get_all_automation_statuses()

        assert isinstance(result, dict)

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    def test_get_failed_automations(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test get_failed_automations returns copy of failed automations dict."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._failed_automations = {"/tmp/bad.py": "Syntax error"}

        result = manager.get_failed_automations()
        assert result == {"/tmp/bad.py": "Syntax error"}
        # Should be a copy
        assert result is not manager._failed_automations


class TestAsyncGetManagerEdgeCases:
    """Tests for async_get_manager helper function."""

    async def test_async_get_manager_no_domain(self) -> None:
        """Test async_get_manager returns None when domain not in data."""
        mock_hass = MagicMock()
        mock_hass.data = {}

        result = await async_get_manager(mock_hass)
        assert result is None

    async def test_async_get_manager_with_manager(self) -> None:
        """Test async_get_manager returns manager when present."""
        mock_hass = MagicMock()
        mock_manager = MagicMock(spec=AutomationManager)

        mock_hass.data = {DOMAIN: {"entry_id": {"manager": mock_manager}}}

        result = await async_get_manager(mock_hass)
        assert result is mock_manager

    async def test_async_get_manager_no_manager_key(self) -> None:
        """Test async_get_manager returns None when no manager key."""
        mock_hass = MagicMock()

        mock_hass.data = {DOMAIN: {"entry_id": {"other_key": "value"}}}

        result = await async_get_manager(mock_hass)
        assert result is None

    async def test_async_get_manager_manager_not_automation_manager(self) -> None:
        """Test async_get_manager returns None when manager is wrong type."""
        mock_hass = MagicMock()

        mock_hass.data = {DOMAIN: {"entry_id": {"manager": "not_a_manager"}}}

        result = await async_get_manager(mock_hass)
        assert result is None


class TestAutomationManagerStartupShutdownActions:
    """Tests for startup and shutdown action methods."""

    @pytest.fixture
    def mock_hass(self, tmp_path: Path) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.config.path = MagicMock(side_effect=lambda *parts: str(tmp_path.joinpath(*parts)))
        hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
        return hass

    @pytest.fixture
    def mock_entry(self) -> MagicMock:
        """Create a mock config entry."""
        entry = MagicMock()
        entry.data = {}
        entry.options = {}
        return entry

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_get_all_automation_statuses(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test get_all_automation_statuses delegates to status manager."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))

        manager._status_manager.add_running_action("automation1", "action", "id1")

        result = manager.get_all_automation_statuses()
        assert set(result) == {"automation1"}
        assert manager.get_automation_status("automation1") is result["automation1"]


class TestAutomationManagerLifecycle:
    """The manager moves automations through the engine's lifecycle."""

    SOURCE = (
        "from haanim import action, startup, shutdown, on_state\n\n"
        "@startup\ndef on_start():\n    record('start ' + __name__)\n\n"
        "@shutdown\ndef on_stop():\n    record('stop ' + __name__)\n\n"
        "@action\ndef ping():\n    return 'pong'\n\n"
        "@on_state(\"sensor.a == 'on'\")\ndef on_a():\n    pass\n"
    )

    @pytest.fixture
    def mock_hass(self, tmp_path: Path) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.config.path = MagicMock(side_effect=lambda *parts: str(tmp_path.joinpath(".ha", *parts)))
        hass.async_create_task = MagicMock(side_effect=lambda coro, **_: coro.close())
        return hass

    @pytest.fixture
    def log(self) -> list[str]:
        """What the automations' startup and shutdown handlers recorded."""
        return []

    @pytest.fixture
    def manager(self, mock_hass: MagicMock, tmp_path: Path, log: list[str]) -> Any:
        """A manager over a temporary automations folder, whose automations can record to the log."""
        automations = tmp_path / "automations"
        automations.mkdir()
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = str(automations)
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        with patch(
            "custom_components.haanim.automation_manager.get_config_manager", return_value=mock_config
        ):
            manager = AutomationManager(
                hass=mock_hass, entry=MagicMock(), host=make_host(files=LocalFileSystem())
            )

        original = AutomationContext.execute

        async def execute(context: AutomationContext) -> Any:
            result = await original(context)
            context.set_symbol("record", log.append)
            return result

        with patch.object(AutomationContext, "execute", execute):
            yield manager

    def write(self, tmp_path: Path, name: str, source: str | None = None) -> Path:
        """Write an automation folder."""
        folder = tmp_path / "automations" / name
        folder.mkdir()
        (folder / "main.py").write_text(source or self.SOURCE)
        return folder

    async def test_loaded_automations_are_off_until_home_assistant_has_started(
        self, manager: AutomationManager, tmp_path: Path, log: list[str]
    ) -> None:
        """Loading runs no automation code; the automation is off."""
        self.write(tmp_path, "lights")

        await manager.async_load_all_automations()

        assert manager.get_automation_state("lights") is AutomationState.OFF
        assert log == []
        with pytest.raises(AutomationNotRunningError):
            await manager.async_call_action("lights", "ping")

    async def test_started_in_ascending_order_and_stopped_in_descending_order(
        self, manager: AutomationManager, tmp_path: Path, log: list[str]
    ) -> None:
        """After Home Assistant starts, automations start by ascending ID; on stop, by descending ID."""
        for name in ("Zeta", "alpha", "Mid"):
            self.write(tmp_path, name)
        triggers = MagicMock()
        triggers.register_trigger = AsyncMock(return_value="id")
        triggers.unregister_automation_triggers = AsyncMock(return_value=1)
        manager.set_trigger_registrar(triggers)

        await manager._on_ha_started(MagicMock())

        assert log == ["start alpha", "start mid", "start zeta"]
        assert [manager.get_automation_state(name) for name in ("alpha", "mid", "zeta")] == [
            AutomationState.ON
        ] * 3
        assert [call.args[0].automation_id for call in triggers.register_trigger.await_args_list] == [
            "alpha",
            "mid",
            "zeta",
        ]
        assert await manager.async_call_action("mid", "ping") == "pong"

        log.clear()
        await manager._on_ha_stop(MagicMock())

        assert log == ["stop zeta", "stop mid", "stop alpha"]
        assert [call.args[0] for call in triggers.unregister_automation_triggers.await_args_list] == [
            "zeta",
            "mid",
            "alpha",
        ]
        assert manager.get_automation_state("alpha") is AutomationState.UNAVAILABLE

    async def test_automation_added_after_start_is_started(
        self, manager: AutomationManager, tmp_path: Path, log: list[str]
    ) -> None:
        """An automation loaded once Home Assistant is running is started right away."""
        await manager._on_ha_started(MagicMock())
        folder = self.write(tmp_path, "lights")

        metadata = await manager.async_load_automation(str(folder))

        assert log == ["start lights"]
        assert manager.get_automation_state("lights") is AutomationState.ON
        assert [action.name for action in metadata.actions] == ["ping", "on_a"]

    async def test_load_error_is_recorded_and_not_started(
        self, manager: AutomationManager, tmp_path: Path, log: list[str]
    ) -> None:
        """An automation that fails to load is reported and never started."""
        folder = self.write(tmp_path, "lights", "import os\n")
        self.write(tmp_path, "heating")

        await manager._on_ha_started(MagicMock())

        assert manager.get_failed_automations() == {
            str(folder): "main.py:1: import of module 'os' is not allowed"
        }
        assert manager.get_automation_state("lights") is AutomationState.ERROR
        assert manager.get_automation_state("heating") is AutomationState.ON
        assert manager.get_context_by_name("lights") is None
        assert log == ["start heating"]

    async def test_failed_start_leaves_the_automation_in_error(
        self, manager: AutomationManager, tmp_path: Path
    ) -> None:
        """An automation whose @startup fails is loaded, in error, and cannot be called."""
        self.write(
            tmp_path,
            "lights",
            "from haanim import startup\n\n@startup\ndef on_start():\n    raise KeyError('x')\n",
        )

        await manager._on_ha_started(MagicMock())

        assert manager.get_automation_state("lights") is AutomationState.ERROR
        with pytest.raises(AutomationNotRunningError):
            await manager.async_call_action("lights", "ping")

    async def test_stop_and_start_through_the_manager(
        self, manager: AutomationManager, tmp_path: Path, log: list[str]
    ) -> None:
        """Stopping and starting an automation runs its handlers and changes its state."""
        self.write(tmp_path, "lights")
        await manager._on_ha_started(MagicMock())
        log.clear()

        await manager.async_stop_automation("lights")
        assert manager.get_automation_state("lights") is AutomationState.OFF
        with pytest.raises(AutomationNotRunningError):
            await manager.async_stop_automation("lights")

        await manager.async_start_automation("lights")
        assert manager.get_automation_state("lights") is AutomationState.ON
        with pytest.raises(AutomationAlreadyRunningError):
            await manager.async_start_automation("lights")

        await manager.async_restart_automation("lights")
        assert log == ["stop lights", "start lights", "stop lights", "start lights"]

    async def test_unknown_automation(self, manager: AutomationManager) -> None:
        """Operations on an automation that is not loaded name it."""
        assert manager.get_automation_state("nope") is AutomationState.UNAVAILABLE
        for operation in (manager.async_start_automation, manager.async_stop_automation):
            with pytest.raises(NonExistingAutomationError):
                await operation("nope")

    async def test_removed_folder_is_stopped_and_unloaded_and_storage_is_kept(
        self, manager: AutomationManager, tmp_path: Path, log: list[str]
    ) -> None:
        """Unloading the automation of a removed folder runs @shutdown and leaves its storage in place."""
        source = (
            "from haanim import action, shutdown, haa\n\n@action\nasync def remember():\n"
            "    haa.set_variable('kept', 'yes')\n\n@action\ndef recall():\n    return haa.get_variable('kept')\n\n"
            "@shutdown\ndef on_stop():\n    record('stop ' + __name__)\n"
        )
        folder = self.write(tmp_path, "lights", source)
        await manager._on_ha_started(MagicMock())
        await manager.async_call_action("lights", "remember")

        assert await manager.async_unload_automation(str(folder)) is True

        assert log == ["stop lights"]
        assert manager.get_automation_state("lights") is AutomationState.UNAVAILABLE
        assert manager.get_context_by_name("lights") is None

        # Put the folder back: the automation is loaded and started again and finds its storage.
        await manager.async_load_automation(str(folder))
        assert await manager.async_call_action("lights", "recall") == "yes"

    async def test_run_action_from_the_gui_needs_a_running_automation(
        self, manager: AutomationManager, tmp_path: Path
    ) -> None:
        """Running an action by hand works while the automation is on, and only then."""
        self.write(tmp_path, "lights")
        await manager.async_load_all_automations()
        with pytest.raises(AutomationNotRunningError):
            await manager.async_run_action("lights", "ping")

        await manager.async_start_automation("lights")

        assert await manager.async_run_action("lights", "ping") == "pong"

    async def test_enable_and_disable_through_the_manager(
        self, manager: AutomationManager, tmp_path: Path, log: list[str]
    ) -> None:
        """Disabling stops the automation and refuses to start it; enabling starts it."""
        self.write(tmp_path, "lights")
        await manager._on_ha_started(MagicMock())
        log.clear()

        await manager.async_disable_automation("lights")
        assert manager.get_automation_state("lights") is AutomationState.OFF
        assert manager.is_automation_enabled("lights") is False
        with pytest.raises(AutomationDisabledError):
            await manager.async_start_automation("lights")
        await manager.async_disable_automation("lights")

        await manager.async_enable_automation("lights")
        assert manager.get_automation_state("lights") is AutomationState.ON
        assert manager.is_automation_enabled("lights") is True
        assert manager.automation_state("lights") == "on"
        assert log == ["stop lights", "start lights"]

    async def test_disabled_automation_is_loaded_but_not_started_after_a_restart(
        self, manager: AutomationManager, mock_hass: MagicMock, tmp_path: Path, log: list[str]
    ) -> None:
        """A disabled automation stays disabled across a restart and across a hot reload."""
        folder = self.write(tmp_path, "lights")
        self.write(tmp_path, "heating")
        await manager._on_ha_started(MagicMock())
        await manager.async_disable_automation("lights")
        await manager._on_ha_stop(MagicMock())
        log.clear()

        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = str(tmp_path / "automations")
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        host = make_host(files=LocalFileSystem(), storage=manager.host.storage)
        with patch(
            "custom_components.haanim.automation_manager.get_config_manager", return_value=mock_config
        ):
            restarted = AutomationManager(hass=mock_hass, entry=MagicMock(), host=host)
        await restarted._on_ha_started(MagicMock())

        assert restarted.get_automation_state("lights") is AutomationState.OFF
        assert restarted.get_automation_state("heating") is AutomationState.ON
        assert restarted.is_automation_enabled("lights") is False
        assert log == ["start heating"]

        # A hot reload of the disabled automation loads it and still does not start it.
        await restarted.async_reload_automation(str(folder))
        assert restarted.get_automation_state("lights") is AutomationState.OFF
        assert log == ["start heating"]

    async def test_error_message_of_an_automation(self, manager: AutomationManager, tmp_path: Path) -> None:
        """The reason for the error state is available by automation ID, also when loading failed."""
        self.write(tmp_path, "broken", "import os\n")
        self.write(
            tmp_path,
            "failing",
            "from haanim import startup\n\n@startup\ndef on_start():\n    raise KeyError('x')\n",
        )
        self.write(tmp_path, "fine")

        await manager._on_ha_started(MagicMock())

        assert manager.automation_message("broken") == "main.py:1: import of module 'os' is not allowed"
        assert manager.automation_message("failing") == "@startup failed: KeyError: 'x'"
        assert manager.automation_message("fine") is None
        assert manager.automation_message("unknown") is None


class TestAutomationManagerHotReload:
    """The manager is kept in step with the files by the engine's hot reloader."""

    ROOT = Path("/config/haanim/automations")
    SOURCE = "from haanim import action\n\n@action\ndef version():\n    return {version}\n"

    @pytest.fixture
    def clock(self) -> FakeClock:
        """The clock the manager and the file system share."""
        return FakeClock()

    @pytest.fixture
    def files(self, clock: FakeClock) -> FakeFileSystem:
        """An in-memory automations folder."""
        return FakeFileSystem(clock)

    @pytest.fixture
    def manager(self, files: FakeFileSystem, clock: FakeClock, tmp_path: Path) -> AutomationManager:
        """A manager over the in-memory folder, rescanning every 10 seconds."""
        hass = MagicMock()
        hass.config.path = MagicMock(side_effect=lambda *parts: str(tmp_path.joinpath(*parts)))
        tasks: list[Any] = []
        hass.async_create_task = MagicMock(
            side_effect=lambda coro, **_: tasks.append(asyncio.ensure_future(coro))
        )
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = str(self.ROOT)
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        with patch(
            "custom_components.haanim.automation_manager.get_config_manager", return_value=mock_config
        ):
            return AutomationManager(hass=hass, entry=MagicMock(), host=make_host(files=files, clock=clock))

    async def test_changed_automation_is_reloaded_after_settling(
        self, manager: AutomationManager, files: FakeFileSystem, clock: FakeClock
    ) -> None:
        """An edit is picked up by the rescans: seen at one, acted on at the next."""
        files.write(self.ROOT / "lights" / "main.py", self.SOURCE.format(version=1))
        await manager._on_ha_started(MagicMock())
        assert await manager.async_call_action("lights", "version") == 1

        await clock.advance(seconds=25)
        assert manager.hass.bus.async_fire.call_count == 1

        files.write(self.ROOT / "lights" / "main.py", self.SOURCE.format(version=2))
        await clock.advance(seconds=5)
        assert await manager.async_call_action("lights", "version") == 1
        await clock.advance(seconds=10)

        assert await manager.async_call_action("lights", "version") == 2
        await manager._on_ha_stop(MagicMock())

    async def test_broken_version_is_in_error_and_fixed_version_runs_again(
        self, manager: AutomationManager, files: FakeFileSystem, clock: FakeClock
    ) -> None:
        """A broken edit leaves the automation in error with the old version stopped; a fix reloads it."""
        files.write(self.ROOT / "lights" / "main.py", self.SOURCE.format(version=1))
        await manager._on_ha_started(MagicMock())

        files.write(self.ROOT / "lights" / "main.py", "def broken(:\n")
        await clock.advance(seconds=20)

        assert manager.get_automation_state("lights") is AutomationState.ERROR
        assert (manager.automation_message("lights") or "").startswith("main.py:1: invalid syntax")
        with pytest.raises(AutomationNotRunningError):
            await manager.async_call_action("lights", "version")

        await clock.advance(seconds=60)
        assert manager.get_automation_state("lights") is AutomationState.ERROR

        files.write(self.ROOT / "lights" / "main.py", self.SOURCE.format(version=3))
        await clock.advance(seconds=20)
        assert manager.get_automation_state("lights") is AutomationState.ON
        assert await manager.async_call_action("lights", "version") == 3
        assert manager.get_failed_automations() == {}
        await manager._on_ha_stop(MagicMock())

    async def test_folders_added_removed_and_renamed(
        self, manager: AutomationManager, files: FakeFileSystem, clock: FakeClock
    ) -> None:
        """Folders that appear are loaded and started; folders that go are stopped and unloaded."""
        files.write(self.ROOT / "lights" / "main.py", self.SOURCE.format(version=1))
        await manager._on_ha_started(MagicMock())

        files.write(self.ROOT / "heating" / "main.py", self.SOURCE.format(version=5))
        await clock.advance(seconds=20)
        assert await manager.async_call_action("heating", "version") == 5

        files.delete(self.ROOT / "lights" / "main.py")
        files.write(self.ROOT / "lamps" / "main.py", self.SOURCE.format(version=1))
        await clock.advance(seconds=20)

        assert manager.get_automation_state("lights") is AutomationState.UNAVAILABLE
        assert manager.get_automation_state("lamps") is AutomationState.ON
        assert sorted(context.automation_id for context in manager.get_all_contexts()) == ["heating", "lamps"]
        await manager._on_ha_stop(MagicMock())

    async def test_asset_change_does_not_reload(
        self, manager: AutomationManager, files: FakeFileSystem, clock: FakeClock
    ) -> None:
        """Changing a file under assets leaves the automation running."""
        files.write(self.ROOT / "lights" / "main.py", self.SOURCE.format(version=1))
        await manager._on_ha_started(MagicMock())
        context = manager.get_context_by_name("lights")

        files.write(self.ROOT / "lights" / "assets" / "sound.txt", "new asset")
        await clock.advance(seconds=40)

        assert manager.get_context_by_name("lights") is context
        await manager._on_ha_stop(MagicMock())

    async def test_rejected_folder_appearing_later_is_reported(
        self, manager: AutomationManager, files: FakeFileSystem, clock: FakeClock
    ) -> None:
        """A folder that cannot be loaded because of its name raises its issue at the rescan, and clears it when gone."""
        files.write(self.ROOT / "lights" / "main.py", self.SOURCE.format(version=1))
        await manager._on_ha_started(MagicMock())

        files.write(self.ROOT / "---" / "main.py", "x = 1\n")
        await clock.advance(seconds=10)
        assert list(manager.host.issues.issues) == ["rejected_folder_---"]

        files.delete(self.ROOT / "---" / "main.py")
        await clock.advance(seconds=10)
        assert manager.host.issues.issues == {}
        await manager._on_ha_stop(MagicMock())
