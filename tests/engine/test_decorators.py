"""Tests for the HAAnim decorators module."""

from __future__ import annotations

import pytest

from custom_components.haanim.engine.decorators import (
    ActionInfo,
    FunctionMetadata,
    TriggerInfo,
    action,
    event_trigger,
    get_metadata,
    has_metadata,
    service,
    shutdown,
    startup,
    state_active,
    state_trigger,
    time_active,
    time_trigger,
)


class TestTriggerInfo:
    """Tests for TriggerInfo dataclass."""

    def test_default_kwargs(self) -> None:
        """Test TriggerInfo default kwargs is empty dict."""
        info = TriggerInfo(trigger_type="state_trigger", trigger_expr="sensor.temp > 25")
        assert info.kwargs == {}

    def test_with_kwargs(self) -> None:
        """Test TriggerInfo with custom kwargs."""
        info = TriggerInfo(
            trigger_type="time_trigger",
            trigger_expr="cron(0 8 * * *)",
            kwargs={"some_key": "value"},
        )
        assert info.kwargs == {"some_key": "value"}


class TestActionInfo:
    """Tests for ActionInfo dataclass."""

    def test_defaults(self) -> None:
        """Test ActionInfo default values."""
        info = ActionInfo()
        assert info.name is None
        assert info.description is None
        assert info.func is None
        assert info.queue is False
        assert info.queue_timeout == 10.0
        assert info.preempt is False

    def test_with_values(self) -> None:
        """Test ActionInfo with custom values."""
        info = ActionInfo(
            name="My Action",
            description="Does something",
            queue=True,
            queue_timeout=30.0,
            preempt=True,
        )
        assert info.name == "My Action"
        assert info.description == "Does something"
        assert info.queue is True
        assert info.queue_timeout == 30.0
        assert info.preempt is True


class TestFunctionMetadata:
    """Tests for FunctionMetadata dataclass."""

    def test_defaults(self) -> None:
        """Test FunctionMetadata default values."""
        meta = FunctionMetadata()
        assert meta.custom_name is None
        assert meta.is_action is False
        assert meta.action_info is None
        assert meta.triggers == []
        assert meta.constraints == []
        assert meta.is_service is False
        assert meta.service_schema is None
        assert meta.is_startup is False
        assert meta.is_shutdown is False


class TestActionDecorator:
    """Tests for the @action decorator."""

    def test_action_without_args(self) -> None:
        """Test @action without arguments."""

        @action
        def my_action() -> None:
            pass

        assert has_metadata(my_action)
        meta = get_metadata(my_action)
        assert meta is not None
        assert meta.is_action is True
        assert meta.action_info is not None
        assert meta.action_info.name is None

    def test_action_with_name(self) -> None:
        """Test @action with a name."""

        @action("My Custom Action")
        def my_action() -> None:
            pass

        meta = get_metadata(my_action)
        assert meta is not None
        assert meta.action_info is not None
        assert meta.action_info.name == "My Custom Action"
        assert meta.custom_name == "My Custom Action"

    def test_action_with_description(self) -> None:
        """Test @action with description."""

        @action("Test", description="This is a test action")
        def my_action() -> None:
            pass

        meta = get_metadata(my_action)
        assert meta is not None
        assert meta.action_info is not None
        assert meta.action_info.description == "This is a test action"

    def test_action_with_queue(self) -> None:
        """Test @action with queue options."""

        @action(queue=True, queue_timeout=30.0)
        def queued_action() -> None:
            pass

        meta = get_metadata(queued_action)
        assert meta is not None
        assert meta.action_info is not None
        assert meta.action_info.queue is True
        assert meta.action_info.queue_timeout == 30.0

    def test_action_with_preempt(self) -> None:
        """Test @action with preempt option."""

        @action(preempt=True)
        def preemptive_action() -> None:
            pass

        meta = get_metadata(preemptive_action)
        assert meta is not None
        assert meta.action_info is not None
        assert meta.action_info.preempt is True

    def test_action_with_all_options(self) -> None:
        """Test @action with all options combined."""

        @action("Full Action", description="Full test", queue=True, queue_timeout=60, preempt=True)
        def full_action() -> None:
            pass

        meta = get_metadata(full_action)
        assert meta is not None
        assert meta.action_info is not None
        assert meta.action_info.name == "Full Action"
        assert meta.action_info.description == "Full test"
        assert meta.action_info.queue is True
        assert meta.action_info.queue_timeout == 60
        assert meta.action_info.preempt is True


