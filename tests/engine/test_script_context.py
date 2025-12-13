"""Tests for the engine/script_context.py module."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.haanim.engine.script_context import (
    ActionDefinition,
    ScriptContext,
    ScriptMetadata,
    TriggerDefinition,
)


class TestActionDefinition:
    """Tests for ActionDefinition dataclass."""

    @pytest.mark.parametrize(
        ("name", "func_name", "script_name", "queue", "preempt"),
        [
            ("my_action", "do_action", "test_script", False, False),
            ("queued_action", "queue_func", "script2", True, False),
            ("preempt_action", "preempt_func", "script3", False, True),
        ],
    )
    def test_creation(
        self, name: str, func_name: str, script_name: str, queue: bool, preempt: bool
    ) -> None:
        """Test creating an ActionDefinition."""
        func = MagicMock()
        action = ActionDefinition(
            name=name,
            func_name=func_name,
            func=func,
            description="Test description",
            script_name=script_name,
            queue=queue,
            queue_timeout=30.0,
            preempt=preempt,
        )
        assert action.name == name
        assert action.func_name == func_name
        assert action.func is func
        assert action.description == "Test description"
        assert action.script_name == script_name
        assert action.queue is queue
        assert action.queue_timeout == 30.0
        assert action.preempt is preempt

    def test_default_values(self) -> None:
        """Test default values."""
        func = MagicMock()
        action = ActionDefinition(
            name="action",
            func_name="action_func",
            func=func,
            script_name="script",
        )
        assert action.description is None
        assert action.queue is False
        assert action.queue_timeout == 10.0
        assert action.preempt is False


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
            script_name="test_script",
        )
        assert trigger.trigger_type == trigger_type
        assert trigger.trigger_expr == trigger_expr
        assert trigger.func_name == "trigger_func"
        assert trigger.func is func
        assert trigger.kwargs == {"extra": "value"}
        assert trigger.script_name == "test_script"


class TestScriptMetadata:
    """Tests for ScriptMetadata dataclass."""

    def test_creation(self) -> None:
        """Test creating ScriptMetadata."""
        now = datetime.now()
        actions = [
            ActionDefinition(
                name="action1",
                func_name="func1",
                func=MagicMock(),
                script_name="test",
            )
        ]
        triggers = [
            TriggerDefinition(
                trigger_type="state",
                trigger_expr="sensor.test == 'on'",
                func_name="trigger_func",
                func=MagicMock(),
                kwargs={},
                script_name="test",
            )
        ]
        services: list[str] = ["my_service"]

        metadata = ScriptMetadata(
            name="Test Script",
            path="/path/to/script.py",
            filename="script.py",
            loaded_at=now,
            modified_at=now,
            actions=actions,
            triggers=triggers,
            services=services,
            has_startup=True,
            has_shutdown=False,
        )

        assert metadata.name == "Test Script"
        assert metadata.path == "/path/to/script.py"
        assert metadata.filename == "script.py"
        assert metadata.loaded_at == now
        assert metadata.modified_at == now
        assert metadata.actions == actions
        assert metadata.triggers == triggers
        assert metadata.services == services
        assert metadata.has_startup is True
        assert metadata.has_shutdown is False
        assert metadata.enabled is True  # Default

    def test_default_enabled(self) -> None:
        """Test default enabled value."""
        metadata = ScriptMetadata(
            name="Test",
            path="/path/script.py",
            filename="script.py",
            loaded_at=datetime.now(),
            modified_at=datetime.now(),
            actions=[],
            triggers=[],
            services=[],
            has_startup=False,
            has_shutdown=False,
        )
        assert metadata.enabled is True


class TestScriptContext:
    """Tests for ScriptContext class."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock()
        return hass

    def test_init(self, mock_hass: MagicMock) -> None:
        """Test ScriptContext initialization."""
        context = ScriptContext(
            hass=mock_hass,
            script_path="/scripts/test.py",
        )
        assert context.hass is mock_hass
        assert context.script_path == "/scripts/test.py"
        assert context.script_name == "test"
        assert context.filename == "test.py"

    @pytest.mark.parametrize(
        ("path", "expected_name", "expected_filename"),
        [
            ("/scripts/my_script.py", "my_script", "my_script.py"),
            ("/home/user/automation.py", "automation", "automation.py"),
            ("./test.py", "test", "test.py"),
        ],
    )
    def test_script_name_from_path(
        self,
        mock_hass: MagicMock,
        path: str,
        expected_name: str,
        expected_filename: str,
    ) -> None:
        """Test script name is derived from path."""
        context = ScriptContext(
            hass=mock_hass,
            script_path=path,
        )
        assert context.script_name == expected_name
        assert context.filename == expected_filename

    def test_is_loaded_initially_false(self, mock_hass: MagicMock) -> None:
        """Test is_loaded is False before loading."""
        context = ScriptContext(
            hass=mock_hass,
            script_path="/scripts/test.py",
        )
        assert context.is_loaded is False

    def test_get_metadata_before_load(self, mock_hass: MagicMock) -> None:
        """Test get_metadata returns None before loading."""
        context = ScriptContext(
            hass=mock_hass,
            script_path="/scripts/test.py",
        )
        assert context.get_metadata() is None

    def test_get_actions_before_load(self, mock_hass: MagicMock) -> None:
        """Test get_actions returns empty list before loading."""
        context = ScriptContext(
            hass=mock_hass,
            script_path="/scripts/test.py",
        )
        assert context.get_actions() == []

    def test_get_triggers_before_load(self, mock_hass: MagicMock) -> None:
        """Test get_triggers returns empty list before loading."""
        context = ScriptContext(
            hass=mock_hass,
            script_path="/scripts/test.py",
        )
        assert context.get_triggers() == []

    def test_get_startup_func_before_load(self, mock_hass: MagicMock) -> None:
        """Test get_startup_func returns None before loading."""
        context = ScriptContext(
            hass=mock_hass,
            script_path="/scripts/test.py",
        )
        assert context.get_startup_func() is None

    def test_get_shutdown_func_before_load(self, mock_hass: MagicMock) -> None:
        """Test get_shutdown_func returns None before loading."""
        context = ScriptContext(
            hass=mock_hass,
            script_path="/scripts/test.py",
        )
        assert context.get_shutdown_func() is None


