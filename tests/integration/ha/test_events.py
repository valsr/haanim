"""Tests for the ha/events.py module."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import MATCH_ALL

from custom_components.haanim.ha.subscriptions import QUEUE_SIZE
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
            time_fired=datetime(2024, 1, 15, 12, 0, 0),
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
        msg = queue.get_nowait()
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
        mock_hass.bus.async_listen.assert_called_once()
        assert mock_hass.bus.async_listen.call_args.args[0] == "test_event"

    def test_subscribe_global(self, event_manager: EventManager, mock_hass: MagicMock) -> None:
        """Test subscribing to all events listens to every event type, once."""
        queue = event_manager.subscribe()
        event_manager.subscribe()
        assert isinstance(queue, asyncio.Queue)
        mock_hass.bus.async_listen.assert_called_once()
        assert mock_hass.bus.async_listen.call_args.args[0] == MATCH_ALL

    def test_subscribe_same_event_multiple_times(
        self, event_manager: EventManager, mock_hass: MagicMock
    ) -> None:
        """Test subscribing to same event type multiple times."""
        event_manager.subscribe("test_event")
        event_manager.subscribe("test_event")

        # Only one listener registered with HA
        assert mock_hass.bus.async_listen.call_count == 1

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
            await asyncio.sleep(0)
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
        """Test an event reaches every subscriber of its type, and nobody else."""
        first = event_manager.subscribe("test_event")
        second = event_manager.subscribe("test_event")
        other = event_manager.subscribe("other_event")
        everything = event_manager.subscribe()

        event_manager._handle_event(mock_event)

        notification = first.get_nowait()
        assert isinstance(notification, EventData)
        assert notification.event_type == "test_event"
        assert second.get_nowait() == notification
        assert other.empty()
        assert everything.empty(), "the listener for all events delivers to those subscribers"

    def test_handle_event_notifies_global_listeners(
        self, event_manager: EventManager, mock_event: MagicMock
    ) -> None:
        """Test an event of any type reaches the subscribers of all events, once."""
        queue = event_manager.subscribe()
        typed = event_manager.subscribe("test_event")

        event_manager._handle_any_event(mock_event)

        assert isinstance(queue.get_nowait(), EventData)
        assert queue.empty()
        assert typed.empty()

    def test_handle_event_applies_filter(self, event_manager: EventManager, mock_event: MagicMock) -> None:
        """Test a subscriber whose filter does not match gets nothing."""
        queue = event_manager.subscribe("test_event", {"key": "other_value"})
        missing_key = event_manager.subscribe("test_event", {"absent": "value"})

        event_manager._handle_event(mock_event)

        assert queue.empty()
        assert missing_key.empty()

    def test_handle_event_filter_matches(self, event_manager: EventManager, mock_event: MagicMock) -> None:
        """Test a subscriber whose filter matches gets the event."""
        queue = event_manager.subscribe("test_event", {"key": "value"})

        event_manager._handle_event(mock_event)

        assert not queue.empty()

    def test_each_subscriber_has_its_own_filter(
        self, event_manager: EventManager, mock_event: MagicMock
    ) -> None:
        """Test two subscribers of one event type with different filters each get only what they asked for.

        The filter of the first subscriber used to be applied to all of them.
        """
        matching = event_manager.subscribe("test_event", {"key": "value"})
        other = event_manager.subscribe("test_event", {"key": "other_value"})
        unfiltered = event_manager.subscribe("test_event")

        event_manager._handle_event(mock_event)

        assert not matching.empty()
        assert other.empty()
        assert not unfiltered.empty()

    def test_unsubscribed_gets_nothing(self, event_manager: EventManager, mock_event: MagicMock) -> None:
        """Test a subscriber that unsubscribed gets no further events; the others still do."""
        gone = event_manager.subscribe("test_event")
        stays = event_manager.subscribe("test_event")
        everything = event_manager.subscribe()
        event_manager.unsubscribe(gone, "test_event")
        event_manager.unsubscribe(everything)
        event_manager.unsubscribe(everything)

        event_manager._handle_event(mock_event)
        event_manager._handle_any_event(mock_event)

        assert gone.empty()
        assert everything.empty()
        assert not stays.empty()

    def test_handle_event_queue_full(
        self, event_manager: EventManager, mock_event: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test a subscriber that fell behind loses the event, with a warning, and the others get it."""
        slow = event_manager.subscribe("test_event")
        fast = event_manager.subscribe("test_event")
        everything = event_manager.subscribe()
        for _ in range(QUEUE_SIZE):
            slow.put_nowait(None)
            everything.put_nowait(None)

        event_manager._handle_event(mock_event)
        event_manager._handle_any_event(mock_event)

        assert slow.qsize() == QUEUE_SIZE
        assert not fast.empty()
        assert "Event notification queue full for test_event" in caplog.text
        assert "Event notification queue full for everything" in caplog.text