class TestStateTriggerDecorator:
    """Tests for the @state_trigger decorator."""

    def test_single_expression(self) -> None:
        """Test @state_trigger with single expression."""

        @state_trigger("sensor.temperature > 25")
        def handle_temp() -> None:
            pass

        meta = get_metadata(handle_temp)
        assert meta is not None
        assert len(meta.triggers) == 1
        assert meta.triggers[0].trigger_type == "state_trigger"
        assert meta.triggers[0].trigger_expr == "sensor.temperature > 25"

    def test_multiple_expressions(self) -> None:
        """Test @state_trigger with multiple expressions."""

        @state_trigger("sensor.a > 10", "sensor.b < 5")
        def handle_multi() -> None:
            pass

        meta = get_metadata(handle_multi)
        assert meta is not None
        assert len(meta.triggers) == 1
        assert meta.triggers[0].trigger_expr == ["sensor.a > 10", "sensor.b < 5"]

    def test_with_state_hold(self) -> None:
        """Test @state_trigger with state_hold option."""

        @state_trigger("sensor.temp > 30", state_hold=60)
        def handle_hold() -> None:
            pass

        meta = get_metadata(handle_hold)
        assert meta is not None
        assert meta.triggers[0].kwargs["state_hold"] == 60

    def test_with_state_check_now(self) -> None:
        """Test @state_trigger with state_check_now option."""

        @state_trigger("binary_sensor.test == 'on'", state_check_now=True)
        def handle_check() -> None:
            pass

        meta = get_metadata(handle_check)
        assert meta is not None
        assert meta.triggers[0].kwargs["state_check_now"] is True

    def test_with_watch(self) -> None:
        """Test @state_trigger with watch option."""

        @state_trigger("sensor.temp", watch=["sensor.temp", "sensor.humidity"])
        def handle_watch() -> None:
            pass

        meta = get_metadata(handle_watch)
        assert meta is not None
        assert meta.triggers[0].kwargs["watch"] == ["sensor.temp", "sensor.humidity"]


class TestTimeTriggerDecorator:
    """Tests for the @time_trigger decorator."""

    def test_cron_expression(self) -> None:
        """Test @time_trigger with cron expression."""

        @time_trigger("cron(0 8 * * *)")
        def morning_routine() -> None:
            pass

        meta = get_metadata(morning_routine)
        assert meta is not None
        assert len(meta.triggers) == 1
        assert meta.triggers[0].trigger_type == "time_trigger"
        assert meta.triggers[0].trigger_expr == "cron(0 8 * * *)"

    def test_multiple_times(self) -> None:
        """Test @time_trigger with multiple time specs."""

        @time_trigger("sunrise", "sunset")
        def sun_times() -> None:
            pass

        meta = get_metadata(sun_times)
        assert meta is not None
        assert meta.triggers[0].trigger_expr == ["sunrise", "sunset"]


class TestEventTriggerDecorator:
    """Tests for the @event_trigger decorator."""

    def test_simple_event(self) -> None:
        """Test @event_trigger with simple event type."""

        @event_trigger("custom_event")
        def handle_event() -> None:
            pass

        meta = get_metadata(handle_event)
        assert meta is not None
        assert len(meta.triggers) == 1
        assert meta.triggers[0].trigger_type == "event_trigger"
        assert meta.triggers[0].trigger_expr == "custom_event"

    def test_with_event_data(self) -> None:
        """Test @event_trigger with event_data filter."""

        @event_trigger("button_press", event_data={"action": "single"})
        def handle_button() -> None:
            pass

        meta = get_metadata(handle_button)
        assert meta is not None
        assert meta.triggers[0].kwargs["event_data"] == {"action": "single"}


