"""Tests for the in-memory host implementations in haanim.testing."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.errors import ActionNotFoundError, NonExistingAutomationError, ServiceCallError
from haanim.interfaces import Host
from haanim.testing import (
    FakeAutomationRegistry,
    FakeClock,
    FakeEventBus,
    FakeFileSystem,
    FakeIssueReporter,
    FakeServiceCaller,
    FakeStateProvider,
    FakeStorage,
    FakeSunProvider,
    LocalFileSystem,
    ServiceCallRecord,
    make_host,
)
from haanim.testing.fakes import DEFAULT_NOW
from tests.engine.helpers import automation_file, load_and_run, make_context

UTC = timezone.utc


class TestFakeClock:
    """Tests for FakeClock."""

    def test_default_start(self) -> None:
        """Test the clock starts at the documented default, timezone-aware."""
        clock = FakeClock()
        assert clock.now() == DEFAULT_NOW
        assert clock.now().tzinfo is not None

    def test_custom_start(self) -> None:
        """Test the clock starts at the given time."""
        start = datetime(2030, 5, 1, 8, 0, tzinfo=UTC)
        assert FakeClock(start).now() == start

    def test_does_not_move_on_its_own(self) -> None:
        """Test two reads give the same time."""
        clock = FakeClock()
        assert clock.now() == clock.now()

    def test_naive_datetime_rejected(self) -> None:
        """Test a datetime without a time zone is rejected by the constructor and by call_at."""
        with pytest.raises(ValueError, match="timezone-aware"):
            FakeClock(datetime(2025, 1, 1))
        with pytest.raises(ValueError, match="timezone-aware"):
            FakeClock().call_at(datetime(2025, 1, 1), lambda: None)

    @pytest.mark.parametrize(
        ("delta", "kwargs", "expected"),
        [
            (timedelta(minutes=5), {}, timedelta(minutes=5)),
            (None, {"hours": 2}, timedelta(hours=2)),
            (timedelta(minutes=1), {"seconds": 30}, timedelta(seconds=90)),
            (None, {}, timedelta()),
        ],
    )
    async def test_advance(
        self, delta: timedelta | None, kwargs: dict[str, float], expected: timedelta
    ) -> None:
        """Test advance moves forward by a timedelta, keyword arguments, or both."""
        clock = FakeClock()
        assert await clock.advance(delta, **kwargs) == DEFAULT_NOW + expected
        assert clock.now() == DEFAULT_NOW + expected

    async def test_advance_backwards_rejected(self) -> None:
        """Test the clock refuses to move backwards and stays where it was."""
        clock = FakeClock()
        with pytest.raises(ValueError, match="backwards"):
            await clock.advance(seconds=-1)
        assert clock.now() == DEFAULT_NOW


class TestFakeClockTimers:
    """Tests for call_later and call_at on FakeClock."""

    async def test_call_later_runs_only_when_due(self) -> None:
        """Test a callback runs once the clock reaches its time, not before, and only once."""
        clock = FakeClock()
        calls: list[datetime] = []
        clock.call_later(10, lambda: calls.append(clock.now()))

        await clock.advance(seconds=9)
        assert calls == []
        assert clock.pending_timers == 1

        await clock.advance(seconds=1)
        assert calls == [DEFAULT_NOW + timedelta(seconds=10)]
        assert clock.pending_timers == 0

        await clock.advance(seconds=60)
        assert len(calls) == 1

    async def test_callback_sees_its_own_time(self) -> None:
        """Test now() inside a callback is the callback's time, not the end of the advance."""
        clock = FakeClock()
        seen: list[datetime] = []
        clock.call_later(10, lambda: seen.append(clock.now()))
        await clock.advance(minutes=5)
        assert seen == [DEFAULT_NOW + timedelta(seconds=10)]
        assert clock.now() == DEFAULT_NOW + timedelta(minutes=5)

    async def test_timers_run_in_time_order(self) -> None:
        """Test timers run earliest first, whatever order they were scheduled in."""
        clock = FakeClock()
        order: list[str] = []
        clock.call_later(30, lambda: order.append("third"))
        clock.call_later(10, lambda: order.append("first"))
        clock.call_later(20, lambda: order.append("second"))
        await clock.advance(minutes=1)
        assert order == ["first", "second", "third"]

    async def test_equal_times_run_in_scheduling_order(self) -> None:
        """Test timers due at the same instant run in the order they were scheduled."""
        clock = FakeClock()
        order: list[int] = []
        for number in range(5):
            clock.call_later(10, lambda number=number: order.append(number))
        await clock.advance(seconds=10)
        assert order == [0, 1, 2, 3, 4]

    async def test_cancel(self) -> None:
        """Test a cancelled timer never runs, and cancelling again or afterwards is harmless."""
        clock = FakeClock()
        calls: list[str] = []
        handle = clock.call_later(10, lambda: calls.append("cancelled"))
        kept = clock.call_later(10, lambda: calls.append("kept"))

        handle.cancel()
        handle.cancel()
        assert clock.pending_timers == 1

        await clock.advance(seconds=10)
        kept.cancel()
        assert calls == ["kept"]

    async def test_timer_scheduled_by_a_timer_runs_in_the_same_advance(self) -> None:
        """Test a callback that schedules another timer inside the advanced span sees it run too."""
        clock = FakeClock()
        calls: list[datetime] = []

        def first() -> None:
            calls.append(clock.now())
            clock.call_later(10, lambda: calls.append(clock.now()))

        clock.call_later(10, first)
        await clock.advance(seconds=30)
        assert calls == [DEFAULT_NOW + timedelta(seconds=10), DEFAULT_NOW + timedelta(seconds=20)]

    async def test_call_at(self) -> None:
        """Test call_at runs the callback when the clock reaches the given time."""
        clock = FakeClock()
        calls: list[datetime] = []
        clock.call_at(DEFAULT_NOW + timedelta(hours=1), lambda: calls.append(clock.now()))
        await clock.advance(minutes=59)
        assert calls == []
        await clock.advance(minutes=1)
        assert calls == [DEFAULT_NOW + timedelta(hours=1)]

    @pytest.mark.parametrize("schedule", ["call_at_past", "call_later_zero", "call_later_negative"])
    async def test_not_in_the_future_runs_as_soon_as_possible(self, schedule: str) -> None:
        """Test a timer that is not in the future runs at the next advance without moving time."""
        clock = FakeClock()
        calls: list[datetime] = []

        def record() -> None:
            calls.append(clock.now())

        if schedule == "call_at_past":
            clock.call_at(DEFAULT_NOW - timedelta(hours=1), record)
        elif schedule == "call_later_zero":
            clock.call_later(0, record)
        else:
            clock.call_later(-5, record)

        assert calls == []
        await clock.advance()
        assert calls == [DEFAULT_NOW]


