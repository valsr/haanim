"""Tests for the engine/triggers.py module."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.engine.helpers import mock_host
from haanim.events import ActionEvent, StateEvent
from haanim.engine.triggers import (
    BaseTrigger,
    EventTrigger,
    TriggerManager,
)
from haanim.engine.automation_context import TriggerDefinition
from haanim.const import (
    TRIGGER_STATE,
    TRIGGER_EVENT,
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

    async def test_check_constraints_empty(self, trigger: ConcreteTrigger) -> None:
        """Test check_constraints with no constraints returns True."""
        result = await trigger._check_constraints()
        assert result is True

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

    async def test_async_teardown(self, trigger_manager: TriggerManager) -> None:
        """Test async_teardown stops triggers."""
        await trigger_manager.async_teardown()
        assert len(trigger_manager._triggers) == 0


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
