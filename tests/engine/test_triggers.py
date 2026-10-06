"""Tests for the engine/triggers.py module."""

from __future__ import annotations

import asyncio
from datetime import datetime, time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.engine.helpers import mock_host
from haanim.events import ActionEvent, StateEvent
from haanim.engine.triggers import (
    BaseTrigger,
    StateTrigger,
    TimeTrigger,
    EventTrigger,
    TriggerManager,
)
from haanim.engine.automation_context import TriggerDefinition
from haanim.const import (
    CONSTRAINT_STATE,
    TRIGGER_STATE,
    CONSTRAINT_TIME,
    TRIGGER_TIME,
    TRIGGER_EVENT,
    EVENT_HOST_STARTED,
)


class ConcreteTrigger(BaseTrigger):
    """Concrete trigger for testing base class."""

    async def async_start(self) -> None:
        """Start the trigger."""

    async def async_stop(self) -> None:
        """Stop the trigger."""


class TestBaseTrigger:
    """Tests for BaseTrigger class."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(
            side_effect=lambda func, *args: (
                func(*args) if not asyncio.iscoroutinefunction(func) else func(*args)
            )
        )
        return hass

    @pytest.fixture
    def mock_state_manager(self) -> MagicMock:
        """Create a mock state manager."""
        return MagicMock()

    @pytest.fixture
    def mock_event_manager(self) -> MagicMock:
        """Create a mock event manager."""
        return MagicMock()

    @pytest.fixture
    def trigger_def(self) -> TriggerDefinition:
        """Create a trigger definition."""
        return TriggerDefinition(
            trigger_type="state",
            trigger_expr="sensor.test > 50",
            func_name="on_trigger",
            func=MagicMock(),
            kwargs={},
            automation_id="test_automation",
        )

    @pytest.fixture
    def trigger(
        self,
        mock_hass: MagicMock,
        trigger_def: TriggerDefinition,
        mock_state_manager: MagicMock,
        mock_event_manager: MagicMock,
    ) -> ConcreteTrigger:
        """Create a concrete trigger instance."""
        return ConcreteTrigger(
            host=mock_host(states=mock_state_manager, events=mock_event_manager),
            trigger_def=trigger_def,
        )

    def test_init(self, trigger: ConcreteTrigger) -> None:
        """Test trigger initialization."""
        assert trigger._enabled is True
        assert trigger._constraints == []
        assert trigger._task is None

    def test_set_constraints(self, trigger: ConcreteTrigger) -> None:
        """Test setting constraints."""
        constraints = [
            {"type": CONSTRAINT_TIME, "specs": ["range(08:00, 18:00)"]},
            {"type": CONSTRAINT_STATE, "exprs": ["light.office == 'on'"]},
        ]
        trigger.set_constraints(constraints)
        assert trigger._constraints == constraints

    async def test_check_constraints_empty(self, trigger: ConcreteTrigger) -> None:
        """Test check_constraints with no constraints returns True."""
        result = await trigger._check_constraints()
        assert result is True

    async def test_check_time_constraint_no_specs(self, trigger: ConcreteTrigger) -> None:
        """Test time constraint with no specs returns True."""
        constraint = {"type": CONSTRAINT_TIME, "specs": []}
        result = await trigger._check_time_constraint(constraint)
        assert result is True

    @pytest.mark.parametrize(
        ("time_str", "expected_hour", "expected_minute"),
        [
            ("08:00", 8, 0),
            ("23:59", 23, 59),
            ("00:00", 0, 0),
            ("12:30:45", 12, 30),  # With seconds
        ],
    )
    def test_parse_time_value_hhmm(
        self,
        trigger: ConcreteTrigger,
        time_str: str,
        expected_hour: int,
        expected_minute: int,
    ) -> None:
        """Test parsing HH:MM time format."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        result = trigger._parse_time_value(time_str, now)
        assert result is not None
        assert result.hour == expected_hour
        assert result.minute == expected_minute

    def test_parse_time_value_invalid(self, trigger: ConcreteTrigger) -> None:
        """Test parsing invalid time returns None."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        result = trigger._parse_time_value("invalid", now)
        assert result is None

    @pytest.mark.parametrize(
        ("expr", "state_val", "expected"),
        [
            ("sensor.temp == 'on'", "on", True),
            ("sensor.temp == 'on'", "off", False),
            ("sensor.temp != 'off'", "on", True),
            ("sensor.temp != 'off'", "off", False),
            ("sensor.temp > 25", "30", True),
            ("sensor.temp > 25", "20", False),
            ("sensor.temp >= 25", "25", True),
            ("sensor.temp >= 25", "24", False),
            ("sensor.temp < 25", "20", True),
            ("sensor.temp < 25", "30", False),
            ("sensor.temp <= 25", "25", True),
            ("sensor.temp <= 25", "26", False),
            ("sensor.temp == 25", "25", True),
            ("sensor.temp == 25", "26", False),
            ("sensor.temp != 25", "26", True),
            ("sensor.temp != 25", "25", False),
        ],
    )
    def test_evaluate_state_expr(
        self,
        trigger: ConcreteTrigger,
        mock_state_manager: MagicMock,
        expr: str,
        state_val: str,
        expected: bool,
    ) -> None:
        """Test evaluating state expressions."""
        mock_state = MagicMock()
        mock_state.state = state_val
        mock_state.is_available.return_value = True
        mock_state_manager.get.return_value = mock_state

        result = trigger._evaluate_state_expr(expr)
        assert result is expected

    def test_evaluate_state_expr_unavailable(
        self,
        trigger: ConcreteTrigger,
        mock_state_manager: MagicMock,
    ) -> None:
        """Test evaluating state expression with unavailable entity."""
        mock_state = MagicMock()
        mock_state.is_available.return_value = False
        mock_state_manager.get.return_value = mock_state

        result = trigger._evaluate_state_expr("sensor.temp > 25")
        assert result is False

    def test_evaluate_state_expr_invalid(
        self,
        trigger: ConcreteTrigger,
    ) -> None:
        """Test evaluating invalid expression."""
        result = trigger._evaluate_state_expr("not a valid expression")
        assert result is False

    async def test_execute_function_async(
        self,
        trigger: ConcreteTrigger,
    ) -> None:
        """Test executing an async trigger function."""
        async_func = AsyncMock(return_value="result")
        trigger.trigger_def = TriggerDefinition(
            trigger_type="state",
            trigger_expr="sensor.test > 50",
            func_name="on_trigger",
            func=async_func,
            kwargs={},
            automation_id="test_automation",
        )

        event = trigger._event(StateEvent, entity_id="sensor.test", old_state=None, new_state=None)
        result = await trigger._execute_function(event)

        async_func.assert_called_once_with(event)
        assert (event.automation_id, event.source, event.data) == ("test_automation", "trigger", {})
        assert result == "result"

    async def test_execute_function_sync(
        self,
        trigger: ConcreteTrigger,
        mock_hass: MagicMock,
    ) -> None:
        """Test executing a sync trigger function."""
        sync_func = MagicMock(return_value="sync_result")
        trigger.trigger_def = TriggerDefinition(
            trigger_type="state",
            trigger_expr="sensor.test > 50",
            func_name="on_trigger",
            func=sync_func,
            kwargs={},
            automation_id="test_automation",
        )

        result = await trigger._execute_function(trigger._event(ActionEvent))

        assert result == "sync_result"


class TestTriggerManager:
    """Tests for TriggerManager."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.bus.async_listen_once = MagicMock()
        hass.async_add_executor_job = AsyncMock(
            side_effect=lambda func, *args: func(*args) if callable(func) else None
        )
        return hass

    @pytest.fixture
    def mock_state_manager(self) -> MagicMock:
        """Create a mock state manager."""
        return MagicMock()

    @pytest.fixture
    def mock_event_manager(self) -> MagicMock:
        """Create a mock event manager."""
        return MagicMock()

    @pytest.fixture
    def trigger_manager(
        self,
        mock_hass: MagicMock,
        mock_state_manager: MagicMock,
        mock_event_manager: MagicMock,
    ) -> TriggerManager:
        """Create a TriggerManager instance."""
        return TriggerManager(
            host=mock_host(states=mock_state_manager, events=mock_event_manager),
            dispatcher=MagicMock(),
        )

    async def test_async_setup(
        self,
        trigger_manager: TriggerManager,
        mock_event_manager: MagicMock,
    ) -> None:
        """Test async_setup registers startup listener."""
        await trigger_manager.async_setup()
        mock_event_manager.listen_once.assert_called_once_with(
            EVENT_HOST_STARTED, trigger_manager._on_ha_started
        )

    async def test_async_teardown(self, trigger_manager: TriggerManager) -> None:
        """Test async_teardown stops triggers."""
        await trigger_manager.async_teardown()
        assert len(trigger_manager._triggers) == 0

    @pytest.mark.parametrize(
        "trigger_type",
        [TRIGGER_STATE, TRIGGER_TIME, TRIGGER_EVENT],
    )
    async def test_register_trigger(
        self,
        trigger_manager: TriggerManager,
        trigger_type: str,
    ) -> None:
        """Test registering different trigger types."""
        expressions = {TRIGGER_STATE: "sensor.a == 'on'", TRIGGER_TIME: "09:00", TRIGGER_EVENT: "my_event"}
        trigger_def = TriggerDefinition(
            trigger_type=trigger_type,
            trigger_expr=expressions[trigger_type],
            func_name="func",
            func=MagicMock(),
            kwargs={},
            automation_id="test",
        )

        trigger_id = await trigger_manager.register_trigger(trigger_def)

        assert trigger_id != ""
        assert len(trigger_manager._triggers) == 1
        assert trigger_manager._triggers[trigger_id] is trigger_def

    async def test_register_unknown_trigger_type(
        self,
        trigger_manager: TriggerManager,
    ) -> None:
        """Test registering unknown trigger type returns empty string."""
        trigger_def = TriggerDefinition(
            trigger_type="unknown",
            trigger_expr="test_expr",
            func_name="func",
            func=MagicMock(),
            kwargs={},
            automation_id="test",
        )

        trigger_id = await trigger_manager.register_trigger(trigger_def)

        assert trigger_id == ""
        assert len(trigger_manager._triggers) == 0