class TestFakeClockSleep:
    """Tests for sleep on FakeClock."""

    async def test_sleep_waits_for_advance(self) -> None:
        """Test a sleeping task resumes when the clock has advanced far enough, not before."""
        clock = FakeClock()
        woke: list[datetime] = []

        async def sleeper() -> None:
            await clock.sleep(60)
            woke.append(clock.now())

        task = asyncio.create_task(sleeper())
        await clock.advance(seconds=59)
        assert woke == []
        await clock.advance(seconds=1)
        assert woke == [DEFAULT_NOW + timedelta(seconds=60)]
        await task

    @pytest.mark.parametrize("seconds", [0, -1])
    async def test_sleep_zero_returns_without_advance(self, seconds: float) -> None:
        """Test a sleep of zero or less only yields; it needs no advance and leaves no timer."""
        clock = FakeClock()
        await clock.sleep(seconds)
        assert clock.now() == DEFAULT_NOW
        assert clock.pending_timers == 0

    async def test_repeated_sleeps_inside_one_advance(self) -> None:
        """Test a loop that sleeps repeatedly runs every iteration that falls inside one advance."""
        clock = FakeClock()
        ticks: list[datetime] = []

        async def interval() -> None:
            while True:
                await clock.sleep(10)
                ticks.append(clock.now())

        task = asyncio.create_task(interval())
        await clock.advance(seconds=35)
        task.cancel()

        assert ticks == [DEFAULT_NOW + timedelta(seconds=seconds) for seconds in (10, 20, 30)]

    async def test_cancelled_sleep_leaves_no_timer(self) -> None:
        """Test cancelling a sleeping task removes its timer."""
        clock = FakeClock()
        task = asyncio.create_task(clock.sleep(60))
        await clock.settle()
        assert clock.pending_timers == 1

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert clock.pending_timers == 0

    async def test_sleepers_wake_in_order(self) -> None:
        """Test several sleeping tasks wake in order of their wake-up time."""
        clock = FakeClock()
        order: list[str] = []

        async def sleeper(name: str, seconds: float) -> None:
            await clock.sleep(seconds)
            order.append(name)

        tasks = [
            asyncio.create_task(sleeper("slow", 30)),
            asyncio.create_task(sleeper("fast", 10)),
            asyncio.create_task(sleeper("medium", 20)),
        ]
        await clock.advance(minutes=1)
        await asyncio.gather(*tasks)
        assert order == ["fast", "medium", "slow"]


