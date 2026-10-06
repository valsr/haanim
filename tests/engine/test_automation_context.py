"""Tests for the engine/automation_context.py module."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from haanim.testing import make_host
from tests.engine.helpers import automation_file, load_and_run, make_context
from haanim.engine.errors import PUBLIC_ERRORS, HAAnimError
from haanim.engine.automation_context import (
    ActionDefinition,
    AutomationContext,
    AutomationMetadata,
    TriggerDefinition,
)


class TestActionDefinition:
    """Tests for ActionDefinition dataclass."""

    @pytest.mark.parametrize(
        ("name", "func_name", "automation_id"),
        [
            ("my_action", "do_action", "test_automation"),
            ("other_action", "other_func", "automation2"),
        ],
    )
    def test_creation(self, name: str, func_name: str, automation_id: str) -> None:
        """Test creating an ActionDefinition."""
        func = MagicMock()
        action = ActionDefinition(
            name=name,
            func_name=func_name,
            func=func,
            description="Test description",
            automation_id=automation_id,
        )
        assert action.name == name
        assert action.func_name == func_name
        assert action.func is func
        assert action.description == "Test description"
        assert action.automation_id == automation_id

    def test_default_values(self) -> None:
        """Test default values."""
        func = MagicMock()
        action = ActionDefinition(
            name="action",
            func_name="action_func",
            func=func,
            automation_id="automation",
        )
        assert action.description is None


class TestTriggerDefinition:
    """Tests for TriggerDefinition dataclass."""

    @pytest.mark.parametrize(
        ("trigger_type", "trigger_expr"),
        [
            ("state", "sensor.temperature > 25"),
            ("time", "cron(0 * * * *)"),
            ("event", "my_custom_event"),
        ],
    )
    def test_creation(self, trigger_type: str, trigger_expr: str) -> None:
        """Test creating a TriggerDefinition."""
        func = MagicMock()
        trigger = TriggerDefinition(
            trigger_type=trigger_type,
            trigger_expr=trigger_expr,
            func_name="trigger_func",
            func=func,
            kwargs={"extra": "value"},
            automation_id="test_automation",
        )
        assert trigger.trigger_type == trigger_type
        assert trigger.trigger_expr == trigger_expr
        assert trigger.func_name == "trigger_func"
        assert trigger.func is func
        assert trigger.kwargs == {"extra": "value"}
        assert trigger.automation_id == "test_automation"


class TestAutomationMetadata:
    """Tests for AutomationMetadata dataclass."""

    def test_creation(self) -> None:
        """Test creating AutomationMetadata."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        actions = [
            ActionDefinition(
                name="action1",
                func_name="func1",
                func=MagicMock(),
                automation_id="test",
            )
        ]
        triggers = [
            TriggerDefinition(
                trigger_type="state",
                trigger_expr="sensor.test == 'on'",
                func_name="trigger_func",
                func=MagicMock(),
                kwargs={},
                automation_id="test",
            )
        ]
        metadata = AutomationMetadata(
            id="Test Automation",
            path="/path/to/automation.py",
            filename="automation.py",
            loaded_at=now,
            modified_at=now,
            actions=actions,
            triggers=triggers,
            has_startup=True,
            has_shutdown=False,
        )

        assert metadata.id == "Test Automation"
        assert metadata.path == "/path/to/automation.py"
        assert metadata.filename == "automation.py"
        assert metadata.loaded_at == now
        assert metadata.modified_at == now
        assert metadata.actions == actions
        assert metadata.triggers == triggers
        assert metadata.has_startup is True
        assert metadata.has_shutdown is False
        assert metadata.enabled is True  # Default

    def test_default_enabled(self) -> None:
        """Test default enabled value."""
        metadata = AutomationMetadata(
            id="Test",
            path="/path/automation.py",
            filename="automation.py",
            loaded_at=datetime(2024, 1, 15, 12, 0, 0),
            modified_at=datetime(2024, 1, 15, 12, 0, 0),
            actions=[],
            triggers=[],
            has_startup=False,
            has_shutdown=False,
        )
        assert metadata.enabled is True


