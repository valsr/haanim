"""Tests for the automation_manager.py module."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from pathlib import Path

import pytest

from haanim.testing import LocalFileSystem, make_host

from custom_components.haanim.const import DOMAIN
from haanim.engine import HAAnimError
from haanim.engine.errors import (
    ActionCancelledError,
    ActionNotFoundError,
    NonExistingAutomationError,
    ShutdownTimeoutError,
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


class TestAutomationManagerLifecycle:
    """Tests for automation manager lifecycle handlers."""

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

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_on_ha_stop(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test _on_ha_stop sets stop event and cleans up."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = str(tmp_path)
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        assert not manager._stop_event.is_set()

        # Call _on_ha_stop
        await manager._on_ha_stop(MagicMock())

        assert manager._stop_event.is_set()

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_action_pool_property(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test action_pool property returns the pool."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        pool = manager.action_pool

        assert pool is manager._action_pool

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

        with pytest.raises(HAAnimError, match="not found"):
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
@action("Add numbers")
async def add(a, b):
    return a + b
"""
        )

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        await manager.async_load_automation(str(automation))

        assert await manager.async_call_action("maths", "add", 2, 3) == 5
        assert await manager.async_call_action("maths", "Add numbers", a=4, b=5) == 9

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
        (automation / "main.py").write_text(
            "from haanim import action\n" "@action\ndef add(a, b):\n    return a + b\n"
        )

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        await manager.async_load_automation(str(automation))

        with pytest.raises(NonExistingAutomationError) as automation_error:
            await manager.async_call_action("nope", "add")
        assert automation_error.value.automation_id == "nope"

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
    async def test_run_all_startup_actions_no_automations(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_all_startup_actions with no automations."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        # Should not raise
        await manager._run_all_startup_actions()

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_run_all_shutdown_actions_no_automations(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_all_shutdown_actions with no automations."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        # Should not raise
        await manager._run_all_shutdown_actions()

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_run_automation_startup_action_no_func(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_automation_startup_action when no startup func."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        mock_context = MagicMock()
        mock_context.get_startup_func.return_value = None

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        # Should not raise when no startup func
        await manager._run_automation_startup_action(mock_context)

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_run_automation_shutdown_action_no_func(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_automation_shutdown_action when no shutdown func."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        mock_context = MagicMock()
        mock_context.get_shutdown_func.return_value = None

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        # Should not raise when no shutdown func
        await manager._run_automation_shutdown_action(mock_context)

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
    async def test_async_unload_automation_runs_shutdown(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test async_unload_automation runs shutdown action."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        # Create mock context
        mock_context = MagicMock()
        mock_context.name = "test_automation"
        mock_context.get_shutdown_func.return_value = None

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._contexts["/tmp/test.py"] = mock_context

        result = await manager.async_unload_automation("/tmp/test.py")
        assert result is True
        assert "/tmp/test.py" not in manager._contexts

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
    async def test_run_all_startup_actions(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_all_startup_actions runs startup for all automations."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        startup_func = AsyncMock()
        mock_context = MagicMock()
        mock_context.automation_id = "test_automation"
        mock_context.get_startup_func.return_value = startup_func

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._contexts["/tmp/test.py"] = mock_context
        manager._action_pool.run_startup_action = AsyncMock()

        await manager._run_all_startup_actions()

        manager._action_pool.run_startup_action.assert_called_once()

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_run_all_startup_actions_no_startup(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_all_startup_actions skips automations without startup."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        mock_context = MagicMock()
        mock_context.automation_id = "test_automation"
        mock_context.get_startup_func.return_value = None

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._contexts["/tmp/test.py"] = mock_context
        manager._action_pool.run_startup_action = AsyncMock()

        await manager._run_all_startup_actions()

        manager._action_pool.run_startup_action.assert_not_called()

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_run_all_shutdown_actions(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_all_shutdown_actions runs shutdown for all automations."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        shutdown_func = AsyncMock()
        mock_context = MagicMock()
        mock_context.automation_id = "test_automation"
        mock_context.get_shutdown_func.return_value = shutdown_func

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._contexts["/tmp/test.py"] = mock_context
        manager._action_pool.run_shutdown_action = AsyncMock()

        await manager._run_all_shutdown_actions()

        manager._action_pool.run_shutdown_action.assert_called_once()

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_run_all_shutdown_actions_no_shutdown(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_all_shutdown_actions skips automations without shutdown."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        mock_context = MagicMock()
        mock_context.automation_id = "test_automation"
        mock_context.get_shutdown_func.return_value = None

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._contexts["/tmp/test.py"] = mock_context
        manager._action_pool.run_shutdown_action = AsyncMock()

        await manager._run_all_shutdown_actions()

        manager._action_pool.run_shutdown_action.assert_not_called()

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_run_automation_startup_action(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_automation_startup_action runs startup for single automation."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        startup_func = AsyncMock()
        mock_context = MagicMock()
        mock_context.automation_id = "test_automation"
        mock_context.get_startup_func.return_value = startup_func

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._action_pool.run_startup_action = AsyncMock()

        await manager._run_automation_startup_action(mock_context)

        manager._action_pool.run_startup_action.assert_called_once()

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_run_automation_shutdown_action(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_automation_shutdown_action runs shutdown for single automation."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        shutdown_func = AsyncMock()
        mock_context = MagicMock()
        mock_context.automation_id = "test_automation"
        mock_context.get_shutdown_func.return_value = shutdown_func

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._action_pool.run_shutdown_action = AsyncMock()

        await manager._run_automation_shutdown_action(mock_context)

        manager._action_pool.run_shutdown_action.assert_called_once()

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
    async def test_run_automation_startup_action_no_func(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_automation_startup_action does nothing when no startup func."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        mock_action_pool = MagicMock()
        mock_action_pool.run_startup_action = AsyncMock()
        manager._action_pool = mock_action_pool

        # Create a context with no startup func
        mock_context = MagicMock()
        mock_context.get_startup_func.return_value = None

        # Should complete without error
        await manager._run_automation_startup_action(mock_context)
        mock_action_pool.run_startup_action.assert_not_called()

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_run_automation_shutdown_action_no_func(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_automation_shutdown_action does nothing when no shutdown func."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        mock_action_pool = MagicMock()
        mock_action_pool.run_shutdown_action = AsyncMock()
        manager._action_pool = mock_action_pool

        # Create a context with no shutdown func
        mock_context = MagicMock()
        mock_context.get_shutdown_func.return_value = None

        # Should complete without error
        await manager._run_automation_shutdown_action(mock_context)
        mock_action_pool.run_shutdown_action.assert_not_called()

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_run_automation_startup_action_success(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_automation_startup_action runs startup func successfully."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._action_pool.run_startup_action = AsyncMock()

        # Create a context with startup func
        mock_startup = AsyncMock()
        mock_context = MagicMock()
        mock_context.get_startup_func.return_value = mock_startup
        mock_context.automation_id = "test_automation"

        await manager._run_automation_startup_action(mock_context)
        manager._action_pool.run_startup_action.assert_called_once()

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_run_automation_shutdown_action_success(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_automation_shutdown_action runs shutdown func successfully."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        manager._action_pool.run_shutdown_action = AsyncMock()

        # Create a context with shutdown func
        mock_shutdown = AsyncMock()
        mock_context = MagicMock()
        mock_context.get_shutdown_func.return_value = mock_shutdown
        mock_context.automation_id = "test_automation"

        await manager._run_automation_shutdown_action(mock_context)
        manager._action_pool.run_shutdown_action.assert_called_once()

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

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_run_automation_shutdown_action_timeout_error(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_automation_shutdown_action handles timeout error."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        mock_action_pool = MagicMock()
        mock_action_pool.run_shutdown_action = AsyncMock(
            side_effect=ShutdownTimeoutError("test_automation", 10)
        )
        manager._action_pool = mock_action_pool

        mock_shutdown = AsyncMock()
        mock_context = MagicMock()
        mock_context.get_shutdown_func.return_value = mock_shutdown
        mock_context.automation_id = "test_automation"

        # Should not raise, just log error
        await manager._run_automation_shutdown_action(mock_context)

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_run_automation_shutdown_action_cancelled(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_automation_shutdown_action handles cancelled error."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        mock_action_pool = MagicMock()
        mock_action_pool.run_shutdown_action = AsyncMock(side_effect=ActionCancelledError("cancelled"))
        manager._action_pool = mock_action_pool

        mock_shutdown = AsyncMock()
        mock_context = MagicMock()
        mock_context.get_shutdown_func.return_value = mock_shutdown
        mock_context.automation_id = "test_automation"

        await manager._run_automation_shutdown_action(mock_context)

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_run_automation_shutdown_action_generic_error(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_automation_shutdown_action handles generic error."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        mock_action_pool = MagicMock()
        mock_action_pool.run_shutdown_action = AsyncMock(side_effect=RuntimeError("generic error"))
        manager._action_pool = mock_action_pool

        mock_shutdown = AsyncMock()
        mock_context = MagicMock()
        mock_context.get_shutdown_func.return_value = mock_shutdown
        mock_context.automation_id = "test_automation"

        await manager._run_automation_shutdown_action(mock_context)

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_run_automation_startup_action_cancelled(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_automation_startup_action handles cancelled error."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        mock_action_pool = MagicMock()
        mock_action_pool.run_startup_action = AsyncMock(side_effect=ActionCancelledError("cancelled"))
        manager._action_pool = mock_action_pool

        mock_startup = AsyncMock()
        mock_context = MagicMock()
        mock_context.get_startup_func.return_value = mock_startup
        mock_context.automation_id = "test_automation"

        await manager._run_automation_startup_action(mock_context)

    @patch("custom_components.haanim.automation_manager.get_config_manager")
    async def test_run_automation_startup_action_generic_error(
        self,
        mock_get_config: MagicMock,
        mock_hass: MagicMock,
        mock_entry: MagicMock,
    ) -> None:
        """Test _run_automation_startup_action handles generic error."""
        mock_config = MagicMock()
        mock_config.get_automation_path.return_value = "/tmp"
        mock_config.get_import_allowlist.return_value = []
        mock_config.get_allow_all_imports.return_value = False
        mock_get_config.return_value = mock_config

        manager = AutomationManager(hass=mock_hass, entry=mock_entry, host=make_host(files=LocalFileSystem()))
        mock_action_pool = MagicMock()
        mock_action_pool.run_startup_action = AsyncMock(side_effect=RuntimeError("generic error"))
        manager._action_pool = mock_action_pool

        mock_startup = AsyncMock()
        mock_context = MagicMock()
        mock_context.get_startup_func.return_value = mock_startup
        mock_context.automation_id = "test_automation"

        await manager._run_automation_startup_action(mock_context)