class TestFakeClockWaitFor:
    """Tests for wait_for on FakeClock."""

    async def test_returns_result_when_finished_in_time(self) -> None:
        """Test the awaitable's result is returned and no timer is left behind."""
        clock = FakeClock()

        async def work() -> str:
            await clock.sleep(5)
            return "done"

        waiter = asyncio.create_task(clock.wait_for(work(), 10))
        await clock.advance(seconds=5)
        assert await waiter == "done"
        assert clock.pending_timers == 0

    async def test_result_without_any_advance(self) -> None:
        """Test an awaitable that finishes without waiting on the clock needs no advance."""
        clock = FakeClock()

        async def work() -> int:
            return 7

        assert await clock.wait_for(work(), 10) == 7

    async def test_timeout_cancels_and_raises(self) -> None:
        """Test passing the timeout raises TimeoutError and cancels the awaitable."""
        clock = FakeClock()
        cancelled: list[bool] = []

        async def work() -> None:
            try:
                await clock.sleep(100)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        waiter = asyncio.create_task(clock.wait_for(work(), 10))
        await clock.advance(seconds=10)

        with pytest.raises(TimeoutError):
            await waiter
        assert cancelled == [True]
        assert clock.pending_timers == 0

    async def test_exception_propagates(self) -> None:
        """Test an exception from the awaitable reaches the caller unchanged."""
        clock = FakeClock()

        async def work() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await clock.wait_for(work(), 10)

    @pytest.mark.parametrize("timeout", [0, -1])
    async def test_zero_timeout_gives_up_at_once(self, timeout: float) -> None:
        """Test a timeout of zero or less raises without any advance when the awaitable is not finished."""
        clock = FakeClock()
        with pytest.raises(TimeoutError):
            await clock.wait_for(clock.sleep(5), timeout)
        assert clock.pending_timers == 0

    async def test_zero_timeout_returns_finished_awaitable(self) -> None:
        """Test a timeout of zero still returns the result of an awaitable that finishes at once."""
        clock = FakeClock()

        async def work() -> int:
            return 7

        assert await clock.wait_for(work(), 0) == 7

    async def test_cancelling_the_waiter_cancels_the_awaitable(self) -> None:
        """Test cancelling the task that is waiting also cancels what it waits for."""
        clock = FakeClock()
        cancelled: list[bool] = []

        async def work() -> None:
            try:
                await clock.sleep(100)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        waiter = asyncio.create_task(clock.wait_for(work(), 50))
        await clock.settle()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert cancelled == [True]
        assert clock.pending_timers == 0

    async def test_awaitable_that_fails_while_being_cancelled(self) -> None:
        """Test a timeout is still reported when the awaitable raises during cancellation."""
        clock = FakeClock()

        async def work() -> None:
            try:
                await clock.sleep(100)
            except asyncio.CancelledError:
                raise RuntimeError("cleanup failed") from None

        waiter = asyncio.create_task(clock.wait_for(work(), 10))
        await clock.advance(seconds=10)
        with pytest.raises(TimeoutError):
            await waiter


class TestFakeStateProvider:
    """Tests for FakeStateProvider."""

    def test_missing_entity(self) -> None:
        """Test a missing entity does not exist and has no state."""
        states = FakeStateProvider()
        assert states.exists("sensor.temp") is False
        value = states.get("sensor.temp")
        assert value.state is None
        assert value.entity_id == "sensor.temp"
        assert value.attributes == {}

    def test_set_and_get(self) -> None:
        """Test a set state is returned with its attributes."""
        states = FakeStateProvider()
        states.set_state("sensor.temp", "21.5", {"unit": "C"})
        assert states.exists("sensor.temp") is True
        value = states.get("sensor.temp")
        assert value.state == "21.5"
        assert value.attributes == {"unit": "C"}
        assert value.get("unit") == "C"

    def test_attributes_are_replaced(self) -> None:
        """Test a later set_state replaces the attributes rather than merging."""
        states = FakeStateProvider()
        states.set_state("light.hall", "on", {"brightness": 200})
        states.set_state("light.hall", "on")
        assert states.get("light.hall").attributes == {}

    async def test_timestamps(self) -> None:
        """Test last_changed moves only when the value changes; last_updated always moves."""
        clock = FakeClock()
        states = FakeStateProvider(clock)
        states.set_state("sensor.temp", "20")
        first = clock.now()

        await clock.advance(minutes=1)
        states.set_state("sensor.temp", "20", {"unit": "C"})
        value = states.get("sensor.temp")
        assert value.last_changed == first
        assert value.last_updated == first + timedelta(minutes=1)

        await clock.advance(minutes=1)
        states.set_state("sensor.temp", "21")
        assert states.get("sensor.temp").last_changed == first + timedelta(minutes=2)

    def test_subscriber_receives_change(self) -> None:
        """Test an entity subscriber gets the old and new state."""
        states = FakeStateProvider()
        states.set_state("sensor.temp", "20")
        queue = states.subscribe("sensor.temp")

        states.set_state("sensor.temp", "21")

        event = queue.get_nowait()
        assert event is not None
        assert event.entity_id == "sensor.temp"
        assert event.old_state is not None and event.old_state.state == "20"
        assert event.new_state.state == "21"
        assert queue.empty()

    def test_first_state_has_no_old_state(self) -> None:
        """Test the change that creates an entity has old_state None."""
        states = FakeStateProvider()
        queue = states.subscribe("sensor.temp")
        states.set_state("sensor.temp", "20")
        event = queue.get_nowait()
        assert event is not None and event.old_state is None

    def test_entity_subscriber_ignores_other_entities(self) -> None:
        """Test a subscription to one entity is not notified about another."""
        states = FakeStateProvider()
        queue = states.subscribe("sensor.temp")
        states.set_state("sensor.other", "1")
        assert queue.empty()

    def test_global_subscriber_receives_everything(self) -> None:
        """Test a subscription without an entity ID gets every change."""
        states = FakeStateProvider()
        queue = states.subscribe()
        states.set_state("sensor.a", "1")
        states.set_state("sensor.b", "2")
        assert [queue.get_nowait().entity_id for _ in range(2)] == ["sensor.a", "sensor.b"]  # type: ignore[union-attr]

    @pytest.mark.parametrize("entity_id", ["sensor.temp", None])
    def test_unsubscribe(self, entity_id: str | None) -> None:
        """Test unsubscribing stops notifications and updates the subscriber count."""
        states = FakeStateProvider()
        queue = states.subscribe(entity_id)
        assert states.subscriber_count(entity_id) == 1

        states.unsubscribe(queue, entity_id)
        states.set_state("sensor.temp", "20")

        assert queue.empty()
        assert states.subscriber_count(entity_id) == 0

    def test_unsubscribe_unknown_queue_is_ignored(self) -> None:
        """Test unsubscribing a queue that is not subscribed does nothing."""
        states = FakeStateProvider()
        other = FakeStateProvider().subscribe("sensor.temp")
        states.unsubscribe(other, "sensor.temp")
        states.unsubscribe(other)

    def test_remove(self) -> None:
        """Test remove deletes an entity silently and tolerates a missing one."""
        states = FakeStateProvider()
        states.set_state("sensor.temp", "20")
        queue = states.subscribe("sensor.temp")
        states.remove("sensor.temp")
        states.remove("sensor.temp")
        assert states.exists("sensor.temp") is False
        assert queue.empty()


