"""Tests for the ha/state.py module."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State as HAState

from custom_components.haanim.ha.state import (
    StateChangedEvent,
    StateManager,
    StateVal,
    state_get,
    state_set,
)


class TestStateChangedEvent:
    """Tests for StateChangedEvent dataclass."""

    def test_creation(self) -> None:
        """Test creating a StateChangedEvent."""
        old_state = StateVal(None, "sensor.test")
        new_state = StateVal(None, "sensor.test")
        event = StateChangedEvent(
            entity_id="sensor.test",
            old_state=old_state,
            new_state=new_state,
        )
        assert event.entity_id == "sensor.test"
        assert event.old_state is old_state
        assert event.new_state is new_state

    def test_creation_with_none_old_state(self) -> None:
        """Test creating event with None old_state."""
        new_state = StateVal(None, "sensor.test")
        event = StateChangedEvent(
            entity_id="sensor.test",
            old_state=None,
            new_state=new_state,
        )
        assert event.old_state is None


class TestStateVal:
    """Tests for StateVal wrapper class."""

    @pytest.fixture
    def mock_ha_state(self) -> MagicMock:
        """Create a mock Home Assistant state."""
        state = MagicMock(spec=HAState)
        state.entity_id = "sensor.test"
        state.state = "50"
        state.attributes = {"unit": "°C", "friendly_name": "Test Sensor"}
        state.last_changed = datetime(2024, 1, 1, 12, 0, 0)
        state.last_updated = datetime(2024, 1, 1, 12, 0, 1)
        return state

    def test_init_with_state(self, mock_ha_state: MagicMock) -> None:
        """Test initialization with a state object."""
        val = StateVal(mock_ha_state)
        assert val.state == "50"
        assert val.entity_id == "sensor.test"

    def test_init_with_none(self) -> None:
        """Test initialization with None state."""
        val = StateVal(None, "sensor.missing")
        assert val.state is None
        assert val.entity_id == "sensor.missing"

    def test_attributes(self, mock_ha_state: MagicMock) -> None:
        """Test getting attributes."""
        val = StateVal(mock_ha_state)
        assert val.attributes == {"unit": "°C", "friendly_name": "Test Sensor"}

    def test_attributes_none_state(self) -> None:
        """Test attributes returns empty dict for None state."""
        val = StateVal(None, "sensor.test")
        assert val.attributes == {}

    def test_last_changed(self, mock_ha_state: MagicMock) -> None:
        """Test last_changed property."""
        val = StateVal(mock_ha_state)
        assert val.last_changed == datetime(2024, 1, 1, 12, 0, 0)

    def test_last_changed_none_state(self) -> None:
        """Test last_changed returns None for None state."""
        val = StateVal(None, "sensor.test")
        assert val.last_changed is None

    def test_last_updated(self, mock_ha_state: MagicMock) -> None:
        """Test last_updated property."""
        val = StateVal(mock_ha_state)
        assert val.last_updated == datetime(2024, 1, 1, 12, 0, 1)

    def test_last_updated_none_state(self) -> None:
        """Test last_updated returns None for None state."""
        val = StateVal(None, "sensor.test")
        assert val.last_updated is None

    def test_str(self, mock_ha_state: MagicMock) -> None:
        """Test string representation."""
        val = StateVal(mock_ha_state)
        assert str(val) == "50"

    def test_str_none_state(self) -> None:
        """Test string representation for None state."""
        val = StateVal(None, "sensor.test")
        assert str(val) == ""

    def test_repr(self, mock_ha_state: MagicMock) -> None:
        """Test detailed representation."""
        val = StateVal(mock_ha_state)
        assert repr(val) == "StateVal(sensor.test=50)"

    @pytest.mark.parametrize(
        ("state_a", "compare_to", "expected"),
        [
            ("on", "on", True),
            ("on", "off", False),
            ("50", "50", True),
            ("50", 50, True),  # Coerced to string for comparison
        ],
    )
    def test_eq(self, state_a: str, compare_to: Any, expected: bool) -> None:
        """Test equality comparison."""
        mock_state = MagicMock(spec=HAState)
        mock_state.state = state_a
        mock_state.entity_id = "sensor.test"
        val = StateVal(mock_state)
        assert (val == compare_to) is expected

    def test_eq_with_stateval(self) -> None:
        """Test equality comparison between two StateVal objects."""
        mock_state1 = MagicMock(spec=HAState)
        mock_state1.state = "on"
        mock_state1.entity_id = "light.one"
        mock_state2 = MagicMock(spec=HAState)
        mock_state2.state = "on"
        mock_state2.entity_id = "light.two"

        val1 = StateVal(mock_state1)
        val2 = StateVal(mock_state2)
        assert val1 == val2

    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            ("on", True),
            ("off", False),
            ("true", True),
            ("false", False),
            ("1", True),
            ("0", False),
            (STATE_UNAVAILABLE, False),
            (STATE_UNKNOWN, False),
            ("", False),
            ("home", True),
        ],
    )
    def test_bool(self, state: str, expected: bool) -> None:
        """Test boolean evaluation."""
        mock_state = MagicMock(spec=HAState)
        mock_state.state = state
        mock_state.entity_id = "sensor.test"
        val = StateVal(mock_state)
        assert bool(val) is expected

    def test_bool_none_state(self) -> None:
        """Test boolean for None state."""
        val = StateVal(None, "sensor.test")
        assert bool(val) is False

    def test_getattr_attribute(self, mock_ha_state: MagicMock) -> None:
        """Test accessing attribute via getattr."""
        val = StateVal(mock_ha_state)
        assert val.unit == "°C"

    def test_getattr_missing_attribute(self, mock_ha_state: MagicMock) -> None:
        """Test accessing missing attribute raises error."""
        val = StateVal(mock_ha_state)
        with pytest.raises(AttributeError, match="has no attribute 'missing'"):
            _ = val.missing

    def test_getattr_private_attribute(self, mock_ha_state: MagicMock) -> None:
        """Test accessing private attribute raises error."""
        val = StateVal(mock_ha_state)
        with pytest.raises(AttributeError, match="has no attribute '_private'"):
            _ = val._private

    def test_getattr_none_state(self) -> None:
        """Test accessing attribute on None state raises error."""
        val = StateVal(None, "sensor.missing")
        with pytest.raises(AttributeError, match="Entity 'sensor.missing' not found"):
            _ = val.unit

    def test_get_existing(self, mock_ha_state: MagicMock) -> None:
        """Test get method for existing attribute."""
        val = StateVal(mock_ha_state)
        assert val.get("unit") == "°C"

    def test_get_missing_with_default(self, mock_ha_state: MagicMock) -> None:
        """Test get method with default for missing attribute."""
        val = StateVal(mock_ha_state)
        assert val.get("missing", "default") == "default"

    def test_get_none_state(self) -> None:
        """Test get returns default for None state."""
        val = StateVal(None, "sensor.test")
        assert val.get("unit", "default") == "default"

    @pytest.mark.parametrize(
        ("state", "default", "expected"),
        [
            ("42", 0, 42),
            ("42.9", 0, 42),
            ("invalid", 5, 5),
            (None, 10, 10),
        ],
    )
    def test_as_int(self, state: str | None, default: int, expected: int) -> None:
        """Test integer conversion."""
        if state is None:
            val = StateVal(None, "sensor.test")
        else:
            mock_state = MagicMock(spec=HAState)
            mock_state.state = state
            mock_state.entity_id = "sensor.test"
            val = StateVal(mock_state)
        assert val.as_int(default) == expected

    @pytest.mark.parametrize(
        ("state", "default", "expected"),
        [
            ("42.5", 0.0, 42.5),
            ("100", 0.0, 100.0),
            ("invalid", 1.5, 1.5),
            (None, 2.5, 2.5),
        ],
    )
    def test_as_float(self, state: str | None, default: float, expected: float) -> None:
        """Test float conversion."""
        if state is None:
            val = StateVal(None, "sensor.test")
        else:
            mock_state = MagicMock(spec=HAState)
            mock_state.state = state
            mock_state.entity_id = "sensor.test"
            val = StateVal(mock_state)
        assert val.as_float(default) == expected

    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            ("on", True),
            ("off", False),
            ("true", True),
            ("false", False),
            ("yes", True),
            ("no", False),
            ("1", True),
            ("0", False),
            ("home", True),
            ("open", True),
            ("away", False),
            ("closed", False),
        ],
    )
    def test_as_bool(self, state: str, expected: bool) -> None:
        """Test boolean conversion."""
        mock_state = MagicMock(spec=HAState)
        mock_state.state = state
        mock_state.entity_id = "sensor.test"
        val = StateVal(mock_state)
        assert val.as_bool() is expected

    def test_as_datetime_valid(self) -> None:
        """Test datetime conversion with valid input."""
        mock_state = MagicMock(spec=HAState)
        mock_state.state = "2024-01-15T10:30:00"
        mock_state.entity_id = "sensor.test"
        val = StateVal(mock_state)
        result = val.as_datetime()
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_as_datetime_invalid(self) -> None:
        """Test datetime conversion with invalid input."""
        mock_state = MagicMock(spec=HAState)
        mock_state.state = "not a date"
        mock_state.entity_id = "sensor.test"
        val = StateVal(mock_state)
        assert val.as_datetime() is None

    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            ("on", True),
            (STATE_UNAVAILABLE, False),
            (STATE_UNKNOWN, False),
            (None, False),
        ],
    )
    def test_is_available(self, state: str | None, expected: bool) -> None:
        """Test availability check."""
        if state is None:
            val = StateVal(None, "sensor.test")
        else:
            mock_state = MagicMock(spec=HAState)
            mock_state.state = state
            mock_state.entity_id = "sensor.test"
            val = StateVal(mock_state)
        assert val.is_available() is expected


class TestStateManager:
    """Tests for StateManager class."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.bus.async_listen = MagicMock(return_value=MagicMock())
        hass.states.get = MagicMock(return_value=None)
        hass.states.async_all = MagicMock(return_value=[])
        hass.states.async_set = MagicMock()
        return hass

    @pytest.fixture
    def state_manager(self, mock_hass: MagicMock) -> StateManager:
        """Create a StateManager instance."""
        return StateManager(mock_hass)

    async def test_async_setup(self, state_manager: StateManager, mock_hass: MagicMock) -> None:
        """Test async_setup registers listener."""
        await state_manager.async_setup()
        mock_hass.bus.async_listen.assert_called_once()

    async def test_async_teardown(self, state_manager: StateManager) -> None:
        """Test async_teardown unsubscribes and clears queues."""
        await state_manager.async_setup()
        queue = state_manager.subscribe("sensor.test")

        await state_manager.async_teardown()
        # Should receive None to signal shutdown
        msg = queue.get_nowait()
        assert msg is None

    def test_get(self, state_manager: StateManager, mock_hass: MagicMock) -> None:
        """Test getting entity state."""
        mock_state = MagicMock(spec=HAState)
        mock_state.state = "on"
        mock_state.entity_id = "light.test"
        mock_hass.states.get.return_value = mock_state

        result = state_manager.get("light.test")
        assert isinstance(result, StateVal)
        assert result.state == "on"

    def test_get_missing_entity(self, state_manager: StateManager) -> None:
        """Test getting non-existent entity."""
        result = state_manager.get("sensor.nonexistent")
        assert result.state is None
        assert result.entity_id == "sensor.nonexistent"

    def test_get_all(self, state_manager: StateManager, mock_hass: MagicMock) -> None:
        """Test getting all states."""
        mock_state1 = MagicMock(spec=HAState)
        mock_state1.state = "on"
        mock_state1.entity_id = "light.one"
        mock_state2 = MagicMock(spec=HAState)
        mock_state2.state = "off"
        mock_state2.entity_id = "light.two"
        mock_hass.states.async_all.return_value = [mock_state1, mock_state2]

        result = state_manager.get_all()
        assert len(result) == 2
        assert all(isinstance(s, StateVal) for s in result)

    def test_get_all_by_domain(self, state_manager: StateManager, mock_hass: MagicMock) -> None:
        """Test getting states filtered by domain."""
        state_manager.get_all("light")
        mock_hass.states.async_all.assert_called_with("light")

    async def test_async_set(self, state_manager: StateManager, mock_hass: MagicMock) -> None:
        """Test setting entity state."""
        await state_manager.async_set("sensor.test", "42", {"unit": "W"})
        mock_hass.states.async_set.assert_called_once_with(
            "sensor.test",
            "42",
            {"unit": "W"},
            force_update=False,
        )

    async def test_async_set_force_update(self, state_manager: StateManager, mock_hass: MagicMock) -> None:
        """Test setting entity state with force_update."""
        await state_manager.async_set("sensor.test", "42", force_update=True)
        mock_hass.states.async_set.assert_called_once_with(
            "sensor.test",
            "42",
            None,
            force_update=True,
        )

    def test_subscribe_entity(self, state_manager: StateManager) -> None:
        """Test subscribing to specific entity."""
        queue = state_manager.subscribe("sensor.test")
        assert isinstance(queue, asyncio.Queue)
        assert state_manager._subscriptions.has_key("sensor.test")

    def test_subscribe_global(self, state_manager: StateManager) -> None:
        """Test subscribing to all entities."""
        queue = state_manager.subscribe()
        assert isinstance(queue, asyncio.Queue)
        state_manager._subscriptions.deliver_to_all("change")  # type: ignore[arg-type]
        assert queue.get_nowait() == "change"

    def test_unsubscribe_entity(self, state_manager: StateManager) -> None:
        """Test unsubscribing from specific entity."""
        queue = state_manager.subscribe("sensor.test")
        state_manager.unsubscribe(queue, "sensor.test")
        state_manager._subscriptions.deliver("sensor.test", "change")  # type: ignore[arg-type]
        assert queue.empty()

    def test_unsubscribe_global(self, state_manager: StateManager) -> None:
        """Test unsubscribing from global listener."""
        queue = state_manager.subscribe()
        state_manager.unsubscribe(queue)
        state_manager._subscriptions.deliver_to_all("change")  # type: ignore[arg-type]
        assert queue.empty()

    def test_exists_true(self, state_manager: StateManager, mock_hass: MagicMock) -> None:
        """Test exists returns True for existing entity."""
        mock_hass.states.get.return_value = MagicMock(spec=HAState)
        assert state_manager.exists("light.test") is True

    def test_exists_false(self, state_manager: StateManager, mock_hass: MagicMock) -> None:
        """Test exists returns False for missing entity."""
        mock_hass.states.get.return_value = None
        assert state_manager.exists("light.nonexistent") is False


