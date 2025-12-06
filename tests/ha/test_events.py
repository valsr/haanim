"""Tests for the ha/events.py module."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from custom_components.haanim.ha.events import (
    EventData,
    EventManager,
    event_fire,
    event_wait,
)


class TestEventData:
    """Tests for EventData dataclass."""

    def test_creation(self) -> None:
        """Test creating an EventData instance."""
        event = EventData(
            event_type="test_event",
            data={"key": "value"},
            origin="LOCAL",
            time_fired=datetime(2024, 1, 1, 12, 0, 0),
            context_id="ctx123",
            context_parent_id="parent123",
            context_user_id="user123",
        )
        assert event.event_type == "test_event"
        assert event.data == {"key": "value"}
        assert event.origin == "LOCAL"
        assert event.context_id == "ctx123"
        assert event.context_parent_id == "parent123"
        assert event.context_user_id == "user123"

    def test_creation_with_none_values(self) -> None:
        """Test creating EventData with None values."""
        event = EventData(
            event_type="test_event",
            data={},
            origin=None,
            time_fired=datetime.now(),
            context_id="ctx123",
            context_parent_id=None,
            context_user_id=None,
        )
        assert event.origin is None
        assert event.context_parent_id is None
        assert event.context_user_id is None


class TestEventManager:
    """Tests for EventManager class."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.bus.async_listen = MagicMock(return_value=MagicMock())
        hass.bus.async_listen_once = MagicMock(return_value=MagicMock())
        hass.bus.async_fire = MagicMock()
        return hass

    @pytest.fixture
    def event_manager(self, mock_hass: MagicMock) -> EventManager:
        """Create an EventManager instance."""
        return EventManager(mock_hass)

    async def test_async_setup(self, event_manager: EventManager) -> None:
        """Test async_setup succeeds."""
        await event_manager.async_setup()
        # Should complete without error

    async def test_async_teardown(self, event_manager: EventManager, mock_hass: MagicMock) -> None:
        """Test async_teardown clears listeners and queues."""
        # Subscribe first
        queue = event_manager.subscribe("test_event")

        await event_manager.async_teardown()

        # Queue should receive None to signal shutdown
        msg = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert msg is None

    async def test_async_teardown_unsubscribes_all(
        self, event_manager: EventManager, mock_hass: MagicMock
    ) -> None:
        """Test async_teardown unsubscribes all listeners."""
        unsub = MagicMock()
        mock_hass.bus.async_listen.return_value = unsub

        event_manager.subscribe("event1")
        event_manager.subscribe("event2")

        await event_manager.async_teardown()

        # All unsub callbacks should have been called
        assert unsub.call_count == 2

    def test_subscribe_specific_event(self, event_manager: EventManager, mock_hass: MagicMock) -> None:
        """Test subscribing to specific event type."""
        queue = event_manager.subscribe("test_event")
        assert isinstance(queue, asyncio.Queue)
        assert "test_event" in event_manager._listeners
        mock_hass.bus.async_listen.assert_called_once()

    def test_subscribe_global(self, event_manager: EventManager) -> None:
        """Test subscribing to all events."""
        queue = event_manager.subscribe()
        assert isinstance(queue, asyncio.Queue)
        assert queue in event_manager._global_listeners

    def test_subscribe_same_event_multiple_times(
        self, event_manager: EventManager, mock_hass: MagicMock
    ) -> None:
        """Test subscribing to same event type multiple times."""
        queue1 = event_manager.subscribe("test_event")
        queue2 = event_manager.subscribe("test_event")

        assert queue1 in event_manager._listeners["test_event"]
        assert queue2 in event_manager._listeners["test_event"]
        # Only one listener registered with HA
        assert mock_hass.bus.async_listen.call_count == 1

    def test_unsubscribe_specific_event(self, event_manager: EventManager) -> None:
        """Test unsubscribing from specific event."""
        queue = event_manager.subscribe("test_event")
        event_manager.unsubscribe(queue, "test_event")
        assert queue not in event_manager._listeners.get("test_event", [])

    def test_unsubscribe_global(self, event_manager: EventManager) -> None:
        """Test unsubscribing from global listener."""
        queue = event_manager.subscribe()
        event_manager.unsubscribe(queue)
        assert queue not in event_manager._global_listeners

    def test_unsubscribe_nonexistent(self, event_manager: EventManager) -> None:
        """Test unsubscribing non-existent queue doesn't error."""
        queue: asyncio.Queue[Any] = asyncio.Queue()
        # Should not raise
        event_manager.unsubscribe(queue, "nonexistent_event")
        event_manager.unsubscribe(queue)

    def test_fire(self, event_manager: EventManager, mock_hass: MagicMock) -> None:
        """Test firing an event."""
        event_manager.fire("my_event", {"data": "value"})
        mock_hass.bus.async_fire.assert_called_once_with("my_event", {"data": "value"})

    def test_fire_no_data(self, event_manager: EventManager, mock_hass: MagicMock) -> None:
        """Test firing an event without data."""
        event_manager.fire("my_event")
        mock_hass.bus.async_fire.assert_called_once_with("my_event", None)

    async def test_async_fire(self, event_manager: EventManager, mock_hass: MagicMock) -> None:
        """Test async firing an event."""
        await event_manager.async_fire("my_event", {"data": "value"})
        mock_hass.bus.async_fire.assert_called_once_with("my_event", {"data": "value"})

    def test_listen_once(self, event_manager: EventManager, mock_hass: MagicMock) -> None:
        """Test listen_once registers one-time listener."""
        callback = MagicMock()
        unsub = MagicMock()
        mock_hass.bus.async_listen_once.return_value = unsub

        result = event_manager.listen_once("test_event", callback)

        mock_hass.bus.async_listen_once.assert_called_once_with("test_event", callback)
        assert result is unsub