class TestFakeEventBus:
    """Tests for FakeEventBus."""

    def test_fire_records_event(self) -> None:
        """Test fired events are recorded with their data and the clock's time."""
        clock = FakeClock()
        bus = FakeEventBus(clock)
        bus.fire("my_event", {"key": "value"})
        bus.fire("other_event")

        assert bus.fired_types() == ["my_event", "other_event"]
        first = bus.fired[0]
        assert first.data == {"key": "value"}
        assert first.time_fired == clock.now()
        assert bus.fired[1].data == {}
        assert first.context_id != bus.fired[1].context_id

    def test_subscriber_receives_matching_type_only(self) -> None:
        """Test a typed subscription gets its own event type and no other."""
        bus = FakeEventBus()
        queue = bus.subscribe("my_event")
        bus.fire("other_event")
        bus.fire("my_event", {"n": 1})
        event = queue.get_nowait()
        assert event is not None and event.event_type == "my_event" and event.data == {"n": 1}
        assert queue.empty()

    @pytest.mark.parametrize(
        ("event_filter", "data", "delivered"),
        [
            ({"command": "toggle"}, {"command": "toggle"}, True),
            ({"command": "toggle"}, {"command": "toggle", "extra": 1}, True),
            ({"command": "toggle"}, {"command": "on"}, False),
            ({"command": "toggle"}, {}, False),
            ({"a": 1, "b": 2}, {"a": 1, "b": 2}, True),
            ({"a": 1, "b": 2}, {"a": 1, "b": 3}, False),
            ({"nested": {"x": [1, 2]}}, {"nested": {"x": [1, 2]}}, True),
            ({"nested": {"x": [1, 2]}}, {"nested": {"x": [1]}}, False),
            ({}, {"anything": True}, True),
            (None, {"anything": True}, True),
        ],
    )
    def test_filter(self, event_filter: dict[str, Any] | None, data: dict[str, Any], delivered: bool) -> None:
        """Test a filter delivers only events containing every listed key with an equal value."""
        bus = FakeEventBus()
        queue = bus.subscribe("my_event", event_filter)
        bus.fire("my_event", data)
        assert queue.empty() is not delivered

    def test_global_subscriber_receives_everything(self) -> None:
        """Test a subscription without an event type gets every event."""
        bus = FakeEventBus()
        queue = bus.subscribe()
        bus.fire("a")
        bus.fire("b")
        assert [queue.get_nowait().event_type for _ in range(2)] == ["a", "b"]  # type: ignore[union-attr]

    @pytest.mark.parametrize("event_type", ["my_event", None])
    def test_unsubscribe(self, event_type: str | None) -> None:
        """Test unsubscribing stops delivery, and unsubscribing twice is harmless."""
        bus = FakeEventBus()
        queue = bus.subscribe(event_type)
        bus.unsubscribe(queue, event_type)
        bus.unsubscribe(queue, event_type)
        bus.fire("my_event")
        assert queue.empty()

    def test_listen_once_sync_callback(self) -> None:
        """Test a one-time listener is called for the first matching event only."""
        bus = FakeEventBus()
        received: list[str] = []
        bus.listen_once("started", lambda event: received.append(event.event_type))
        bus.fire("other")
        bus.fire("started")
        bus.fire("started")
        assert received == ["started"]

    async def test_listen_once_async_callback(self) -> None:
        """Test a coroutine callback is scheduled and runs."""
        bus = FakeEventBus()
        received: list[str] = []

        async def on_started(event: Any) -> None:
            received.append(event.event_type)

        bus.listen_once("started", on_started)
        bus.fire("started")
        assert received == []
        await asyncio_yield()
        assert received == ["started"]

    def test_listen_once_cancel(self) -> None:
        """Test the returned function cancels the listener, and can be called twice."""
        bus = FakeEventBus()
        received: list[str] = []
        cancel = bus.listen_once("started", lambda event: received.append(event.event_type))
        cancel()
        cancel()
        bus.fire("started")
        assert received == []