class TestTimeRangeEvaluation:
    """Tests for time range evaluation."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        return MagicMock()

    @pytest.fixture
    def trigger(self, mock_hass: MagicMock) -> ConcreteTrigger:
        """Create a trigger for testing."""
        trigger_def = TriggerDefinition(
            trigger_type="state",
            trigger_expr="test",
            func_name="func",
            func=MagicMock(),
            kwargs={},
            automation_id="test",
        )
        return ConcreteTrigger(
            host=mock_host(),
            trigger_def=trigger_def,
        )

    @pytest.mark.parametrize(
        ("spec", "current_hour", "current_minute", "expected"),
        [
            ("range(08:00, 18:00)", 12, 0, True),  # Within range
            ("range(08:00, 18:00)", 7, 59, False),  # Before range
            ("range(08:00, 18:00)", 18, 1, False),  # After range
            ("range(08:00, 18:00)", 8, 0, True),  # At start
            ("range(08:00, 18:00)", 18, 0, True),  # At end
            ("range(22:00, 06:00)", 23, 0, True),  # Overnight - late
            ("range(22:00, 06:00)", 3, 0, True),  # Overnight - early
            ("range(22:00, 06:00)", 12, 0, False),  # Overnight - midday
        ],
    )
    def test_evaluate_time_spec_range(
        self,
        trigger: ConcreteTrigger,
        spec: str,
        current_hour: int,
        current_minute: int,
        expected: bool,
    ) -> None:
        """Test time range evaluation."""
        now = datetime(2024, 6, 15, current_hour, current_minute, 0)
        result = trigger._evaluate_time_spec(spec, now)
        assert result is expected

    def test_evaluate_time_spec_invalid(self, trigger: ConcreteTrigger) -> None:
        """Test invalid time spec returns False."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        result = trigger._evaluate_time_spec("invalid_spec", now)
        assert result is False


