"""Tests for the api.py module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.haanim.api import (
    ActionsListView,
    ConfigView,
    HAAnimAPIView,
    ReloadScriptsView,
    RunActionView,
    ScriptsListView,
    async_register_api,
)
from custom_components.haanim.const import DOMAIN


class TestHAAnimAPIView:
    """Tests for base HAAnimAPIView class."""

    def test_requires_auth(self) -> None:
        """Test that authentication is required."""
        view = HAAnimAPIView()
        assert view.requires_auth is True


class TestScriptsListView:
    """Tests for ScriptsListView."""

    def test_url_and_name(self) -> None:
        """Test the URL and name are set correctly."""
        view = ScriptsListView()
        assert view.url is not None
        assert f"/api/{DOMAIN}/scripts" in view.url
        assert DOMAIN in view.name

    @patch("custom_components.haanim.api.async_get_manager")
    async def test_get_no_manager(self, mock_get_manager: MagicMock) -> None:
        """Test GET returns error when manager not available."""
        mock_get_manager.return_value = None

        view = ScriptsListView()
        request = MagicMock()
        request.app = {"hass": MagicMock()}

        # Mock json method
        with patch.object(view, "json", return_value=MagicMock()) as mock_json:
            await view.get(request)
            mock_json.assert_called_once()
            call_args = mock_json.call_args[0][0]
            assert call_args["scripts"] == []
            assert "error" in call_args

    @patch("custom_components.haanim.api.async_get_manager")
    async def test_get_returns_scripts(self, mock_get_manager: MagicMock) -> None:
        """Test GET returns script list."""
        mock_manager = MagicMock()
        mock_metadata = MagicMock()
        mock_metadata.name = "test_script"
        mock_metadata.path = "/path/to/script.py"
        mock_metadata.actions = []
        mock_metadata.triggers = []
        mock_metadata.enabled = True
        mock_manager.get_all_metadata.return_value = [mock_metadata]
        mock_get_manager.return_value = mock_manager

        view = ScriptsListView()
        request = MagicMock()
        request.app = {"hass": MagicMock()}

        with patch.object(view, "json", return_value=MagicMock()) as mock_json:
            await view.get(request)
            call_args = mock_json.call_args[0][0]
            assert len(call_args["scripts"]) == 1
            assert call_args["scripts"][0]["name"] == "test_script"


class TestActionsListView:
    """Tests for ActionsListView."""

    def test_url_and_name(self) -> None:
        """Test the URL and name are set correctly."""
        view = ActionsListView()
        assert view.url is not None
        assert f"/api/{DOMAIN}/actions" in view.url
        assert DOMAIN in view.name

    @patch("custom_components.haanim.api.async_get_manager")
    async def test_get_no_manager(self, mock_get_manager: MagicMock) -> None:
        """Test GET returns error when manager not available."""
        mock_get_manager.return_value = None

        view = ActionsListView()
        request = MagicMock()
        request.app = {"hass": MagicMock()}
        request.query = {}

        with patch.object(view, "json", return_value=MagicMock()) as mock_json:
            await view.get(request)
            call_args = mock_json.call_args[0][0]
            assert call_args["actions"] == []
            assert "error" in call_args

    @patch("custom_components.haanim.api.async_get_manager")
    async def test_get_returns_actions(self, mock_get_manager: MagicMock) -> None:
        """Test GET returns actions list."""
        mock_manager = MagicMock()
        mock_action = MagicMock()
        mock_action.name = "my_action"
        mock_action.func_name = "my_func"
        mock_action.script_name = "test_script"
        mock_action.description = "A test action"
        mock_manager.get_all_actions.return_value = [mock_action]
        mock_get_manager.return_value = mock_manager

        view = ActionsListView()
        request = MagicMock()
        request.app = {"hass": MagicMock()}
        request.query = {}

        with patch.object(view, "json", return_value=MagicMock()) as mock_json:
            await view.get(request)
            call_args = mock_json.call_args[0][0]
            assert len(call_args["actions"]) == 1
            assert call_args["actions"][0]["name"] == "my_action"

    @patch("custom_components.haanim.api.async_get_manager")
    async def test_get_filters_by_script(self, mock_get_manager: MagicMock) -> None:
        """Test GET filters actions by script name."""
        mock_manager = MagicMock()
        mock_action1 = MagicMock()
        mock_action1.name = "action1"
        mock_action1.func_name = "func1"
        mock_action1.script_name = "script1"
        mock_action1.description = ""
        mock_action2 = MagicMock()
        mock_action2.name = "action2"
        mock_action2.func_name = "func2"
        mock_action2.script_name = "script2"
        mock_action2.description = ""
        mock_manager.get_all_actions.return_value = [mock_action1, mock_action2]
        mock_get_manager.return_value = mock_manager

        view = ActionsListView()
        request = MagicMock()
        request.app = {"hass": MagicMock()}
        request.query = {"script_name": "script1"}

        with patch.object(view, "json", return_value=MagicMock()) as mock_json:
            await view.get(request)
            call_args = mock_json.call_args[0][0]
            assert len(call_args["actions"]) == 1
            assert call_args["actions"][0]["script_name"] == "script1"


class TestConfigView:
    """Tests for ConfigView."""

    def test_url_and_name(self) -> None:
        """Test the URL and name are set correctly."""
        view = ConfigView()
        assert view.url is not None
        assert f"/api/{DOMAIN}/config" in view.url
        assert DOMAIN in view.name

    @patch("custom_components.haanim.api.get_config_manager")
    async def test_get_returns_config(self, mock_get_config: MagicMock) -> None:
        """Test GET returns configuration."""
        mock_config = MagicMock()
        mock_config.get_all.return_value = {"setting1": "value1"}
        mock_config.load_from_dict = MagicMock()
        mock_get_config.return_value = mock_config

        view = ConfigView()
        request = MagicMock()
        request.app = {"hass": MagicMock()}
        request.app["hass"].data = {}

        with patch.object(view, "json", return_value=MagicMock()) as mock_json:
            await view.get(request)
            call_args = mock_json.call_args[0][0]
            assert "setting1" in call_args
            assert "version" in call_args


class TestRunActionView:
    """Tests for RunActionView."""

    def test_url_and_name(self) -> None:
        """Test the URL and name are set correctly."""
        view = RunActionView()
        assert view.url is not None
        assert f"/api/{DOMAIN}/run_action" in view.url
        assert DOMAIN in view.name

    @patch("custom_components.haanim.api.async_get_manager")
    async def test_post_missing_params(self, _: MagicMock) -> None:
        """Test POST returns error when params missing."""
        view = RunActionView()
        request = MagicMock()
        request.app = {"hass": MagicMock()}
        request.json = AsyncMock(return_value={})

        with patch.object(view, "json", return_value=MagicMock()) as mock_json:
            await view.post(request)
            call_args = mock_json.call_args[0][0]
            assert call_args["success"] is False
            assert "Missing" in call_args["error"]

    @patch("custom_components.haanim.api.async_get_manager")
    async def test_post_invalid_json(self, _: MagicMock) -> None:
        """Test POST handles invalid JSON."""
        view = RunActionView()
        request = MagicMock()
        request.app = {"hass": MagicMock()}
        request.json = AsyncMock(side_effect=ValueError("Invalid JSON"))

        with patch.object(view, "json", return_value=MagicMock()) as mock_json:
            await view.post(request)
            call_args = mock_json.call_args[0][0]
            assert call_args["success"] is False
            assert "Invalid JSON" in call_args["error"]

    @patch("custom_components.haanim.api.async_get_manager")
    async def test_post_no_manager(self, mock_get_manager: MagicMock) -> None:
        """Test POST returns error when manager not available."""
        mock_get_manager.return_value = None

        view = RunActionView()
        request = MagicMock()
        request.app = {"hass": MagicMock()}
        request.json = AsyncMock(
            return_value={"script_name": "test", "action_name": "action"}
        )

        with patch.object(view, "json", return_value=MagicMock()) as mock_json:
            await view.post(request)
            call_args = mock_json.call_args[0][0]
            assert call_args["success"] is False
            assert "manager not available" in call_args["error"]

    @patch("custom_components.haanim.api.async_get_manager")
    async def test_post_success(self, mock_get_manager: MagicMock) -> None:
        """Test POST successfully runs action."""
        mock_manager = MagicMock()
        mock_manager.async_run_action = AsyncMock()
        mock_get_manager.return_value = mock_manager

        view = RunActionView()
        request = MagicMock()
        request.app = {"hass": MagicMock()}
        request.json = AsyncMock(
            return_value={"script_name": "test", "action_name": "action"}
        )

        with patch.object(view, "json", return_value=MagicMock()) as mock_json:
            await view.post(request)
            call_args = mock_json.call_args[0][0]
            assert call_args["success"] is True
            mock_manager.async_run_action.assert_called_once_with(
                "test", "action", manual=True
            )


class TestReloadScriptsView:
    """Tests for ReloadScriptsView."""

    def test_url_and_name(self) -> None:
        """Test the URL and name are set correctly."""
        view = ReloadScriptsView()
        assert view.url is not None
        assert f"/api/{DOMAIN}/reload" in view.url
        assert DOMAIN in view.name

    @patch("custom_components.haanim.api.async_get_manager")
    async def test_post_no_manager(self, mock_get_manager: MagicMock) -> None:
        """Test POST returns error when manager not available."""
        mock_get_manager.return_value = None

        view = ReloadScriptsView()
        request = MagicMock()
        request.app = {"hass": MagicMock()}

        with patch.object(view, "json", return_value=MagicMock()) as mock_json:
            await view.post(request)
            call_args = mock_json.call_args[0][0]
            assert call_args["success"] is False

    @patch("custom_components.haanim.api.async_get_manager")
    async def test_post_success(self, mock_get_manager: MagicMock) -> None:
        """Test POST successfully reloads scripts."""
        mock_manager = MagicMock()
        mock_manager.async_reload_all_scripts = AsyncMock()
        mock_get_manager.return_value = mock_manager

        view = ReloadScriptsView()
        request = MagicMock()
        request.app = {"hass": MagicMock()}

        with patch.object(view, "json", return_value=MagicMock()) as mock_json:
            await view.post(request)
            call_args = mock_json.call_args[0][0]
            assert call_args["success"] is True
            mock_manager.async_reload_all_scripts.assert_called_once()


class TestAsyncRegisterAPI:
    """Tests for async_register_api function."""

    def test_registers_all_views(self) -> None:
        """Test that all views are registered."""
        hass = MagicMock()
        hass.http.register_view = MagicMock()

        async_register_api(hass)

        # Should register 5 views
        assert hass.http.register_view.call_count == 5


class TestRunActionViewErrors:
    """Tests for error handling in RunActionView."""

    @patch("custom_components.haanim.api.async_get_manager")
    async def test_post_action_fails(self, mock_get_manager: MagicMock) -> None:
        """Test POST returns error when action fails."""
        mock_manager = MagicMock()
        mock_manager.async_run_action = AsyncMock(
            side_effect=RuntimeError("Action failed")
        )
        mock_get_manager.return_value = mock_manager

        view = RunActionView()
        request = MagicMock()
        request.app = {"hass": MagicMock()}
        request.json = AsyncMock(return_value={
            "script_name": "test_script",
            "action_name": "test_action",
        })

        with patch.object(view, "json", return_value=MagicMock()) as mock_json:
            await view.post(request)
            call_args = mock_json.call_args[0][0]
            assert call_args["success"] is False
            assert "error" in call_args


class TestReloadScriptsViewErrors:
    """Tests for error handling in ReloadScriptsView."""

    @patch("custom_components.haanim.api.async_get_manager")
    async def test_post_reload_fails(self, mock_get_manager: MagicMock) -> None:
        """Test POST returns error when reload fails."""
        mock_manager = MagicMock()
        mock_manager.async_reload_all_scripts = AsyncMock(
            side_effect=RuntimeError("Reload failed")
        )
        mock_get_manager.return_value = mock_manager

        view = ReloadScriptsView()
        request = MagicMock()
        request.app = {"hass": MagicMock()}

        with patch.object(view, "json", return_value=MagicMock()) as mock_json:
            await view.post(request)
            call_args = mock_json.call_args[0][0]
            assert call_args["success"] is False
            assert "error" in call_args


class TestConfigViewEdgeCases:
    """Edge case tests for ConfigView."""

    @patch("custom_components.haanim.api.get_config_manager")
    async def test_get_loads_from_entry(self, mock_get_config: MagicMock) -> None:
        """Test GET loads config from entry."""
        mock_config_mgr = MagicMock()
        mock_config_mgr.get_all.return_value = {"option1": "value1"}
        mock_get_config.return_value = mock_config_mgr

        view = ConfigView()
        mock_entry = MagicMock()
        mock_entry.data = {"key": "value"}
        mock_entry.options = {"opt": "val"}

        request = MagicMock()
        mock_hass = MagicMock()
        mock_hass.data = {DOMAIN: {"entry_id": {"entry": mock_entry}}}
        request.app = {"hass": mock_hass}

        with patch.object(view, "json", return_value=MagicMock()) as mock_json:
            await view.get(request)
            mock_config_mgr.load_from_dict.assert_called_once_with(
                mock_entry.data, mock_entry.options
            )
            call_args = mock_json.call_args[0][0]
            assert "version" in call_args