async def asyncio_yield() -> None:
    """Let scheduled callbacks and tasks run once."""
    await asyncio.sleep(0)


class TestFakeServiceCaller:
    """Tests for FakeServiceCaller."""

    def test_no_services_by_default(self) -> None:
        """Test a new caller has no services."""
        services = FakeServiceCaller()
        assert services.has_service("light", "turn_on") is False
        assert services.services() == []

    def test_register_and_describe(self) -> None:
        """Test a registered service is listed with its description and fields."""
        services = FakeServiceCaller()
        services.register(
            "light", "turn_on", description="Turn on", fields={"brightness": {"required": False}}
        )
        assert services.has_service("light", "turn_on") is True
        (info,) = services.services()
        assert (info.domain, info.name, info.description) == ("light", "turn_on", "Turn on")
        assert info.fields == {"brightness": {"required": False}}

    async def test_call_is_recorded(self) -> None:
        """Test a call is recorded with its data and returns None when no response is requested."""
        services = FakeServiceCaller()
        services.register("light", "turn_on", response={"ok": True})

        result = await services.async_call("light", "turn_on", {"entity_id": "light.hall"})

        assert result is None
        assert services.calls == [ServiceCallRecord("light", "turn_on", {"entity_id": "light.hall"}, False)]
        assert services.calls_to("light", "turn_on") == services.calls
        assert services.calls_to("light", "turn_off") == []

    @pytest.mark.parametrize(("response", "expected"), [({"ok": True}, {"ok": True}), (None, None)])
    async def test_call_returns_response_when_requested(
        self, response: dict[str, Any] | None, expected: dict[str, Any] | None
    ) -> None:
        """Test the stubbed response is returned when the caller asks for it."""
        services = FakeServiceCaller()
        services.register("weather", "get_forecast", response=response)
        assert await services.async_call("weather", "get_forecast", return_response=True) == expected

    async def test_call_data_is_copied(self) -> None:
        """Test later changes to the caller's dictionary do not alter the record."""
        services = FakeServiceCaller()
        services.register("light", "turn_on")
        data = {"entity_id": "light.hall"}
        await services.async_call("light", "turn_on", data)
        data["entity_id"] = "light.other"
        assert services.calls[0].data == {"entity_id": "light.hall"}

    async def test_missing_service_raises_and_is_recorded(self) -> None:
        """Test calling an unregistered service raises ServiceCallError and still records the call."""
        services = FakeServiceCaller()
        with pytest.raises(ServiceCallError, match="service not found") as exc_info:
            await services.async_call("light", "turn_on")
        assert (exc_info.value.domain, exc_info.value.service) == ("light", "turn_on")
        assert len(services.calls) == 1

    async def test_fail(self) -> None:
        """Test a service set to fail raises with the given reason."""
        services = FakeServiceCaller()
        services.register("light", "turn_on")
        services.fail("light", "turn_on", "device offline")
        with pytest.raises(ServiceCallError) as exc_info:
            await services.async_call("light", "turn_on")
        assert exc_info.value.reason == "device offline"

    async def test_register_again_clears_failure(self) -> None:
        """Test re-registering a service makes it succeed again."""
        services = FakeServiceCaller()
        services.register("light", "turn_on")
        services.fail("light", "turn_on")
        services.register("light", "turn_on")
        assert await services.async_call("light", "turn_on") is None

    def test_fail_unregistered_service(self) -> None:
        """Test failing a service that is not registered is a test error."""
        with pytest.raises(KeyError):
            FakeServiceCaller().fail("light", "turn_on")