class TestStateTrigger:
    """Tests for StateTrigger class."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_create_task = MagicMock()
        return hass

    @pytest.fixture
    def mock_state_manager(self) -> MagicMock:
        """Create a mock state manager."""
        sm = MagicMock()
        sm.subscribe = MagicMock(return_value=asyncio.Queue())
        sm.unsubscribe = MagicMock()
        return sm

    @pytest.fixture
    def trigger_def(self) -> TriggerDefinition:
        """Create a trigger definition."""
        return TriggerDefinition(
            trigger_type=TRIGGER_STATE,
            trigger_expr="sensor.test > 50",
            func_name="on_state",
            func=MagicMock(),
            kwargs={},
            automation_id="test_automation",
        )

    @pytest.fixture
    def state_trigger(
        self,
        mock_hass: MagicMock,
        trigger_def: TriggerDefinition,
        mock_state_manager: MagicMock,
    ) -> StateTrigger:
        """Create a StateTrigger instance."""
        return StateTrigger(
            host=mock_host(states=mock_state_manager),
            trigger_def=trigger_def,
        )

    def test_init_defaults(self, state_trigger: StateTrigger) -> None:
        """Test default initialization."""
        assert state_trigger._state_hold is None
        assert state_trigger._state_check_now is False
        assert state_trigger._watch_entities == []

    def test_init_with_state_hold(self, mock_hass: MagicMock, mock_state_manager: MagicMock) -> None:
        """Test initialization with state_hold."""
        trigger_def = TriggerDefinition(
            trigger_type=TRIGGER_STATE,
            trigger_expr="sensor.test > 50",
            func_name="on_state",
            func=MagicMock(),
            kwargs={"hold": 5.0, "state_check_now": True},
            automation_id="test_automation",
        )
        trigger = StateTrigger(
            host=mock_host(states=mock_state_manager),
            trigger_def=trigger_def,
        )
        assert trigger._state_hold == 5.0
        assert trigger._state_check_now is True

    @pytest.mark.parametrize(
        ("state_hold", "expected"),
        [
            (5.0, 5.0),
            ("10", 10.0),
            (-1, None),  # Negative value
            ("invalid", None),  # Non-numeric
            (None, None),
        ],
    )
    def test_get_state_hold_from_trigger(
        self, mock_hass: MagicMock, mock_state_manager: MagicMock, state_hold: Any, expected: float | None
    ) -> None:
        """Test _get_state_hold_from_trigger validation."""
        trigger_def = TriggerDefinition(
            trigger_type=TRIGGER_STATE,
            trigger_expr="sensor.test > 50",
            func_name="on_state",
            func=MagicMock(),
            kwargs={"hold": state_hold},
            automation_id="test_automation",
        )
        trigger = StateTrigger(
            host=mock_host(states=mock_state_manager),
            trigger_def=trigger_def,
        )
        assert trigger._state_hold == expected

    @pytest.mark.parametrize(
        ("expr", "expected_entities"),
        [
            ("sensor.temp > 50", ["sensor.temp"]),
            ("light.office == 'on'", ["light.office"]),
            ("sensor.a > 10 and sensor.b < 20", ["sensor.a", "sensor.b"]),
            (["sensor.temp > 50", "light.office == 'on'"], ["sensor.temp", "light.office"]),
        ],
    )
    def test_extract_entities(
        self, state_trigger: StateTrigger, expr: str | list[str], expected_entities: list[str]
    ) -> None:
        """Test extracting entity IDs from expressions."""
        result = state_trigger._extract_entities(expr)
        assert set(result) == set(expected_entities)

    async def test_async_start(self, state_trigger: StateTrigger, mock_hass: MagicMock) -> None:
        """Test async_start subscribes and creates task."""
        await state_trigger.async_start()

        assert state_trigger._watch_entities == ["sensor.test"]
        assert state_trigger._task is not None
        await state_trigger.async_stop()


class TestEventTrigger:
    """Tests for EventTrigger class."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_create_task = MagicMock()
        return hass

    @pytest.fixture
    def mock_event_manager(self) -> MagicMock:
        """Create a mock event manager."""
        em = MagicMock()
        em.subscribe = MagicMock(return_value=asyncio.Queue())
        em.unsubscribe = MagicMock()
        return em

    @pytest.fixture
    def trigger_def(self) -> TriggerDefinition:
        """Create a trigger definition."""
        return TriggerDefinition(
            trigger_type=TRIGGER_EVENT,
            trigger_expr="custom_event",
            func_name="on_event",
            func=MagicMock(),
            kwargs={},
            automation_id="test_automation",
        )

    @pytest.fixture
    def event_trigger(
        self, mock_hass: MagicMock, trigger_def: TriggerDefinition, mock_event_manager: MagicMock
    ) -> EventTrigger:
        """Create an EventTrigger instance."""
        return EventTrigger(
            host=mock_host(events=mock_event_manager),
            trigger_def=trigger_def,
        )

    def test_init(self, event_trigger: EventTrigger) -> None:
        """Test initialization."""
        assert event_trigger._event_type == "custom_event"

    async def test_async_start(
        self, event_trigger: EventTrigger, mock_hass: MagicMock, mock_event_manager: MagicMock
    ) -> None:
        """Test async_start subscribes to events."""
        await event_trigger.async_start()
        # Subscribe is called with event_type and optional filter (None)
        mock_event_manager.subscribe.assert_called_once_with("custom_event", None)
        assert event_trigger._task is not None
        await event_trigger.async_stop()

    async def test_async_stop(self, event_trigger: EventTrigger) -> None:
        """Test async_stop cancels task."""

        # Create an actual async task that we can cancel
        async def long_running():
            await asyncio.Event().wait()

        event_trigger._queue = asyncio.Queue()
        event_trigger._task = asyncio.create_task(long_running())

        await event_trigger.async_stop()

        assert event_trigger._task.cancelled() or event_trigger._task.done()