class TestScriptContextLoad:
    """Tests for ScriptContext.load method."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(
            side_effect=lambda func, *args: func(*args)
        )
        return hass

    async def test_load_nonexistent_file(self, mock_hass: MagicMock) -> None:
        """Test loading non-existent file raises error."""
        from custom_components.haanim.engine.errors import ScriptError

        context = ScriptContext(
            hass=mock_hass,
            script_path="/nonexistent/path/script.py",
        )

        with pytest.raises(ScriptError, match="Script file not found"):
            await context.load()

    async def test_load_simple_script(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading a simple valid script."""
        script_path = tmp_path / "test_script.py"
        script_path.write_text("""
@action
def my_action():
    pass
""")

        context = ScriptContext(
            hass=mock_hass,
            script_path=str(script_path),
        )

        metadata = await context.load()

        assert metadata is not None
        assert metadata.name == "test_script"
        assert len(metadata.actions) == 1
        assert metadata.actions[0].name == "my_action"

    async def test_load_script_with_triggers(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading a script with triggers."""
        script_path = tmp_path / "trigger_script.py"
        script_path.write_text("""
@state_trigger("sensor.test > 50")
def on_temp_high():
    pass

@time_trigger("cron(0 * * * *)")
def on_hour():
    pass
""")

        context = ScriptContext(
            hass=mock_hass,
            script_path=str(script_path),
        )

        metadata = await context.load()

        assert len(metadata.triggers) == 2
        trigger_types = {t.trigger_type for t in metadata.triggers}
        assert "state_trigger" in trigger_types
        assert "time_trigger" in trigger_types

    async def test_load_script_with_startup_shutdown(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading a script with startup and shutdown."""
        script_path = tmp_path / "lifecycle_script.py"
        script_path.write_text("""
@startup
def on_startup():
    pass

@shutdown
def on_shutdown():
    pass
""")

        context = ScriptContext(
            hass=mock_hass,
            script_path=str(script_path),
        )

        metadata = await context.load()

        assert metadata.has_startup is True
        assert metadata.has_shutdown is True
        assert context.get_startup_func() is not None
        assert context.get_shutdown_func() is not None

    async def test_load_script_with_syntax_error(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading a script with syntax error raises error."""
        from custom_components.haanim.engine.errors import ScriptError

        script_path = tmp_path / "bad_script.py"
        script_path.write_text("""
def broken(:
    pass
""")

        context = ScriptContext(
            hass=mock_hass,
            script_path=str(script_path),
        )

        with pytest.raises(ScriptError, match="Syntax error"):
            await context.load()


class TestScriptContextGetters:
    """Tests for ScriptContext getter methods."""

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
        script_path = tmp_path / "action_script.py"
        script_path.write_text("""
@action("First Action")
def first():
    pass

@action("Second Action")
def second():
    pass
""")

        context = ScriptContext(hass=mock_hass, script_path=str(script_path))
        await context.load()

        actions = context.get_actions()
        assert len(actions) == 2

    async def test_get_triggers(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test get_triggers returns trigger definitions."""
        script_path = tmp_path / "trigger_script.py"
        script_path.write_text("""
@state_trigger("sensor.test > 50")
def on_high():
    pass
""")

        context = ScriptContext(hass=mock_hass, script_path=str(script_path))
        await context.load()

        triggers = context.get_triggers()
        assert len(triggers) == 1

    async def test_get_metadata(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test get_metadata returns script metadata."""
        script_path = tmp_path / "meta_script.py"
        script_path.write_text("""
@action("Test")
def test():
    pass
""")

        context = ScriptContext(hass=mock_hass, script_path=str(script_path))
        await context.load()

        metadata = context.get_metadata()
        assert metadata is not None
        assert metadata.filename == "meta_script.py"

    def test_get_metadata_not_loaded(self, mock_hass: MagicMock) -> None:
        """Test get_metadata returns None when not loaded."""
        context = ScriptContext(hass=mock_hass, script_path="/fake/path.py")
        assert context.get_metadata() is None

    async def test_script_name_property(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test script_name property returns name without .py."""
        script_path = tmp_path / "my_cool_script.py"
        script_path.write_text("x = 1")

        context = ScriptContext(hass=mock_hass, script_path=str(script_path))
        assert context.script_name == "my_cool_script"

    async def test_filename_property(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test filename property returns filename with .py."""
        script_path = tmp_path / "my_script.py"
        script_path.write_text("x = 1")

        context = ScriptContext(hass=mock_hass, script_path=str(script_path))
        assert context.filename == "my_script.py"

    async def test_name_property(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test name property returns display name."""
        script_path = tmp_path / "test.py"
        script_path.write_text("x = 1")

        context = ScriptContext(hass=mock_hass, script_path=str(script_path))
        await context.load()
        assert context.name == "test"


class TestScriptContextEdgeCases:
    """Tests for ScriptContext edge cases."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(
            side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)
        )
        return hass

    async def test_load_minimal_script(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading a minimal script with just a variable."""
        script_path = tmp_path / "minimal.py"
        script_path.write_text("x = 1")

        context = ScriptContext(hass=mock_hass, script_path=str(script_path))
        metadata = await context.load()

        assert metadata.name == "minimal"
        assert len(metadata.actions) == 0
        assert len(metadata.triggers) == 0

    async def test_load_script_with_action_name(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test loading a script with @action decorator sets display name."""
        script_path = tmp_path / "my_script.py"
        script_path.write_text('''
@action("My Custom Action")
def do_something():
    pass
''')

        context = ScriptContext(hass=mock_hass, script_path=str(script_path))
        metadata = await context.load()

        # Should have an action with custom name
        assert len(metadata.actions) == 1
        assert metadata.actions[0].name == "My Custom Action"

    async def test_load_script_file_not_found(self, mock_hass: MagicMock) -> None:
        """Test loading a non-existent script raises ScriptError."""
        from custom_components.haanim.engine.errors import ScriptError

        context = ScriptContext(hass=mock_hass, script_path="/nonexistent/path.py")

        with pytest.raises(ScriptError, match="not found"):
            await context.load()

    async def test_get_startup_func_none(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test get_startup_func returns None when no startup defined."""
        script_path = tmp_path / "no_startup.py"
        script_path.write_text("x = 1")

        context = ScriptContext(hass=mock_hass, script_path=str(script_path))
        await context.load()

        assert context.get_startup_func() is None

    async def test_get_shutdown_func_none(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test get_shutdown_func returns None when no shutdown defined."""
        script_path = tmp_path / "no_shutdown.py"
        script_path.write_text("x = 1")

        context = ScriptContext(hass=mock_hass, script_path=str(script_path))
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
        script_path = tmp_path / "trigger_script.py"
        script_path.write_text(
            """
@state_trigger("sensor.test > 50")
def on_high():
    pass
"""
        )

        context = ScriptContext(hass=mock_hass, script_path=str(script_path))
        metadata = await context.load()

        # Should have both a trigger and an action
        assert len(metadata.triggers) == 1
        assert len(metadata.actions) == 1
        assert metadata.actions[0].func_name == "on_high"

    async def test_multiple_triggers_single_action(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test that multiple triggers on one function still creates one action."""
        script_path = tmp_path / "multi_trigger.py"
        script_path.write_text(
            """
@state_trigger("sensor.a > 10")
@state_trigger("sensor.b < 5")
@time_trigger("cron(0 8 * * *)")
def multi_trigger():
    pass
"""
        )

        context = ScriptContext(hass=mock_hass, script_path=str(script_path))
        metadata = await context.load()

        # Should have 3 triggers but only 1 action
        assert len(metadata.triggers) == 3
        assert len(metadata.actions) == 1
        assert metadata.actions[0].func_name == "multi_trigger"

    async def test_triggered_action_with_metadata(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test that triggered function with @action decorator gets metadata."""
        script_path = tmp_path / "trigger_with_action.py"
        script_path.write_text(
            """
@action("Custom Name", description="Custom description", queue=True)
@state_trigger("sensor.test > 50")
def custom_action():
    pass
"""
        )

        context = ScriptContext(hass=mock_hass, script_path=str(script_path))
        metadata = await context.load()

        # Should have trigger and action with custom metadata
        assert len(metadata.triggers) == 1
        assert len(metadata.actions) == 1
        action = metadata.actions[0]
        assert action.name == "Custom Name"
        assert action.description == "Custom description"
        assert action.queue is True

    async def test_triggered_action_default_settings(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test that triggered function without @action gets default settings."""
        script_path = tmp_path / "trigger_only.py"
        script_path.write_text(
            """
@time_trigger("sunset")
def evening_lights():
    pass
"""
        )

        context = ScriptContext(hass=mock_hass, script_path=str(script_path))
        metadata = await context.load()

        # Should have action with default settings
        assert len(metadata.actions) == 1
        action = metadata.actions[0]
        assert action.name == "evening_lights"  # Uses function name
        assert action.description is None
        assert action.queue is False
        assert action.queue_timeout == 10.0
        assert action.preempt is False

    async def test_action_without_trigger(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test that @action without triggers still works."""
        script_path = tmp_path / "action_only.py"
        script_path.write_text(
            """
@action("Manual Action")
def manual_only():
    pass
"""
        )

        context = ScriptContext(hass=mock_hass, script_path=str(script_path))
        metadata = await context.load()

        # Should have action but no triggers
        assert len(metadata.actions) == 1
        assert len(metadata.triggers) == 0
        assert metadata.actions[0].name == "Manual Action"

    async def test_mixed_actions_and_triggers(self, mock_hass: MagicMock, tmp_path: Any) -> None:
        """Test script with mix of actions, triggers, and combined."""
        script_path = tmp_path / "mixed.py"
        script_path.write_text(
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

        context = ScriptContext(hass=mock_hass, script_path=str(script_path))
        metadata = await context.load()

        # Should have 3 actions (all callable) and 2 triggers
        assert len(metadata.actions) == 3
        assert len(metadata.triggers) == 2

        action_names = {a.name for a in metadata.actions}
        assert "Manual Only" in action_names
        assert "auto_only" in action_names  # Default name
        assert "Both" in action_names