class TestFakeSunProvider:
    """Tests for FakeSunProvider."""

    @pytest.mark.parametrize(
        ("event", "after", "expected"),
        [
            ("sunrise", datetime(2025, 1, 6, 5, 0, tzinfo=UTC), datetime(2025, 1, 6, 7, 0, tzinfo=UTC)),
            ("sunrise", datetime(2025, 1, 6, 7, 0, tzinfo=UTC), datetime(2025, 1, 7, 7, 0, tzinfo=UTC)),
            ("sunrise", datetime(2025, 1, 6, 12, 0, tzinfo=UTC), datetime(2025, 1, 7, 7, 0, tzinfo=UTC)),
            ("sunset", datetime(2025, 1, 6, 12, 0, tzinfo=UTC), datetime(2025, 1, 6, 19, 0, tzinfo=UTC)),
            ("sunset", datetime(2025, 1, 6, 19, 0, 1, tzinfo=UTC), datetime(2025, 1, 7, 19, 0, tzinfo=UTC)),
        ],
    )
    def test_next_event(self, event: str, after: datetime, expected: datetime) -> None:
        """Test the next event is strictly after the given time, rolling over to the next day."""
        assert FakeSunProvider().next_event(event, after) == expected

    def test_custom_times(self) -> None:
        """Test configured sunrise and sunset times are used."""
        sun = FakeSunProvider(sunrise="05:30", sunset="21:15")
        after = datetime(2025, 6, 1, 0, 0, tzinfo=UTC)
        assert sun.next_event("sunrise", after) == datetime(2025, 6, 1, 5, 30, tzinfo=UTC)
        assert sun.next_event("sunset", after) == datetime(2025, 6, 1, 21, 15, tzinfo=UTC)

    def test_result_keeps_time_zone(self) -> None:
        """Test the result is in the time zone of the given time."""
        zone = timezone(timedelta(hours=-5))
        result = FakeSunProvider().next_event("sunrise", datetime(2025, 1, 6, 5, 0, tzinfo=zone))
        assert result is not None and result.tzinfo is zone

    @pytest.mark.parametrize("event", ["sunrise", "sunset"])
    def test_no_event(self, event: str) -> None:
        """Test a provider configured without an event returns None for it."""
        sun = FakeSunProvider(sunrise=None, sunset=None)
        assert sun.next_event(event, DEFAULT_NOW) is None

    def test_unknown_event(self) -> None:
        """Test an event other than sunrise or sunset is rejected."""
        with pytest.raises(ValueError, match="Unknown sun event"):
            FakeSunProvider().next_event("noon", DEFAULT_NOW)


class TestFakeFileSystem:
    """Tests for FakeFileSystem."""

    async def test_write_and_read(self) -> None:
        """Test a written file exists, can be read, and is stamped with the clock's time."""
        clock = FakeClock()
        files = FakeFileSystem(clock)
        files.write("/automations/a/main.py", "x = 1")
        path = Path("/automations/a/main.py")
        assert files.exists(path) is True
        assert await files.read_text(path) == "x = 1"
        assert files.modified_time(path) == clock.now()

    async def test_rewrite_updates_modified_time(self) -> None:
        """Test writing again moves the modification time."""
        clock = FakeClock()
        files = FakeFileSystem(clock)
        files.write("/a.py", "1")
        await clock.advance(seconds=10)
        files.write("/a.py", "2")
        assert files.modified_time(Path("/a.py")) == DEFAULT_NOW + timedelta(seconds=10)

    async def test_missing_file(self) -> None:
        """Test a missing file does not exist and cannot be read or inspected."""
        files = FakeFileSystem()
        path = Path("/missing.py")
        assert files.exists(path) is False
        with pytest.raises(FileNotFoundError):
            await files.read_text(path)
        with pytest.raises(FileNotFoundError):
            files.modified_time(path)

    async def test_delete(self) -> None:
        """Test delete removes a file and tolerates a missing one."""
        files = FakeFileSystem()
        files.write("/a.py", "1")
        files.delete("/a.py")
        files.delete("/a.py")
        assert files.exists(Path("/a.py")) is False

    async def test_unreadable(self) -> None:
        """Test an unreadable file exists but raises PermissionError when read."""
        files = FakeFileSystem()
        files.write("/a.py", "1")
        files.make_unreadable("/a.py")
        assert files.exists(Path("/a.py")) is True
        with pytest.raises(PermissionError):
            await files.read_text(Path("/a.py"))

    async def test_delete_clears_unreadable(self) -> None:
        """Test a file written again after deletion is readable."""
        files = FakeFileSystem()
        files.write("/a.py", "1")
        files.make_unreadable("/a.py")
        files.delete("/a.py")
        files.write("/a.py", "2")
        assert await files.read_text(Path("/a.py")) == "2"


class TestLocalFileSystem:
    """Tests for LocalFileSystem."""

    async def test_reads_real_files(self, tmp_path: Path) -> None:
        """Test a file on disk exists, can be read, and reports its modification time."""
        path = tmp_path / "main.py"
        path.write_text("x = 1", encoding="utf-8")
        files = LocalFileSystem()
        assert files.exists(path) is True
        assert await files.read_text(path) == "x = 1"
        assert files.modified_time(path) == datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)

    async def test_missing_file(self, tmp_path: Path) -> None:
        """Test a missing file does not exist and raises OSError when read or inspected."""
        path = tmp_path / "missing.py"
        files = LocalFileSystem()
        assert files.exists(path) is False
        with pytest.raises(OSError):
            await files.read_text(path)
        with pytest.raises(OSError):
            files.modified_time(path)