class TestStateTriggerAdvanced:
    """Advanced tests for StateTrigger."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_create_task = MagicMock()
        return hass

    @pytest.fixture
    def mock_state_manager(self) -> MagicMock:
        """Create a mock state manager."""
        sm = MagicMock()
        sm.subscribe = MagicMock(return_value=asyncio.Queue())
        sm.unsubscribe = MagicMock()
        return sm

    @pytest.fixture
    def state_trigger(self, mock_hass: MagicMock, mock_state_manager: MagicMock) -> StateTrigger:
        """Create a StateTrigger instance."""
        trigger_def = TriggerDefinition(
            trigger_type=TRIGGER_STATE,
            trigger_expr="sensor.test > 50",
            func_name="on_state",
            func=MagicMock(),
            kwargs={},
            automation_id="test_automation",
        )
        return StateTrigger(
            host=mock_host(states=mock_state_manager),
            trigger_def=trigger_def,
        )

    def test_evaluate_trigger_single_expr(
        self, state_trigger: StateTrigger, mock_state_manager: MagicMock
    ) -> None:
        """Test evaluating single trigger expression."""
        mock_state = MagicMock()
        mock_state.state = "60"
        mock_state.is_available.return_value = True
        mock_state_manager.get.return_value = mock_state

        result = state_trigger._evaluate_trigger()
        assert result is True

    def test_evaluate_trigger_list_expr(self, mock_hass: MagicMock, mock_state_manager: MagicMock) -> None:
        """Test evaluating list of trigger expressions."""
        trigger_def = TriggerDefinition(
            trigger_type=TRIGGER_STATE,
            trigger_expr=["sensor.a > 50", "sensor.b < 10"],
            func_name="on_state",
            func=MagicMock(),
            kwargs={},
            automation_id="test_automation",
        )
        trigger = StateTrigger(
            host=mock_host(states=mock_state_manager),
            trigger_def=trigger_def,
        )

        # First expr matches
        mock_state = MagicMock()
        mock_state.state = "60"
        mock_state.is_available.return_value = True
        mock_state_manager.get.return_value = mock_state

        result = trigger._evaluate_trigger()
        assert result is True

    async def test_async_stop_with_hold_task(
        self, state_trigger: StateTrigger, mock_state_manager: MagicMock
    ) -> None:
        """Test async_stop cancels hold task."""

        async def long_running():
            await asyncio.Event().wait()

        state_trigger._task = asyncio.create_task(long_running())
        state_trigger._hold_task = asyncio.create_task(long_running())
        state_trigger._queue = asyncio.Queue()
        state_trigger._watch_entities = ["sensor.test"]

        await state_trigger.async_stop()

        assert state_trigger._task.cancelled() or state_trigger._task.done()
        # Hold task may be in cancelling state, so check it's done or cancelling
        assert state_trigger._hold_task.cancelled() or state_trigger._hold_task.cancelling()

    def test_init_with_watch_entities(self, mock_hass: MagicMock, mock_state_manager: MagicMock) -> None:
        """Test initialization with explicit watch entities."""
        trigger_def = TriggerDefinition(
            trigger_type=TRIGGER_STATE,
            trigger_expr="sensor.test > 50",
            func_name="on_state",
            func=MagicMock(),
            kwargs={"watch": ["sensor.a", "sensor.b"]},
            automation_id="test_automation",
        )
        trigger = StateTrigger(
            host=mock_host(states=mock_state_manager),
            trigger_def=trigger_def,
        )
        assert trigger._watch_entities == ["sensor.a", "sensor.b"]


class TestTriggerManagerAdvanced:
    """Advanced tests for TriggerManager."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.bus.async_listen_once = MagicMock()
        hass.async_add_executor_job = AsyncMock(
            side_effect=lambda func, *args: func(*args) if callable(func) else None
        )
        return hass

    @pytest.fixture
    def trigger_manager(self, mock_hass: MagicMock) -> TriggerManager:
        """Create a TriggerManager instance."""
        return TriggerManager(
            host=mock_host(),
            dispatcher=MagicMock(),
        )

    async def test_unregister_trigger(self, trigger_manager: TriggerManager) -> None:
        """Test unregistering a trigger."""
        trigger_def = TriggerDefinition(
            trigger_type=TRIGGER_STATE,
            trigger_expr="sensor.test > 50",
            func_name="func",
            func=MagicMock(),
            kwargs={},
            automation_id="test",
        )

        trigger_id = await trigger_manager.register_trigger(trigger_def)
        assert trigger_id != ""
        assert len(trigger_manager._triggers) == 1

        result = await trigger_manager.unregister_trigger(trigger_id)
        assert result is True
        assert len(trigger_manager._triggers) == 0

    async def test_unregister_trigger_not_found(self, trigger_manager: TriggerManager) -> None:
        """Test unregistering a non-existent trigger."""
        result = await trigger_manager.unregister_trigger("nonexistent")
        assert result is False

    async def test_get_trigger_count(self, trigger_manager: TriggerManager) -> None:
        """Test getting trigger count."""
        assert trigger_manager.get_trigger_count() == 0

        trigger_def = TriggerDefinition(
            trigger_type=TRIGGER_STATE,
            trigger_expr="sensor.test > 50",
            func_name="func",
            func=MagicMock(),
            kwargs={},
            automation_id="my_automation",
        )

        await trigger_manager.register_trigger(trigger_def)

        assert trigger_manager.get_trigger_count() == 1

    async def test_unregister_automation_triggers(self, trigger_manager: TriggerManager) -> None:
        """Test unregistering all triggers for an automation."""
        trigger_def = TriggerDefinition(
            trigger_type=TRIGGER_STATE,
            trigger_expr="sensor.test > 50",
            func_name="func",
            func=MagicMock(),
            kwargs={},
            automation_id="my_automation",
        )

        await trigger_manager.register_trigger(trigger_def)
        assert trigger_manager.get_trigger_count() == 1

        count = await trigger_manager.unregister_automation_triggers("my_automation")
        assert count == 1
        assert trigger_manager.get_trigger_count() == 0

    async def test_register_trigger_with_constraints(self, trigger_manager: TriggerManager) -> None:
        """Test registering a trigger with constraints."""
        trigger_def = TriggerDefinition(
            trigger_type=TRIGGER_STATE,
            trigger_expr="sensor.test > 50",
            func_name="func",
            func=MagicMock(),
            kwargs={},
            automation_id="test",
        )
        constraints = [{"type": CONSTRAINT_TIME, "specs": ["range(08:00, 18:00)"]}]

        trigger_id = await trigger_manager.register_trigger(trigger_def, constraints)

        assert trigger_id != ""
        assert trigger_manager._trigger_metadata[trigger_id]["constraints"] == constraints