class TestAutomationContext:
    """Tests for AutomationContext class."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock()
        return hass

    def test_init(self, mock_hass: MagicMock) -> None:
        """Test AutomationContext initialization."""
        host = make_host()
        context = make_context("/automations/test", host=host)
        assert context.host is host
        assert context.automation_path == "/automations/test"
        assert context.automation_id == "test"
        assert context.filename == "main.py"

    @pytest.mark.parametrize(
        ("path", "expected_name", "expected_filename"),
        [
            ("/automations/my_automation", "my_automation", "main.py"),
            ("/home/user/My Automation", "my_automation", "main.py"),
            ("./Café  Lights.v2", "cafe_lights_v2", "main.py"),
        ],
    )
    def test_automation_id_from_path(
        self,
        mock_hass: MagicMock,
        path: str,
        expected_name: str,
        expected_filename: str,
    ) -> None:
        """Test the automation ID is the slug of the folder name."""
        context = make_context(
            automation_path=path,
        )
        assert context.automation_id == expected_name
        assert context.filename == expected_filename

    def test_is_loaded_initially_false(self, mock_hass: MagicMock) -> None:
        """Test is_loaded is False before loading."""
        context = make_context(
            automation_path="/automations/test",
        )
        assert context.is_loaded is False

    def test_get_metadata_before_load(self, mock_hass: MagicMock) -> None:
        """Test get_metadata returns None before loading."""
        context = make_context(
            automation_path="/automations/test",
        )
        assert context.get_metadata() is None

    def test_get_actions_before_load(self, mock_hass: MagicMock) -> None:
        """Test get_actions returns empty list before loading."""
        context = make_context(
            automation_path="/automations/test",
        )
        assert context.get_actions() == []

    def test_get_triggers_before_load(self, mock_hass: MagicMock) -> None:
        """Test get_triggers returns empty list before loading."""
        context = make_context(
            automation_path="/automations/test",
        )
        assert context.get_triggers() == []

    def test_get_startup_func_before_load(self, mock_hass: MagicMock) -> None:
        """Test get_startup_func returns None before loading."""
        context = make_context(
            automation_path="/automations/test",
        )
        assert context.get_startup_func() is None

    def test_get_shutdown_func_before_load(self, mock_hass: MagicMock) -> None:
        """Test get_shutdown_func returns None before loading."""
        context = make_context(
            automation_path="/automations/test",
        )
        assert context.get_shutdown_func() is None


class TestAutomationContextLoad:
    """Tests for AutomationContext.load method."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
        return hass

    async def test_load_nonexistent_file(self, mock_hass: MagicMock) -> None:
        """Test loading non-existent file raises error."""
        from haanim.engine.errors import HAAnimError

        context = make_context(
            automation_path="/nonexistent/path/automation",
        )

        with pytest.raises(HAAnimError, match="Automation has no main.py"):
            await load_and_run(context)

    async def test_load_simple_automation(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading a simple valid automation."""
        automation_path = automation_file(tmp_path, "test_automation")
        automation_path.write_text(
            """
from haanim import action
@action
def my_action():
    pass
"""
        )

        context = make_context(
            automation_path=str(automation_path),
        )

        metadata = await load_and_run(context)

        assert metadata is not None
        assert metadata.id == "test_automation"
        assert len(metadata.actions) == 1
        assert metadata.actions[0].name == "my_action"

    @pytest.mark.parametrize("error_class", PUBLIC_ERRORS, ids=lambda cls: cls.__name__)
    async def test_errors_importable_from_haanim(
        self, mock_hass: MagicMock, tmp_path: Any, error_class: type[HAAnimError]
    ) -> None:
        """Test every public error can be imported from the haanim module by an automation."""
        name = error_class.__name__
        automation_path = automation_file(tmp_path, "imports_error")
        automation_path.write_text(f"from haanim import {name}\nimported = {name}\n")

        context = make_context(str(automation_path))
        await load_and_run(context)

        assert context.get_symbol("imported") is error_class

    async def test_internal_errors_not_importable_from_haanim(
        self, mock_hass: MagicMock, tmp_path: Any
    ) -> None:
        """Test errors outside the public list are not exported to automations."""
        automation_path = automation_file(tmp_path, "imports_internal")
        automation_path.write_text("from haanim import ShutdownTimeoutError\n")

        context = make_context(str(automation_path))
        with pytest.raises(ImportError, match="cannot import name 'ShutdownTimeoutError' from 'haanim'"):
            await load_and_run(context)

    async def test_load_automation_with_triggers(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading an automation with triggers."""
        automation_path = automation_file(tmp_path, "trigger_automation")
        automation_path.write_text(
            """
from haanim import on_state, on_time
@on_state("sensor.test > 50")
def on_temp_high():
    pass

@on_time("cron(0 * * * *)")
def on_hour():
    pass
"""
        )

        context = make_context(
            automation_path=str(automation_path),
        )

        metadata = await load_and_run(context)

        assert len(metadata.triggers) == 2
        trigger_types = {t.trigger_type for t in metadata.triggers}
        assert "state" in trigger_types
        assert "time" in trigger_types

    async def test_load_automation_with_startup_shutdown(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading an automation with startup and shutdown."""
        automation_path = automation_file(tmp_path, "lifecycle_automation")
        automation_path.write_text(
            """
from haanim import startup, shutdown
@startup
def on_startup():
    pass

@shutdown
def on_shutdown():
    pass
"""
        )

        context = make_context(
            automation_path=str(automation_path),
        )

        metadata = await load_and_run(context)

        assert metadata.has_startup is True
        assert metadata.has_shutdown is True
        assert context.get_startup_func() is not None
        assert context.get_shutdown_func() is not None

    async def test_load_automation_with_syntax_error(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading an automation with syntax error raises error."""
        from haanim.engine.errors import HAAnimError

        automation_path = automation_file(tmp_path, "bad_automation")
        automation_path.write_text(
            """
def broken(:
    pass
"""
        )

        context = make_context(
            automation_path=str(automation_path),
        )

        with pytest.raises(HAAnimError, match=r"^main.py:2: invalid syntax"):
            await load_and_run(context)


class TestAutomationContextGetters:
    """Tests for AutomationContext getter methods."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(
            side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)
        )
        return hass

    async def test_get_actions(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test get_actions returns action definitions."""
        automation_path = automation_file(tmp_path, "action_automation")
        automation_path.write_text(
            """
from haanim import action
@action(name="First Action")
def first():
    pass

@action(name="Second Action")
def second():
    pass
"""
        )

        context = make_context(str(automation_path))
        await load_and_run(context)

        actions = context.get_actions()
        assert len(actions) == 2

    async def test_get_triggers(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test get_triggers returns trigger definitions."""
        automation_path = automation_file(tmp_path, "trigger_automation")
        automation_path.write_text(
            """
from haanim import on_state
@on_state("sensor.test > 50")
def on_high():
    pass
"""
        )

        context = make_context(str(automation_path))
        await load_and_run(context)

        triggers = context.get_triggers()
        assert len(triggers) == 1

    async def test_get_metadata(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test get_metadata returns automation metadata."""
        automation_path = automation_file(tmp_path, "meta_automation")
        automation_path.write_text(
            """
from haanim import action
@action(name="Test")
def test():
    pass
"""
        )

        context = make_context(str(automation_path))
        await load_and_run(context)

        metadata = context.get_metadata()
        assert metadata is not None
        assert metadata.filename == "main.py"
        assert metadata.name == "meta_automation"

    def test_get_metadata_not_loaded(self, mock_hass: MagicMock) -> None:
        """Test get_metadata returns None when not loaded."""
        context = make_context("/fake/path.py")
        assert context.get_metadata() is None

    async def test_automation_id_property(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test automation_id property returns name without .py."""
        automation_path = automation_file(tmp_path, "my_cool_automation")
        automation_path.write_text("x = 1")

        context = make_context(str(automation_path))
        assert context.automation_id == "my_cool_automation"

    async def test_filename_property(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test filename property returns filename with .py."""
        automation_path = automation_file(tmp_path, "my_automation")
        automation_path.write_text("x = 1")

        context = make_context(str(automation_path))
        assert context.filename == "main.py"


class TestAutomationContextEdgeCases:
    """Tests for AutomationContext edge cases."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(
            side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)
        )
        return hass

    async def test_load_minimal_automation(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading a minimal automation with just a variable."""
        automation_path = automation_file(tmp_path, "minimal")
        automation_path.write_text("x = 1")

        context = make_context(str(automation_path))
        metadata = await load_and_run(context)

        assert metadata.id == "minimal"
        assert len(metadata.actions) == 0
        assert len(metadata.triggers) == 0

    async def test_load_automation_with_action_name(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading an automation with @action decorator sets display name."""
        automation_path = automation_file(tmp_path, "my_automation")
        automation_path.write_text(
            """
from haanim import action
@action(name="My Custom Action")
def do_something():
    pass
"""
        )

        context = make_context(str(automation_path))
        metadata = await load_and_run(context)

        # Should have an action with custom name
        assert len(metadata.actions) == 1
        assert metadata.actions[0].name == "My Custom Action"

    async def test_load_automation_file_not_found(self, mock_hass: MagicMock) -> None:
        """Test loading a non-existent automation raises HAAnimError."""
        from haanim.engine.errors import HAAnimError

        context = make_context("/nonexistent/path")

        with pytest.raises(HAAnimError, match="has no main.py"):
            await load_and_run(context)

    async def test_get_startup_func_none(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test get_startup_func returns None when no startup defined."""
        automation_path = automation_file(tmp_path, "no_startup")
        automation_path.write_text("x = 1")

        context = make_context(str(automation_path))
        await load_and_run(context)

        assert context.get_startup_func() is None

    async def test_get_shutdown_func_none(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test get_shutdown_func returns None when no shutdown defined."""
        automation_path = automation_file(tmp_path, "no_shutdown")
        automation_path.write_text("x = 1")

        context = make_context(str(automation_path))
        await load_and_run(context)

        assert context.get_shutdown_func() is None


class TestTriggersAsActions:
    """Tests for triggers automatically being actions."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(
            side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)
        )
        return hass

    async def test_triggered_function_is_action(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test that a function with triggers is automatically an action."""
        automation_path = automation_file(tmp_path, "trigger_automation")
        automation_path.write_text(
            """
from haanim import on_state
@on_state("sensor.test > 50")
def on_high():
    pass
"""
        )

        context = make_context(str(automation_path))
        metadata = await load_and_run(context)

        # Should have both a trigger and an action
        assert len(metadata.triggers) == 1
        assert len(metadata.actions) == 1
        assert metadata.actions[0].func_name == "on_high"

    async def test_multiple_triggers_single_action(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test that multiple triggers on one function still creates one action."""
        automation_path = automation_file(tmp_path, "multi_trigger")
        automation_path.write_text(
            """
from haanim import on_state, on_time
@on_state("sensor.a > 10")
@on_state("sensor.b < 5")
@on_time("cron(0 8 * * *)")
def multi_trigger():
    pass
"""
        )

        context = make_context(str(automation_path))
        metadata = await load_and_run(context)

        # Should have 3 triggers but only 1 action
        assert len(metadata.triggers) == 3
        assert len(metadata.actions) == 1
        assert metadata.actions[0].func_name == "multi_trigger"

    async def test_triggered_action_with_metadata(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test that triggered function with @action decorator gets metadata."""
        automation_path = automation_file(tmp_path, "trigger_with_action")
        automation_path.write_text(
            """
from haanim import action, on_state
@action(name="Custom Name", description="Custom description")
@on_state("sensor.test > 50")
def custom_action():
    pass
"""
        )

        context = make_context(str(automation_path))
        metadata = await load_and_run(context)

        # Should have trigger and action with custom metadata
        assert len(metadata.triggers) == 1
        assert len(metadata.actions) == 1
        action = metadata.actions[0]
        assert action.name == "Custom Name"
        assert action.description == "Custom description"

    async def test_triggered_action_default_settings(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test that triggered function without @action gets default settings."""
        automation_path = automation_file(tmp_path, "trigger_only")
        automation_path.write_text(
            """
from haanim import on_time
@on_time("sunset")
def evening_lights():
    pass
"""
        )

        context = make_context(str(automation_path))
        metadata = await load_and_run(context)

        # Should have action with default settings
        assert len(metadata.actions) == 1
        action = metadata.actions[0]
        assert action.name == "evening_lights"  # Uses function name
        assert action.description is None

    async def test_action_without_trigger(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test that @action without triggers still works."""
        automation_path = automation_file(tmp_path, "action_only")
        automation_path.write_text(
            """
from haanim import action
@action(name="Manual Action")
def manual_only():
    pass
"""
        )

        context = make_context(str(automation_path))
        metadata = await load_and_run(context)

        # Should have action but no triggers
        assert len(metadata.actions) == 1
        assert len(metadata.triggers) == 0
        assert metadata.actions[0].name == "Manual Action"

    async def test_mixed_actions_and_triggers(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test automation with mix of actions, triggers, and combined."""
        automation_path = automation_file(tmp_path, "mixed")
        automation_path.write_text(
            """
from haanim import action, on_state, on_time
@action(name="Manual Only")
def manual():
    pass

@on_state("sensor.a > 10")
def auto_only():
    pass

@action(name="Both", description="Has both")
@on_time("sunset")
def both():
    pass
"""
        )

        context = make_context(str(automation_path))
        metadata = await load_and_run(context)

        # Should have 3 actions (all callable) and 2 triggers
        assert len(metadata.actions) == 3
        assert len(metadata.triggers) == 2

        action_names = {a.name for a in metadata.actions}
        assert "Manual Only" in action_names
        assert "auto_only" in action_names  # Default name
        assert "Both" in action_names