class TestFakeAutomationRegistry:
    """Tests for FakeAutomationRegistry."""

    @pytest.fixture
    async def loaded_context(self, tmp_path: Path) -> Any:
        """Load an automation with a sync and an async action."""
        path = automation_file(tmp_path, "lights")
        path.write_text(
            "from haanim import action\n"
            "@action\n"
            "def add(a, b):\n"
            "    return a + b\n"
            "\n"
            "@action\n"
            "async def greet(name='world'):\n"
            "    return 'hello ' + name\n",
            encoding="utf-8",
        )
        context = make_context(str(path))
        await load_and_run(context)
        return context

    def test_empty(self) -> None:
        """Test an empty registry has no automations."""
        registry = FakeAutomationRegistry()
        assert registry.get_all_contexts() == []
        assert registry.get_context_by_name("lights") is None

    async def test_add_and_lookup(self, loaded_context: Any) -> None:
        """Test an added context is found by its automation ID."""
        registry = FakeAutomationRegistry()
        registry.add(loaded_context)
        assert registry.get_all_contexts() == [loaded_context]
        assert registry.get_context_by_name("lights") is loaded_context

    async def test_call_action(self, loaded_context: Any) -> None:
        """Test actions are called with their arguments and return their result."""
        registry = FakeAutomationRegistry()
        registry.add(loaded_context)
        assert await registry.async_call_action("lights", "add", 2, 3) == 5
        assert await registry.async_call_action("lights", "greet", name="there") == "hello there"

    async def test_call_action_unknown_automation(self) -> None:
        """Test calling into an automation that is not registered raises."""
        with pytest.raises(NonExistingAutomationError):
            await FakeAutomationRegistry().async_call_action("lights", "add")

    async def test_call_action_unknown_action(self, loaded_context: Any) -> None:
        """Test calling an action the automation does not have raises."""
        registry = FakeAutomationRegistry()
        registry.add(loaded_context)
        with pytest.raises(ActionNotFoundError):
            await registry.async_call_action("lights", "missing")

    async def test_control_calls_recorded(self, loaded_context: Any) -> None:
        """Test each control operation is recorded in order."""
        registry = FakeAutomationRegistry()
        registry.add(loaded_context)
        await registry.async_enable_automation("lights")
        await registry.async_disable_automation("lights")
        await registry.async_start_automation("lights")
        await registry.async_stop_automation("lights")
        await registry.async_restart_automation("lights")
        assert registry.control_calls == [
            ("enable", "lights"),
            ("disable", "lights"),
            ("start", "lights"),
            ("stop", "lights"),
            ("restart", "lights"),
        ]

    @pytest.mark.parametrize("operation", ["enable", "disable", "start", "stop", "restart"])
    async def test_control_unknown_automation(self, operation: str) -> None:
        """Test controlling an automation that is not registered raises and records nothing."""
        registry = FakeAutomationRegistry()
        with pytest.raises(NonExistingAutomationError):
            await getattr(registry, f"async_{operation}_automation")("lights")
        assert registry.control_calls == []


class TestMakeHost:
    """Tests for make_host."""

    def test_creates_all_members(self) -> None:
        """Test a host built without arguments has a fake for every member."""
        host = make_host()
        assert isinstance(host, Host)
        assert isinstance(host.states, FakeStateProvider)
        assert isinstance(host.events, FakeEventBus)
        assert isinstance(host.services, FakeServiceCaller)
        assert isinstance(host.clock, FakeClock)
        assert isinstance(host.sun, FakeSunProvider)
        assert isinstance(host.files, FakeFileSystem)

    async def test_created_fakes_share_the_clock(self) -> None:
        """Test states, events and files created by make_host are stamped by the host's clock."""
        clock = FakeClock()
        host = make_host(clock=clock)
        await clock.advance(hours=1)

        host.states.set_state("sensor.temp", "20")  # type: ignore[attr-defined]
        host.events.fire("my_event")
        host.files.write("/a.py", "1")  # type: ignore[attr-defined]

        assert host.clock is clock
        assert host.states.get("sensor.temp").last_updated == clock.now()
        assert host.events.fired[0].time_fired == clock.now()  # type: ignore[attr-defined]
        assert host.files.modified_time(Path("/a.py")) == clock.now()

    def test_given_fakes_are_used(self) -> None:
        """Test members passed in are used as they are."""
        states = FakeStateProvider()
        events = FakeEventBus()
        services = FakeServiceCaller()
        sun = FakeSunProvider()
        files = LocalFileSystem()
        host = make_host(states=states, events=events, services=services, sun=sun, files=files)
        assert (host.states, host.events, host.services, host.sun, host.files) == (
            states,
            events,
            services,
            sun,
            files,
        )

    def test_host_is_immutable(self) -> None:
        """Test members of a Host cannot be reassigned."""
        host = make_host()
        with pytest.raises(AttributeError):
            host.clock = FakeClock()  # type: ignore[misc]