class TestBaseTriggerConstraints:
    """Tests for BaseTrigger constraint checking."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
        return hass

    @pytest.fixture
    def mock_state_manager(self) -> MagicMock:
        """Create a mock state manager."""
        return MagicMock()

    @pytest.fixture
    def mock_event_manager(self) -> MagicMock:
        """Create a mock event manager."""
        return MagicMock()

    @pytest.fixture
    def trigger_def(self) -> TriggerDefinition:
        """Create a trigger definition."""
        return TriggerDefinition(
            trigger_type="state",
            trigger_expr="sensor.test > 50",
            func_name="on_trigger",
            func=MagicMock(),
            kwargs={},
            automation_id="test_automation",
        )

    async def test_check_constraints_time_active(
        self,
        mock_hass: MagicMock,
        trigger_def: TriggerDefinition,
        mock_state_manager: MagicMock,
        mock_event_manager: MagicMock,
    ) -> None:
        """Test _check_constraints with time_active constraint."""
        trigger = ConcreteTrigger(
            host=mock_host(states=mock_state_manager, events=mock_event_manager),
            trigger_def=trigger_def,
        )
        trigger.set_constraints([{"type": CONSTRAINT_TIME, "specs": []}])
        result = await trigger._check_constraints()
        assert result is True

    async def test_check_constraints_state_active(
        self,
        mock_hass: MagicMock,
        trigger_def: TriggerDefinition,
        mock_state_manager: MagicMock,
        mock_event_manager: MagicMock,
    ) -> None:
        """Test _check_constraints with state_active constraint."""
        mock_state = MagicMock()
        mock_state.state = "on"
        mock_state.is_available.return_value = True
        mock_state_manager.get.return_value = mock_state

        trigger = ConcreteTrigger(
            host=mock_host(states=mock_state_manager, events=mock_event_manager),
            trigger_def=trigger_def,
        )
        trigger.set_constraints([{"type": CONSTRAINT_STATE, "exprs": ["light.test == 'on'"]}])
        result = await trigger._check_constraints()
        assert result is True

    async def test_check_state_constraint(
        self,
        mock_hass: MagicMock,
        trigger_def: TriggerDefinition,
        mock_state_manager: MagicMock,
        mock_event_manager: MagicMock,
    ) -> None:
        """Test _check_state_constraint method."""
        mock_state = MagicMock()
        mock_state.state = "on"
        mock_state.is_available.return_value = True
        mock_state_manager.get.return_value = mock_state

        trigger = ConcreteTrigger(
            host=mock_host(states=mock_state_manager, events=mock_event_manager),
            trigger_def=trigger_def,
        )
        result = await trigger._check_state_constraint({"exprs": ["light.test == 'on'"]})
        assert result is True

    async def test_check_state_constraint_fails(
        self,
        mock_hass: MagicMock,
        trigger_def: TriggerDefinition,
        mock_state_manager: MagicMock,
        mock_event_manager: MagicMock,
    ) -> None:
        """Test _check_state_constraint returns False when expr fails."""
        mock_state = MagicMock()
        mock_state.state = "off"
        mock_state.is_available.return_value = True
        mock_state_manager.get.return_value = mock_state

        trigger = ConcreteTrigger(
            host=mock_host(states=mock_state_manager, events=mock_event_manager),
            trigger_def=trigger_def,
        )
        result = await trigger._check_state_constraint({"exprs": ["light.test == 'on'"]})
        assert result is False

    async def test_execute_function_async(
        self,
        mock_hass: MagicMock,
        mock_state_manager: MagicMock,
        mock_event_manager: MagicMock,
    ) -> None:
        """Test _execute_function with async function."""
        async_func = AsyncMock(return_value="result")
        trigger_def = TriggerDefinition(
            trigger_type="state",
            trigger_expr="sensor.test > 50",
            func_name="on_trigger",
            func=async_func,
            kwargs={},
            automation_id="test_automation",
        )

        trigger = ConcreteTrigger(
            host=mock_host(states=mock_state_manager, events=mock_event_manager),
            trigger_def=trigger_def,
        )
        result = await trigger._execute_function(trigger._event(ActionEvent))
        assert result == "result"
        async_func.assert_awaited_once()

    async def test_execute_function_sync(
        self,
        mock_hass: MagicMock,
        mock_state_manager: MagicMock,
        mock_event_manager: MagicMock,
    ) -> None:
        """Test _execute_function with sync function."""
        sync_func = MagicMock(return_value="sync_result")
        trigger_def = TriggerDefinition(
            trigger_type="state",
            trigger_expr="sensor.test > 50",
            func_name="on_trigger",
            func=sync_func,
            kwargs={},
            automation_id="test_automation",
        )

        trigger = ConcreteTrigger(
            host=mock_host(states=mock_state_manager, events=mock_event_manager),
            trigger_def=trigger_def,
        )
        result = await trigger._execute_function(trigger._event(ActionEvent))
        assert result == "sync_result"

    @pytest.mark.parametrize(
        ("state_val", "expected"),
        [
            ("", False),  # Empty state
            (None, False),  # None state
            ("invalid", False),  # Non-numeric
        ],
    )
    def test_evaluate_state_expr_numeric_edge_cases(
        self,
        mock_hass: MagicMock,
        trigger_def: TriggerDefinition,
        mock_state_manager: MagicMock,
        mock_event_manager: MagicMock,
        state_val: str | None,
        expected: bool,
    ) -> None:
        """Test evaluating state expressions with edge cases."""
        mock_state = MagicMock()
        mock_state.state = state_val
        mock_state.is_available.return_value = True
        mock_state_manager.get.return_value = mock_state

        trigger = ConcreteTrigger(
            host=mock_host(states=mock_state_manager, events=mock_event_manager),
            trigger_def=trigger_def,
        )
        result = trigger._evaluate_state_expr("sensor.temp > 25")
        assert result is expected


class TestEventTriggerAdvanced:
    """Advanced tests for EventTrigger class."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_create_task = MagicMock(return_value=MagicMock())
        hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
        return hass

    @pytest.fixture
    def mock_state_manager(self) -> MagicMock:
        """Create a mock state manager."""
        return MagicMock()

    @pytest.fixture
    def mock_event_manager(self) -> MagicMock:
        """Create a mock event manager."""
        manager = MagicMock()
        manager.subscribe = MagicMock(return_value=asyncio.Queue())
        return manager

    async def test_async_start(
        self,
        mock_hass: MagicMock,
        mock_state_manager: MagicMock,
        mock_event_manager: MagicMock,
    ) -> None:
        """Test EventTrigger async_start."""
        trigger_def = TriggerDefinition(
            trigger_type=TRIGGER_EVENT,
            trigger_expr="my_custom_event",
            func_name="on_event",
            func=AsyncMock(),
            kwargs={},
            automation_id="test_automation",
        )
        trigger = EventTrigger(
            host=mock_host(states=mock_state_manager, events=mock_event_manager),
            trigger_def=trigger_def,
        )
        await trigger.async_start()
        mock_event_manager.subscribe.assert_called_once()
        assert trigger._task is not None
        await trigger.async_stop()

    async def test_async_stop(
        self,
        mock_hass: MagicMock,
        mock_state_manager: MagicMock,
        mock_event_manager: MagicMock,
    ) -> None:
        """Test EventTrigger async_stop cancels task."""
        trigger_def = TriggerDefinition(
            trigger_type=TRIGGER_EVENT,
            trigger_expr="my_custom_event",
            func_name="on_event",
            func=AsyncMock(),
            kwargs={},
            automation_id="test_automation",
        )
        trigger = EventTrigger(
            host=mock_host(states=mock_state_manager, events=mock_event_manager),
            trigger_def=trigger_def,
        )

        # Create a real task that we can cancel
        async def long_running():
            await asyncio.Event().wait()

        trigger._task = asyncio.create_task(long_running())
        await trigger.async_stop()
        assert trigger._task.cancelled() or trigger._task.done()