class TestTimeActiveDecorator:
    """Tests for the @time_active decorator."""

    def test_time_range(self) -> None:
        """Test @time_active with time range."""

        @time_active("range(08:00, 17:00)")
        def daytime_only() -> None:
            pass

        meta = get_metadata(daytime_only)
        assert meta is not None
        assert len(meta.constraints) == 1
        assert meta.constraints[0]["type"] == "time_active"
        assert "range(08:00, 17:00)" in meta.constraints[0]["specs"]


class TestStateActiveDecorator:
    """Tests for the @state_active decorator."""

    def test_state_condition(self) -> None:
        """Test @state_active with state condition."""

        @state_active("input_boolean.enabled == 'on'")
        def when_enabled() -> None:
            pass

        meta = get_metadata(when_enabled)
        assert meta is not None
        assert len(meta.constraints) == 1
        assert meta.constraints[0]["type"] == "state_active"
        assert "input_boolean.enabled == 'on'" in meta.constraints[0]["exprs"]


class TestServiceDecorator:
    """Tests for the @service decorator."""

    def test_service_without_args(self) -> None:
        """Test @service without arguments."""

        @service
        def my_service() -> None:
            pass

        meta = get_metadata(my_service)
        assert meta is not None
        assert meta.is_service is True

    def test_service_with_name(self) -> None:
        """Test @service with custom name."""

        @service("custom_service", description="A custom service")
        def my_service() -> None:
            pass

        meta = get_metadata(my_service)
        assert meta is not None
        assert meta.is_service is True
        assert meta.service_schema is not None
        assert meta.service_schema["name"] == "custom_service"
        assert meta.service_schema["description"] == "A custom service"


class TestStartupDecorator:
    """Tests for the @startup decorator."""

    def test_startup(self) -> None:
        """Test @startup decorator."""

        @startup
        def on_startup() -> None:
            pass

        meta = get_metadata(on_startup)
        assert meta is not None
        assert meta.is_startup is True


class TestShutdownDecorator:
    """Tests for the @shutdown decorator."""

    def test_shutdown(self) -> None:
        """Test @shutdown decorator."""

        @shutdown
        def on_shutdown() -> None:
            pass

        meta = get_metadata(on_shutdown)
        assert meta is not None
        assert meta.is_shutdown is True


class TestCombinedDecorators:
    """Tests for combining multiple decorators."""

    def test_action_with_trigger(self) -> None:
        """Test combining @action with @state_trigger."""

        @action("Combined Action")
        @state_trigger("sensor.test > 10")
        def combined() -> None:
            pass

        meta = get_metadata(combined)
        assert meta is not None
        assert meta.is_action is True
        assert len(meta.triggers) == 1

    def test_multiple_triggers(self) -> None:
        """Test combining multiple trigger decorators."""

        @state_trigger("sensor.a > 10")
        @time_trigger("cron(0 8 * * *)")
        def multi_trigger() -> None:
            pass

        meta = get_metadata(multi_trigger)
        assert meta is not None
        assert len(meta.triggers) == 2

    def test_trigger_with_constraint(self) -> None:
        """Test combining trigger with constraint."""

        @time_active("range(sunset, sunrise)")
        @state_trigger("binary_sensor.motion == 'on'")
        def night_motion() -> None:
            pass

        meta = get_metadata(night_motion)
        assert meta is not None
        assert len(meta.triggers) == 1
        assert len(meta.constraints) == 1


class TestMetadataHelpers:
    """Tests for metadata helper functions."""

    def test_has_metadata_true(self) -> None:
        """Test has_metadata returns True for decorated function."""

        @action
        def decorated() -> None:
            pass

        assert has_metadata(decorated) is True

    def test_has_metadata_false(self) -> None:
        """Test has_metadata returns False for undecorated function."""

        def not_decorated() -> None:
            pass

        assert has_metadata(not_decorated) is False

    def test_get_metadata_none(self) -> None:
        """Test get_metadata returns None for undecorated function."""

        def not_decorated() -> None:
            pass

        assert get_metadata(not_decorated) is None