class TestFakeFileSystemDirectories:
    """Directories of the in-memory file system exist through the files below them."""

    async def test_directories_follow_files(self) -> None:
        """A directory exists while it has a file below it."""
        files = FakeFileSystem()
        files.write("/a/b/c.py", "")

        assert files.is_dir(Path("/a")) and files.is_dir(Path("/a/b"))
        assert files.exists(Path("/a/b"))
        assert not files.is_dir(Path("/a/b/c.py"))
        assert await files.list_dir(Path("/a")) == [Path("/a/b")]

        files.delete("/a/b/c.py")
        assert not files.is_dir(Path("/a"))
        assert not files.exists(Path("/a/b"))

    async def test_list_dir(self) -> None:
        """Direct children are listed once each, sorted."""
        files = FakeFileSystem()
        for path in ("/r/b/x.py", "/r/b/y.py", "/r/a.py", "/r/c/d/e.py", "/other/z.py"):
            files.write(path, "")

        assert await files.list_dir(Path("/r")) == [Path("/r/a.py"), Path("/r/b"), Path("/r/c")]

    async def test_list_dir_of_a_file_or_missing_path(self) -> None:
        """Only directories can be listed."""
        files = FakeFileSystem()
        files.write("/r/a.py", "")

        for path in ("/r/a.py", "/missing"):
            with pytest.raises(FileNotFoundError):
                await files.list_dir(Path(path))


class TestLocalFileSystemDirectories:
    """The real file system lists directories the same way."""

    async def test_list_dir(self, tmp_path: Path) -> None:
        """Direct children are listed sorted."""
        (tmp_path / "b").mkdir()
        (tmp_path / "a.py").write_text("", encoding="utf-8")
        files = LocalFileSystem()

        assert await files.list_dir(tmp_path) == [tmp_path / "a.py", tmp_path / "b"]
        assert files.is_dir(tmp_path / "b") and not files.is_dir(tmp_path / "a.py")


class TestFakeIssueReporter:
    """Issues are held in memory and every call is recorded."""

    def test_report_clear_and_history(self) -> None:
        """The current issues and the calls made are both available to a test."""
        reporter = FakeIssueReporter()
        placeholders = {"folder": "x"}

        reporter.report("one", "kind", placeholders)
        placeholders["folder"] = "changed afterwards"
        reporter.clear("one")
        reporter.clear("unknown")

        assert reporter.issues == {}
        assert reporter.history == [("report", "one"), ("clear", "one"), ("clear", "unknown")]

    def test_placeholders_are_copied(self) -> None:
        """Changing the caller's dict afterwards does not change the issue."""
        reporter = FakeIssueReporter()
        placeholders = {"folder": "x"}

        reporter.report("one", "kind", placeholders)
        placeholders["folder"] = "y"

        assert reporter.issues["one"] == ("kind", {"folder": "x"})

    def test_make_host_creates_a_reporter(self) -> None:
        """A host built from fakes has an issue reporter, or the one given."""
        given = FakeIssueReporter()

        assert isinstance(make_host().issues, FakeIssueReporter)
        assert make_host(issues=given).issues is given


class TestFakeStorage:
    """Documents are held in memory as JSON."""

    async def test_save_load_and_peek(self) -> None:
        """A saved document can be loaded, and inspected without awaiting."""
        storage = FakeStorage()

        assert await storage.load("key") is None
        assert storage.peek("key") is None
        await storage.save("key", {"a": [1]})

        assert await storage.load("key") == {"a": [1]}
        assert storage.peek("key") == {"a": [1]}
        assert storage.saves == ["key"]

    async def test_rejects_what_is_not_json(self) -> None:
        """A value JSON cannot hold is refused, as a real store would."""
        with pytest.raises(TypeError):
            await FakeStorage().save("key", {"value": object()})

    def test_make_host_creates_storage(self) -> None:
        """A host built from fakes has storage, or the one given."""
        given = FakeStorage()

        assert isinstance(make_host().storage, FakeStorage)
        assert make_host(storage=given).storage is given


class TestFakeAutomationRegistryQueries:
    """The fake registry reports what a test sets."""

    def test_state_message_and_flag(self) -> None:
        """Defaults suit a running automation; each value can be set."""
        registry = FakeAutomationRegistry()

        assert registry.automation_state("lights") == "unavailable"
        assert registry.automation_message("lights") is None
        assert registry.is_automation_enabled("lights") is True

        registry.states["lights"] = "error"
        registry.messages["lights"] = "broken"
        registry.disabled.add("lights")

        assert registry.automation_state("lights") == "error"
        assert registry.automation_message("lights") == "broken"
        assert registry.is_automation_enabled("lights") is False