class TestTimeConstraintEvaluation:
    """Tests for time constraint evaluation in BaseTrigger."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(
            side_effect=lambda func, *args: (
                func(*args) if not asyncio.iscoroutinefunction(func) else func(*args)
            )
        )
        return hass

    @pytest.fixture
    def mock_state_manager(self) -> MagicMock:
        """Create a mock state manager."""
        return MagicMock()

    @pytest.fixture
    def mock_event_manager(self) -> MagicMock:
        """Create a mock event manager."""
        return MagicMock()

    @pytest.fixture
    def trigger_def(self) -> TriggerDefinition:
        """Create a trigger definition."""
        return TriggerDefinition(
            trigger_type=TRIGGER_STATE,
            trigger_expr="sensor.test > 50",
            func_name="on_trigger",
            func=MagicMock(),
            kwargs={},
            automation_id="test_automation",
        )

    @pytest.fixture
    def trigger(
        self,
        mock_hass: MagicMock,
        trigger_def: TriggerDefinition,
        mock_state_manager: MagicMock,
        mock_event_manager: MagicMock,
    ) -> StateTrigger:
        """Create a StateTrigger instance for testing."""
        return StateTrigger(
            host=mock_host(states=mock_state_manager, events=mock_event_manager),
            trigger_def=trigger_def,
        )

    async def test_check_time_constraint_no_specs(self, trigger: StateTrigger) -> None:
        """Test that time constraint with no specs is always active."""
        constraint = {"type": CONSTRAINT_TIME, "specs": []}
        result = await trigger._check_time_constraint(constraint)
        assert result is True

    def test_parse_time_value_hhmm_format(self, trigger: StateTrigger) -> None:
        """Test parsing HH:MM time format."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        result = trigger._parse_time_value("14:30", now)
        assert result == time(14, 30, 0)

    def test_parse_time_value_hhmmss_format(self, trigger: StateTrigger) -> None:
        """Test parsing HH:MM:SS time format."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        result = trigger._parse_time_value("14:30:45", now)
        assert result == time(14, 30, 45)

    def test_parse_time_value_invalid(self, trigger: StateTrigger) -> None:
        """Test parsing invalid time format returns None."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        result = trigger._parse_time_value("not_a_time", now)
        assert result is None

    def test_parse_time_value_sunrise(self, trigger: StateTrigger) -> None:
        """Test parsing sunrise returns time."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        with patch.object(trigger.host.sun, "next_event") as mock_sun:
            mock_sun.return_value = datetime(2024, 1, 15, 7, 30, 0)
            result = trigger._parse_time_value("sunrise", now)
            assert result == time(7, 30, 0)
            mock_sun.assert_called()

    def test_parse_time_value_sunset(self, trigger: StateTrigger) -> None:
        """Test parsing sunset returns time."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        with patch.object(trigger.host.sun, "next_event") as mock_sun:
            mock_sun.return_value = datetime(2024, 1, 15, 18, 45, 0)
            result = trigger._parse_time_value("sunset", now)
            assert result == time(18, 45, 0)
            mock_sun.assert_called()

    def test_parse_time_value_sunrise_none(self, trigger: StateTrigger) -> None:
        """Test parsing sunrise returns None when sun data unavailable."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        with patch.object(trigger.host.sun, "next_event") as mock_sun:
            mock_sun.return_value = None
            result = trigger._parse_time_value("sunrise", now)
            assert result is None

    def test_parse_time_value_sunset_none(self, trigger: StateTrigger) -> None:
        """Test parsing sunset returns None when sun data unavailable."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        with patch.object(trigger.host.sun, "next_event") as mock_sun:
            mock_sun.return_value = None
            result = trigger._parse_time_value("sunset", now)
            assert result is None

    async def test_check_time_constraint_range_normal(self, trigger: StateTrigger) -> None:
        """Test evaluating time spec for normal range."""
        # Mock a specific current time
        with patch.object(trigger.host.clock, "now") as mock_now:
            current = datetime(2024, 1, 15, 14, 30, 0)
            mock_now.return_value = current
            # Create constraint that includes 14:30
            constraint = {"type": CONSTRAINT_TIME, "specs": ["range(12:00, 18:00)"]}
            result = await trigger._check_time_constraint(constraint)
            assert result is True

    async def test_check_time_constraint_range_outside(self, trigger: StateTrigger) -> None:
        """Test evaluating time spec when outside range."""
        with patch.object(trigger.host.clock, "now") as mock_now:
            current = datetime(2024, 1, 15, 20, 30, 0)
            mock_now.return_value = current
            # Create constraint that does not include 20:30
            constraint = {"type": CONSTRAINT_TIME, "specs": ["range(08:00, 18:00)"]}
            result = await trigger._check_time_constraint(constraint)
            assert result is False

    async def test_check_time_constraint_overnight_range(self, trigger: StateTrigger) -> None:
        """Test evaluating overnight time range."""
        with patch.object(trigger.host.clock, "now") as mock_now:
            current = datetime(2024, 1, 15, 23, 30, 0)
            mock_now.return_value = current
            # Overnight range from 22:00 to 06:00
            constraint = {"type": CONSTRAINT_TIME, "specs": ["range(22:00, 06:00)"]}
            result = await trigger._check_time_constraint(constraint)
            assert result is True

    async def test_check_time_constraint_overnight_morning(self, trigger: StateTrigger) -> None:
        """Test evaluating overnight time range in morning."""
        with patch.object(trigger.host.clock, "now") as mock_now:
            current = datetime(2024, 1, 15, 4, 30, 0)
            mock_now.return_value = current
            # Overnight range from 22:00 to 06:00
            constraint = {"type": CONSTRAINT_TIME, "specs": ["range(22:00, 06:00)"]}
            result = await trigger._check_time_constraint(constraint)
            assert result is True


