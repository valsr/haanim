"""Tests for the engine/automation_context.py module."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.haanim.engine.errors import PUBLIC_ERRORS, HAAnimError
from custom_components.haanim.engine.automation_context import (
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
        now = datetime.now()
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
            loaded_at=datetime.now(),
            modified_at=datetime.now(),
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
        context = AutomationContext(
            hass=mock_hass,
            automation_path="/automations/test.py",
        )
        assert context.hass is mock_hass
        assert context.automation_path == "/automations/test.py"
        assert context.automation_id == "test"
        assert context.filename == "test.py"

    @pytest.mark.parametrize(
        ("path", "expected_name", "expected_filename"),
        [
            ("/automations/my_automation.py", "my_automation", "my_automation.py"),
            ("/home/user/automation.py", "automation", "automation.py"),
            ("./test.py", "test", "test.py"),
        ],
    )
    def test_automation_id_from_path(
        self,
        mock_hass: MagicMock,
        path: str,
        expected_name: str,
        expected_filename: str,
    ) -> None:
        """Test automation name is derived from path."""
        context = AutomationContext(
            hass=mock_hass,
            automation_path=path,
        )
        assert context.automation_id == expected_name
        assert context.filename == expected_filename

    def test_is_loaded_initially_false(self, mock_hass: MagicMock) -> None:
        """Test is_loaded is False before loading."""
        context = AutomationContext(
            hass=mock_hass,
            automation_path="/automations/test.py",
        )
        assert context.is_loaded is False

    def test_get_metadata_before_load(self, mock_hass: MagicMock) -> None:
        """Test get_metadata returns None before loading."""
        context = AutomationContext(
            hass=mock_hass,
            automation_path="/automations/test.py",
        )
        assert context.get_metadata() is None

    def test_get_actions_before_load(self, mock_hass: MagicMock) -> None:
        """Test get_actions returns empty list before loading."""
        context = AutomationContext(
            hass=mock_hass,
            automation_path="/automations/test.py",
        )
        assert context.get_actions() == []

    def test_get_triggers_before_load(self, mock_hass: MagicMock) -> None:
        """Test get_triggers returns empty list before loading."""
        context = AutomationContext(
            hass=mock_hass,
            automation_path="/automations/test.py",
        )
        assert context.get_triggers() == []

    def test_get_startup_func_before_load(self, mock_hass: MagicMock) -> None:
        """Test get_startup_func returns None before loading."""
        context = AutomationContext(
            hass=mock_hass,
            automation_path="/automations/test.py",
        )
        assert context.get_startup_func() is None

    def test_get_shutdown_func_before_load(self, mock_hass: MagicMock) -> None:
        """Test get_shutdown_func returns None before loading."""
        context = AutomationContext(
            hass=mock_hass,
            automation_path="/automations/test.py",
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
        from custom_components.haanim.engine.errors import HAAnimError

        context = AutomationContext(
            hass=mock_hass,
            automation_path="/nonexistent/path/automation.py",
        )

        with pytest.raises(HAAnimError, match="Automation file not found"):
            await context.load()

    async def test_load_simple_automation(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading a simple valid automation."""
        automation_path = tmp_path / "test_automation.py"
        automation_path.write_text(
            """
@action
def my_action():
    pass
"""
        )

        context = AutomationContext(
            hass=mock_hass,
            automation_path=str(automation_path),
        )

        metadata = await context.load()

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
        automation_path = tmp_path / "imports_error.py"
        automation_path.write_text(f"from haanim import {name}\nimported = {name}\n")

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        await context.load()

        assert context.get_symbol("imported") is error_class

    async def test_internal_errors_not_importable_from_haanim(
        self, mock_hass: MagicMock, tmp_path: Any
    ) -> None:
        """Test errors outside the public list are not exported to automations."""
        automation_path = tmp_path / "imports_internal.py"
        automation_path.write_text("from haanim import ShutdownTimeoutError\n")

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        with pytest.raises(HAAnimError):
            await context.load()

    async def test_load_automation_with_triggers(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading an automation with triggers."""
        automation_path = tmp_path / "trigger_automation.py"
        automation_path.write_text(
            """
@state_trigger("sensor.test > 50")
def on_temp_high():
    pass

@time_trigger("cron(0 * * * *)")
def on_hour():
    pass
"""
        )

        context = AutomationContext(
            hass=mock_hass,
            automation_path=str(automation_path),
        )

        metadata = await context.load()

        assert len(metadata.triggers) == 2
        trigger_types = {t.trigger_type for t in metadata.triggers}
        assert "state_trigger" in trigger_types
        assert "time_trigger" in trigger_types

    async def test_load_automation_with_startup_shutdown(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading an automation with startup and shutdown."""
        automation_path = tmp_path / "lifecycle_automation.py"
        automation_path.write_text(
            """
@startup
def on_startup():
    pass

@shutdown
def on_shutdown():
    pass
"""
        )

        context = AutomationContext(
            hass=mock_hass,
            automation_path=str(automation_path),
        )

        metadata = await context.load()

        assert metadata.has_startup is True
        assert metadata.has_shutdown is True
        assert context.get_startup_func() is not None
        assert context.get_shutdown_func() is not None

    async def test_load_automation_with_syntax_error(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading an automation with syntax error raises error."""
        from custom_components.haanim.engine.errors import HAAnimError

        automation_path = tmp_path / "bad_automation.py"
        automation_path.write_text(
            """
def broken(:
    pass
"""
        )

        context = AutomationContext(
            hass=mock_hass,
            automation_path=str(automation_path),
        )

        with pytest.raises(HAAnimError, match="Syntax error"):
            await context.load()


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
        automation_path = tmp_path / "action_automation.py"
        automation_path.write_text(
            """
@action("First Action")
def first():
    pass

@action("Second Action")
def second():
    pass
"""
        )

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        await context.load()

        actions = context.get_actions()
        assert len(actions) == 2

    async def test_get_triggers(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test get_triggers returns trigger definitions."""
        automation_path = tmp_path / "trigger_automation.py"
        automation_path.write_text(
            """
@state_trigger("sensor.test > 50")
def on_high():
    pass
"""
        )

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        await context.load()

        triggers = context.get_triggers()
        assert len(triggers) == 1

    async def test_get_metadata(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test get_metadata returns automation metadata."""
        automation_path = tmp_path / "meta_automation.py"
        automation_path.write_text(
            """
@action("Test")
def test():
    pass
"""
        )

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        await context.load()

        metadata = context.get_metadata()
        assert metadata is not None
        assert metadata.filename == "meta_automation.py"

    def test_get_metadata_not_loaded(self, mock_hass: MagicMock) -> None:
        """Test get_metadata returns None when not loaded."""
        context = AutomationContext(hass=mock_hass, automation_path="/fake/path.py")
        assert context.get_metadata() is None

    async def test_automation_id_property(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test automation_id property returns name without .py."""
        automation_path = tmp_path / "my_cool_automation.py"
        automation_path.write_text("x = 1")

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        assert context.automation_id == "my_cool_automation"

    async def test_filename_property(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test filename property returns filename with .py."""
        automation_path = tmp_path / "my_automation.py"
        automation_path.write_text("x = 1")

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        assert context.filename == "my_automation.py"


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
        automation_path = tmp_path / "minimal.py"
        automation_path.write_text("x = 1")

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        metadata = await context.load()

        assert metadata.id == "minimal"
        assert len(metadata.actions) == 0
        assert len(metadata.triggers) == 0

    async def test_load_automation_with_action_name(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading an automation with @action decorator sets display name."""
        automation_path = tmp_path / "my_automation.py"
        automation_path.write_text(
            """
@action("My Custom Action")
def do_something():
    pass
"""
        )

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        metadata = await context.load()

        # Should have an action with custom name
        assert len(metadata.actions) == 1
        assert metadata.actions[0].name == "My Custom Action"

    async def test_load_automation_file_not_found(self, mock_hass: MagicMock) -> None:
        """Test loading a non-existent automation raises HAAnimError."""
        from custom_components.haanim.engine.errors import HAAnimError

        context = AutomationContext(hass=mock_hass, automation_path="/nonexistent/path.py")

        with pytest.raises(HAAnimError, match="not found"):
            await context.load()

    async def test_get_startup_func_none(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test get_startup_func returns None when no startup defined."""
        automation_path = tmp_path / "no_startup.py"
        automation_path.write_text("x = 1")

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        await context.load()

        assert context.get_startup_func() is None

    async def test_get_shutdown_func_none(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test get_shutdown_func returns None when no shutdown defined."""
        automation_path = tmp_path / "no_shutdown.py"
        automation_path.write_text("x = 1")

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        await context.load()

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
        automation_path = tmp_path / "trigger_automation.py"
        automation_path.write_text(
            """
@state_trigger("sensor.test > 50")
def on_high():
    pass
"""
        )

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        metadata = await context.load()

        # Should have both a trigger and an action
        assert len(metadata.triggers) == 1
        assert len(metadata.actions) == 1
        assert metadata.actions[0].func_name == "on_high"

    async def test_multiple_triggers_single_action(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test that multiple triggers on one function still creates one action."""
        automation_path = tmp_path / "multi_trigger.py"
        automation_path.write_text(
            """
@state_trigger("sensor.a > 10")
@state_trigger("sensor.b < 5")
@time_trigger("cron(0 8 * * *)")
def multi_trigger():
    pass
"""
        )

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        metadata = await context.load()

        # Should have 3 triggers but only 1 action
        assert len(metadata.triggers) == 3
        assert len(metadata.actions) == 1
        assert metadata.actions[0].func_name == "multi_trigger"

    async def test_triggered_action_with_metadata(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test that triggered function with @action decorator gets metadata."""
        automation_path = tmp_path / "trigger_with_action.py"
        automation_path.write_text(
            """
@action("Custom Name", description="Custom description")
@state_trigger("sensor.test > 50")
def custom_action():
    pass
"""
        )

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        metadata = await context.load()

        # Should have trigger and action with custom metadata
        assert len(metadata.triggers) == 1
        assert len(metadata.actions) == 1
        action = metadata.actions[0]
        assert action.name == "Custom Name"
        assert action.description == "Custom description"

    async def test_triggered_action_default_settings(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test that triggered function without @action gets default settings."""
        automation_path = tmp_path / "trigger_only.py"
        automation_path.write_text(
            """
@time_trigger("sunset")
def evening_lights():
    pass
"""
        )

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        metadata = await context.load()

        # Should have action with default settings
        assert len(metadata.actions) == 1
        action = metadata.actions[0]
        assert action.name == "evening_lights"  # Uses function name
        assert action.description is None

    async def test_action_without_trigger(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test that @action without triggers still works."""
        automation_path = tmp_path / "action_only.py"
        automation_path.write_text(
            """
@action("Manual Action")
def manual_only():
    pass
"""
        )

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        metadata = await context.load()

        # Should have action but no triggers
        assert len(metadata.actions) == 1
        assert len(metadata.triggers) == 0
        assert metadata.actions[0].name == "Manual Action"

    async def test_mixed_actions_and_triggers(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test automation with mix of actions, triggers, and combined."""
        automation_path = tmp_path / "mixed.py"
        automation_path.write_text(
            """
@action("Manual Only")
def manual():
    pass

@state_trigger("sensor.a > 10")
def auto_only():
    pass

@action("Both", description="Has both")
@time_trigger("sunset")
def both():
    pass
"""
        )

        context = AutomationContext(hass=mock_hass, automation_path=str(automation_path))
        metadata = await context.load()

        # Should have 3 actions (all callable) and 2 triggers
        assert len(metadata.actions) == 3
        assert len(metadata.triggers) == 2

        action_names = {a.name for a in metadata.actions}
        assert "Manual Only" in action_names
        assert "auto_only" in action_names  # Default name
        assert "Both" in action_names