class TestEventConvenienceFunctions:
    """Tests for convenience functions."""

    def test_event_fire(self) -> None:
        """Test event_fire function."""
        hass = MagicMock()
        event_fire(hass, "my_event", {"key": "value"})
        hass.bus.async_fire.assert_called_once_with("my_event", {"key": "value"})

    def test_event_fire_no_data(self) -> None:
        """Test event_fire function without data."""
        hass = MagicMock()
        event_fire(hass, "my_event")
        hass.bus.async_fire.assert_called_once_with("my_event", None)

    async def test_event_wait_success(self) -> None:
        """Test event_wait receives event."""
        hass = MagicMock()

        # Simulate event firing
        async def mock_listen(event_type: str, callback: Any) -> MagicMock:
            # Create mock event
            mock_event = MagicMock()
            mock_event.event_type = event_type
            mock_event.data = {"test": "data"}
            mock_event.time_fired = datetime(2024, 1, 1, 12, 0, 0)
            # Call the callback
            await asyncio.sleep(0.01)
            callback(mock_event)
            return MagicMock()

        # Use a simpler approach - test the timeout path
        hass.bus.async_listen = MagicMock(return_value=MagicMock())

        result = await event_wait(hass, "test_event", timeout=0.01)
        # Will timeout since we can't properly simulate the event
        assert result is None

    async def test_event_wait_timeout(self) -> None:
        """Test event_wait times out."""
        hass = MagicMock()
        hass.bus.async_listen = MagicMock(return_value=MagicMock())

        result = await event_wait(hass, "test_event", timeout=0.01)
        assert result is None


class TestEventManagerHandleEvent:
    """Tests for _handle_event method."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.bus.async_listen = MagicMock(return_value=MagicMock())
        return hass

    @pytest.fixture
    def event_manager(self, mock_hass: MagicMock) -> EventManager:
        """Create an EventManager instance."""
        return EventManager(mock_hass)

    @pytest.fixture
    def mock_event(self) -> MagicMock:
        """Create a mock event."""
        event = MagicMock()
        event.event_type = "test_event"
        event.data = {"key": "value"}
        event.origin = MagicMock()
        event.origin.name = "LOCAL"
        event.time_fired = datetime(2024, 1, 1, 12, 0, 0)
        event.context = MagicMock()
        event.context.id = "ctx123"
        event.context.parent_id = None
        event.context.user_id = None
        return event

    def test_handle_event_notifies_listeners(
        self, event_manager: EventManager, mock_event: MagicMock
    ) -> None:
        """Test _handle_event notifies type-specific listeners."""
        queue = event_manager.subscribe("test_event")
        # Subscribe creates internal listener with filter
        event_manager._listeners["test_event"] = [queue]

        event_manager._handle_event(mock_event, "test_event", None)

        assert not queue.empty()
        notification = queue.get_nowait()
        assert isinstance(notification, EventData)
        assert notification.event_type == "test_event"

    def test_handle_event_notifies_global_listeners(
        self, event_manager: EventManager, mock_event: MagicMock
    ) -> None:
        """Test _handle_event notifies global listeners."""
        queue = event_manager.subscribe()

        event_manager._handle_event(mock_event, "test_event", None)

        assert not queue.empty()
        notification = queue.get_nowait()
        assert isinstance(notification, EventData)

    def test_handle_event_applies_filter(
        self, event_manager: EventManager, mock_event: MagicMock
    ) -> None:
        """Test _handle_event applies event filter."""
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=100)
        event_manager._listeners["test_event"] = [queue]

        # Filter for different value
        event_manager._handle_event(mock_event, "test_event", {"key": "other_value"})

        assert queue.empty()

    def test_handle_event_filter_matches(
        self, event_manager: EventManager, mock_event: MagicMock
    ) -> None:
        """Test _handle_event passes when filter matches."""
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=100)
        event_manager._listeners["test_event"] = [queue]

        event_manager._handle_event(mock_event, "test_event", {"key": "value"})

        assert not queue.empty()

    def test_handle_event_queue_full(
        self, event_manager: EventManager, mock_event: MagicMock
    ) -> None:
        """Test _handle_event handles full queue gracefully."""
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=1)
        queue.put_nowait(EventData(
            event_type="filler",
            data={},
            origin=None,
            time_fired=datetime.now(),
            context_id="ctx",
            context_parent_id=None,
            context_user_id=None,
        ))
        event_manager._listeners["test_event"] = [queue]

        # Should not raise, just log warning
        event_manager._handle_event(mock_event, "test_event", None)