class TestStateConvenienceFunctions:
    """Tests for convenience functions."""

    def test_state_get(self) -> None:
        """Test state_get function."""
        hass = MagicMock()
        mock_state = MagicMock(spec=HAState)
        mock_state.state = "on"
        mock_state.entity_id = "light.test"
        hass.states.get.return_value = mock_state

        result = state_get(hass, "light.test")
        assert isinstance(result, StateVal)
        assert result.state == "on"

    async def test_state_set(self) -> None:
        """Test state_set function."""
        hass = MagicMock()
        await state_set(hass, "sensor.test", "42", {"unit": "W"})
        hass.states.async_set.assert_called_once_with("sensor.test", "42", {"unit": "W"})


class TestStateManagerEdgeCases:
    """Edge case tests for StateManager."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.states = MagicMock()
        hass.bus = MagicMock()
        return hass

    @pytest.fixture
    def state_manager(self, mock_hass: MagicMock) -> StateManager:
        """Create a StateManager instance."""
        return StateManager(mock_hass)

    def test_unsubscribe_nonexistent_entity_queue(self, state_manager: StateManager) -> None:
        """Test unsubscribing a queue that was never subscribed to an entity."""
        queue = asyncio.Queue()
        # This should not raise - just silently return
        state_manager.unsubscribe(queue, "sensor.test")

    def test_unsubscribe_nonexistent_global_queue(self, state_manager: StateManager) -> None:
        """Test unsubscribing a queue that was never subscribed globally."""
        queue = asyncio.Queue()
        # This should not raise - just silently return
        state_manager.unsubscribe(queue)

    def test_unsubscribe_already_removed_entity_queue(self, state_manager: StateManager) -> None:
        """Test unsubscribing an entity queue that was already removed."""
        queue = state_manager.subscribe("sensor.test")
        state_manager.unsubscribe(queue, "sensor.test")
        # Second unsubscribe should not raise
        state_manager.unsubscribe(queue, "sensor.test")

    def test_unsubscribe_already_removed_global_queue(self, state_manager: StateManager) -> None:
        """Test unsubscribing a global queue that was already removed."""
        queue = state_manager.subscribe()
        state_manager.unsubscribe(queue)
        # Second unsubscribe should not raise
        state_manager.unsubscribe(queue)

    def test_get_entity_info_not_found(self, state_manager: StateManager, mock_hass: MagicMock) -> None:
        """Test get_entity_info returns None for non-existent entity."""
        with patch("custom_components.haanim.ha.state.er") as mock_er:
            mock_registry = MagicMock()
            mock_registry.async_get.return_value = None
            mock_er.async_get.return_value = mock_registry

            result = state_manager.get_entity_info("sensor.nonexistent")
            assert result is None

    def test_get_entity_info_found(self, state_manager: StateManager, mock_hass: MagicMock) -> None:
        """Test get_entity_info returns info for existing entity."""
        with patch("custom_components.haanim.ha.state.er") as mock_er:
            mock_entry = MagicMock()
            mock_entry.entity_id = "light.test"
            mock_entry.unique_id = "abc123"
            mock_entry.platform = "hue"
            mock_entry.name = "Test Light"
            mock_entry.original_name = "Original"
            mock_entry.icon = "mdi:lightbulb"
            mock_entry.original_icon = "mdi:lamp"
            mock_entry.device_id = "dev123"
            mock_entry.area_id = "area123"
            mock_entry.disabled_by = None
            mock_entry.hidden_by = None
            mock_entry.capabilities = {"brightness": True}
            mock_entry.device_class = "light"
            mock_entry.supported_features = 7

            mock_registry = MagicMock()
            mock_registry.async_get.return_value = mock_entry
            mock_er.async_get.return_value = mock_registry

            result = state_manager.get_entity_info("light.test")
            assert result is not None
            assert result["entity_id"] == "light.test"
            assert result["unique_id"] == "abc123"
            assert result["platform"] == "hue"
            assert result["name"] == "Test Light"

    async def test_async_teardown_with_subscriptions(self, state_manager: StateManager) -> None:
        """Test teardown stops all subscriptions."""
        # Subscribe to some entities
        q1 = state_manager.subscribe("sensor.test1")
        q2 = state_manager.subscribe("sensor.test2")
        q3 = state_manager.subscribe()  # global

        await state_manager.async_teardown()

        # All listeners should be cleared
        assert not state_manager._subscriptions.has_key("sensor.test1")
        assert not state_manager._subscriptions.has_key("sensor.test2")

    @pytest.mark.parametrize("domain", ["light", "sensor"])
    def test_get_all_domain_filter(
        self,
        state_manager: StateManager,
        mock_hass: MagicMock,
        domain: str,
    ) -> None:
        """Test get_all with domain filter."""
        mock_hass.states.async_all.return_value = []
        state_manager.get_all(domain)
        mock_hass.states.async_all.assert_called_with(domain)

    def test_get_all_no_domain(
        self,
        state_manager: StateManager,
        mock_hass: MagicMock,
    ) -> None:
        """Test get_all without domain filter."""
        mock_hass.states.async_all.return_value = []
        state_manager.get_all()
        mock_hass.states.async_all.assert_called_once_with()