class TestStateConstraintEvaluation:
    """Tests for state constraint evaluation in BaseTrigger."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        return hass

    def _create_state_mock(self, state_value: str, available: bool = True) -> MagicMock:
        """Create a mock State object."""
        state = MagicMock()
        state.is_available.return_value = available
        state.state = state_value
        state.__str__ = MagicMock(return_value=state_value)
        # Override == operator for state comparison
        state.__eq__ = MagicMock(side_effect=lambda x: state_value == x)
        return state

    @pytest.fixture
    def mock_state_manager(self) -> MagicMock:
        """Create a mock state manager."""
        manager = MagicMock()
        return manager

    @pytest.fixture
    def mock_event_manager(self) -> MagicMock:
        """Create a mock event manager."""
        return MagicMock()

    @pytest.fixture
    def trigger_def(self) -> TriggerDefinition:
        """Create a trigger definition."""
        return TriggerDefinition(
            trigger_type=TRIGGER_STATE,
            trigger_expr="sensor.test > 50",
            func_name="on_trigger",
            func=MagicMock(),
            kwargs={},
            automation_id="test_automation",
        )

    @pytest.fixture
    def trigger(
        self,
        mock_hass: MagicMock,
        trigger_def: TriggerDefinition,
        mock_state_manager: MagicMock,
        mock_event_manager: MagicMock,
    ) -> StateTrigger:
        """Create a StateTrigger instance for testing."""
        return StateTrigger(
            host=mock_host(states=mock_state_manager, events=mock_event_manager),
            trigger_def=trigger_def,
        )

    async def test_check_state_constraint_string_equal_true(
        self, trigger: StateTrigger, mock_state_manager: MagicMock
    ) -> None:
        """Test evaluating state constraint with string equality that is true."""
        mock_state_manager.get.return_value = self._create_state_mock("on")
        constraint = {"type": CONSTRAINT_STATE, "exprs": ["light.test == 'on'"]}
        result = await trigger._check_state_constraint(constraint)
        assert result is True

    async def test_check_state_constraint_string_equal_false(
        self, trigger: StateTrigger, mock_state_manager: MagicMock
    ) -> None:
        """Test evaluating state constraint with string equality that is false."""
        mock_state_manager.get.return_value = self._create_state_mock("off")
        constraint = {"type": CONSTRAINT_STATE, "exprs": ["light.test == 'on'"]}
        result = await trigger._check_state_constraint(constraint)
        assert result is False

    async def test_check_state_constraint_no_exprs(
        self, trigger: StateTrigger, mock_state_manager: MagicMock
    ) -> None:
        """Test evaluating state constraint with no expressions."""
        constraint = {"type": CONSTRAINT_STATE, "exprs": []}
        result = await trigger._check_state_constraint(constraint)
        # No expressions means always true
        assert result is True

    async def test_check_state_constraint_numeric_greater(
        self, trigger: StateTrigger, mock_state_manager: MagicMock
    ) -> None:
        """Test evaluating state constraint with numeric comparison."""
        mock_state_manager.get.return_value = self._create_state_mock("25.5")
        constraint = {"type": CONSTRAINT_STATE, "exprs": ["sensor.temp > 20"]}
        result = await trigger._check_state_constraint(constraint)
        assert result is True

    async def test_check_state_constraint_numeric_less(
        self, trigger: StateTrigger, mock_state_manager: MagicMock
    ) -> None:
        """Test evaluating state constraint with numeric less than."""
        mock_state_manager.get.return_value = self._create_state_mock("15")
        constraint = {"type": CONSTRAINT_STATE, "exprs": ["sensor.temp < 20"]}
        result = await trigger._check_state_constraint(constraint)
        assert result is True

    async def test_check_state_constraint_unavailable_state(
        self, trigger: StateTrigger, mock_state_manager: MagicMock
    ) -> None:
        """Test evaluating state constraint when state is unavailable."""
        mock_state_manager.get.return_value = self._create_state_mock("on", available=False)
        constraint = {"type": CONSTRAINT_STATE, "exprs": ["light.test == 'on'"]}
        result = await trigger._check_state_constraint(constraint)
        assert result is False
