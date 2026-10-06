"""Tests that the engine's timing follows the injected clock.

Each test drives a piece of the engine with ``FakeClock`` and checks that
timestamps, delays and timeouts happen exactly when the clock says, with no
real waiting.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from haanim.const import TRIGGER_CRON, TRIGGER_INTERVAL, TRIGGER_STATE
from haanim.engine.action_pool import ActionWorkerPool
from haanim.engine.automation_context import TriggerDefinition
from haanim.engine.automation_status import AutomationStatusManager
from haanim.engine.haanim_api import HAAnim
from haanim.engine.triggers import CronTrigger, IntervalTrigger, StateTrigger
from haanim.interfaces import Host
from haanim.testing import FakeAutomationRegistry, FakeClock, FakeServiceCaller, FakeStateProvider, make_host
from haanim.testing.fakes import DEFAULT_NOW
from tests.engine.helpers import automation_file, load_and_run, make_context

UTC = timezone.utc


@pytest.fixture
def clock() -> FakeClock:
    """A fake clock at its default start."""
    return FakeClock()


@pytest.fixture
def pool(clock: FakeClock) -> ActionWorkerPool:
    """An action pool on the fake clock."""
    return ActionWorkerPool(status_manager=AutomationStatusManager(), clock=clock)


def trigger_definition(trigger_type: str, expr: str, func: Any, **kwargs: Any) -> TriggerDefinition:
    """Build a trigger definition for a test function."""
    return TriggerDefinition(
        trigger_type=trigger_type,
        trigger_expr=expr,
        func_name="on_trigger",
        func=func,
        kwargs=kwargs,
        automation_id="auto",
    )


class TestPoolTimestamps:
    """The pool stamps executions with the clock's time."""

    async def test_clock_property(self, pool: ActionWorkerPool, clock: FakeClock) -> None:
        """Test the pool exposes the clock it was given."""
        assert pool.clock is clock

    async def test_started_and_completed_times(self, pool: ActionWorkerPool, clock: FakeClock) -> None:
        """Test started_at and completed_at are read from the clock."""
        executions: list[Any] = []

        async def action() -> None:
            executions.extend(pool.get_active_actions("auto"))
            await clock.sleep(30)

        task = asyncio.create_task(pool.submit_action("auto", "work", action))
        await clock.advance(seconds=30)
        await task

        (execution,) = executions
        assert execution.started_at == DEFAULT_NOW
        assert execution.completed_at == DEFAULT_NOW + timedelta(seconds=30)


class TestIntervalTriggerOnClock:
    """The interval trigger fires when the clock says."""

    async def test_fires_every_interval(self, clock: FakeClock) -> None:
        """Test the first fire is one interval after start and then one per interval."""
        fired: list[datetime] = []

        async def on_trigger(**kwargs: Any) -> None:
            fired.append(clock.now())

        trigger = IntervalTrigger(
            make_host(clock=clock), trigger_definition(TRIGGER_INTERVAL, "00:01:00", on_trigger)
        )
        await trigger.async_start()

        await clock.advance(seconds=59)
        assert fired == []

        await clock.advance(minutes=3, seconds=1)
        await trigger.async_stop()

        assert fired == [DEFAULT_NOW + timedelta(minutes=minutes) for minutes in (1, 2, 3, 4)]

    async def test_delay_sets_first_fire(self, clock: FakeClock) -> None:
        """Test a delay moves the first fire; later fires are one interval apart."""
        fired: list[datetime] = []

        async def on_trigger(**kwargs: Any) -> None:
            fired.append(clock.now())

        trigger = IntervalTrigger(
            make_host(clock=clock),
            trigger_definition(TRIGGER_INTERVAL, "00:05:00", on_trigger, delay="00:01:00"),
        )
        await trigger.async_start()
        await clock.advance(minutes=12)
        await trigger.async_stop()

        assert fired == [DEFAULT_NOW + timedelta(minutes=minutes) for minutes in (1, 6, 11)]

    async def test_stop_leaves_no_timer(self, clock: FakeClock) -> None:
        """Test stopping the trigger cancels its pending sleep and nothing fires afterwards."""
        fired: list[datetime] = []

        async def on_trigger(**kwargs: Any) -> None:
            fired.append(clock.now())

        trigger = IntervalTrigger(
            make_host(clock=clock), trigger_definition(TRIGGER_INTERVAL, "60", on_trigger)
        )
        await trigger.async_start()
        await clock.settle()
        assert clock.pending_timers == 1

        await trigger.async_stop()
        assert clock.pending_timers == 0

        await clock.advance(hours=1)
        assert fired == []


class TestCronTriggerOnClock:
    """The cron trigger computes its fires from the clock's time."""

    async def test_fires_at_matching_times(self) -> None:
        """Test a five-minute cron fires at each five-minute mark of the clock's time."""
        clock = FakeClock(datetime(2025, 1, 6, 12, 2, 0, tzinfo=UTC))
        fired: list[datetime] = []

        async def on_trigger(**kwargs: Any) -> None:
            fired.append(clock.now())

        trigger = CronTrigger(
            make_host(clock=clock), trigger_definition(TRIGGER_CRON, "*/5 * * * *", on_trigger)
        )
        await trigger.async_start()

        await clock.advance(minutes=2, seconds=59)
        assert fired == []

        await clock.advance(minutes=10, seconds=1)
        await trigger.async_stop()

        assert fired == [datetime(2025, 1, 6, 12, minute, 0, tzinfo=UTC) for minute in (5, 10, 15)]
        assert clock.pending_timers == 0


class TestStateHoldOnClock:
    """A state trigger's hold time is measured on the clock."""

    async def test_fires_after_hold(self, clock: FakeClock) -> None:
        """Test a held state trigger fires once the hold time has passed on the clock, not before."""
        fired: list[datetime] = []

        async def on_trigger(**kwargs: Any) -> None:
            fired.append(clock.now())

        states = FakeStateProvider(clock)
        states.set_state("sensor.temp", "10")
        host = make_host(clock=clock, states=states)
        trigger = StateTrigger(
            host, trigger_definition(TRIGGER_STATE, "sensor.temp > 25", on_trigger, hold=60)
        )
        await trigger.async_start()
        await clock.settle()

        states.set_state("sensor.temp", "30")
        await clock.advance(seconds=59)
        assert fired == []

        await clock.advance(seconds=1)
        await trigger.async_stop()
        assert fired == [DEFAULT_NOW + timedelta(seconds=60)]


class TestHaaOnClock:
    """The haa API reads time from the clock."""

    @pytest.fixture
    def services(self) -> FakeServiceCaller:
        """Services with one registered light service."""
        caller = FakeServiceCaller()
        caller.register("light", "turn_on")
        return caller

    @pytest.fixture
    def host(self, clock: FakeClock, services: FakeServiceCaller) -> Host:
        """A fake host on the fake clock."""
        return make_host(clock=clock, services=services)

    @pytest.fixture
    def haa(self, host: Host, tmp_path: Path) -> HAAnim:
        """A haa instance on the fake host."""
        return HAAnim(host, "me", FakeAutomationRegistry())

    async def test_now_follows_the_clock(self, haa: HAAnim, clock: FakeClock) -> None:
        """Test haa.now() is the clock's time, timezone-aware, and moves when the clock moves."""
        assert haa.now() == DEFAULT_NOW
        assert haa.now().tzinfo is not None
        await clock.advance(hours=2)
        assert haa.now() == DEFAULT_NOW + timedelta(hours=2)

    async def test_service_call_times(self, haa: HAAnim, clock: FakeClock) -> None:
        """Test a service call result carries the clock's time for call and completion."""
        await clock.advance(minutes=5)
        result = await haa.service.light.turn_on()
        assert result.call_time == DEFAULT_NOW + timedelta(minutes=5)
        assert result.complete_time == DEFAULT_NOW + timedelta(minutes=5)

    async def test_failed_service_call_times(
        self, haa: HAAnim, clock: FakeClock, services: FakeServiceCaller
    ) -> None:
        """Test a failed call is also stamped from the clock."""
        services.fail("light", "turn_on")
        result = await haa.service.light.turn_on()
        assert result.success is False
        assert result.complete_time == clock.now()


class TestAutomationOnClock:
    """A loaded automation takes its time from the clock."""

    async def test_loaded_at(self, clock: FakeClock, tmp_path: Path) -> None:
        """Test an automation's load time is the clock's time at load."""
        path = automation_file(tmp_path, "auto")
        path.write_text("x = 1\n", encoding="utf-8")
        await clock.advance(hours=1)

        context = make_context(str(path), host=_host_reading_disk(clock))
        metadata = await load_and_run(context)

        assert metadata.loaded_at == DEFAULT_NOW + timedelta(hours=1)

    async def test_sleep_helper_uses_the_clock(self, clock: FakeClock, tmp_path: Path) -> None:
        """Test the sleep helper available to automations waits on the clock, not on real time."""
        path = automation_file(tmp_path, "auto")
        path.write_text(
            "from haanim import action, haa\n"
            "steps = []\n"
            "\n"
            "@action\n"
            "async def wait_a_minute():\n"
            "    steps.append('before')\n"
            "    await haa.sleep(60)\n"
            "    steps.append('after')\n",
            encoding="utf-8",
        )
        context = make_context(str(path), host=_host_reading_disk(clock))
        await load_and_run(context)

        task = asyncio.create_task(context.run_action("wait_a_minute"))
        await clock.advance(seconds=59)
        assert context.get_symbol("steps") == ["before"]

        await clock.advance(seconds=1)
        await task
        assert context.get_symbol("steps") == ["before", "after"]


def _host_reading_disk(clock: FakeClock) -> Host:
    """Build a fake host on the given clock whose file system reads real files."""
    from haanim.testing import LocalFileSystem  # pylint: disable=import-outside-toplevel

    return make_host(clock=clock, files=LocalFileSystem())


class TestIntervalAndCronDetails:
    """Remaining behaviour of the interval and cron triggers, driven by the clock."""

    def test_interval_decorator_records_trigger(self) -> None:
        """Test the interval decorator records the interval, delay and constraints on the function."""
        from haanim.engine.decorators import get_metadata  # pylint: disable=import-outside-toplevel
        from haanim.engine.decorators import on_interval  # pylint: disable=import-outside-toplevel

        @on_interval("00:05:00", delay="00:01:00", when="person.john == 'home'")
        def task() -> None:
            """Decorated function."""

        (info,) = get_metadata(task).triggers
        assert info.trigger_type == TRIGGER_INTERVAL
        assert info.trigger_expr == "00:05:00"
        assert info.kwargs == {"delay": "00:01:00"}
        assert info.constraints == {"when": "person.john == 'home'"}

    def test_cron_decorator_records_trigger(self) -> None:
        """Test the cron decorator records the expression and constraints on the function."""
        from haanim.engine.decorators import get_metadata  # pylint: disable=import-outside-toplevel
        from haanim.engine.decorators import on_cron  # pylint: disable=import-outside-toplevel

        @on_cron("0 9 * * 1-5", when="person.john == 'home'")
        def task() -> None:
            """Decorated function."""

        (info,) = get_metadata(task).triggers
        assert info.trigger_type == TRIGGER_CRON
        assert info.trigger_expr == "0 9 * * 1-5"
        assert info.kwargs == {}
        assert info.constraints == {"when": "person.john == 'home'"}

    @pytest.mark.parametrize(
        ("spec", "seconds"),
        [("90", 90.0), ("0.5", 0.5), ("01:00:00", 3600), ("00:00:45", 45)],
    )
    def test_interval_formats(self, clock: FakeClock, spec: str, seconds: float) -> None:
        """Test each interval format gives the expected number of seconds."""
        trigger = IntervalTrigger(
            make_host(clock=clock), trigger_definition(TRIGGER_INTERVAL, spec, lambda: None)
        )
        assert trigger.interval_seconds == seconds
        assert trigger.delay_seconds == seconds

    def test_invalid_cron_expression(self, clock: FakeClock) -> None:
        """Test an invalid cron expression is rejected when the trigger is created."""
        with pytest.raises(ValueError, match="Invalid cron expression"):
            CronTrigger(make_host(clock=clock), trigger_definition(TRIGGER_CRON, "not a cron", lambda: None))

    async def test_interval_stop_before_start(self, clock: FakeClock) -> None:
        """Test stopping an interval trigger that was never started does nothing."""
        trigger = IntervalTrigger(
            make_host(clock=clock), trigger_definition(TRIGGER_INTERVAL, "60", lambda: None)
        )
        await trigger.async_stop()

    async def test_cron_stop_before_start(self, clock: FakeClock) -> None:
        """Test stopping a cron trigger that was never started does nothing."""
        trigger = CronTrigger(
            make_host(clock=clock), trigger_definition(TRIGGER_CRON, "* * * * *", lambda: None)
        )
        await trigger.async_stop()

    async def test_interval_skips_when_constraint_fails(self, clock: FakeClock) -> None:
        """Test an interval whose constraint is not met does not fire and does not count the run."""
        fired: list[datetime] = []

        async def on_trigger(**kwargs: Any) -> None:
            fired.append(clock.now())

        states = FakeStateProvider(clock)
        states.set_state("input_boolean.enabled", "off")
        definition = trigger_definition(TRIGGER_INTERVAL, "60", on_trigger)
        definition.constraints = {"when": "input_boolean.enabled == 'on'"}
        trigger = IntervalTrigger(make_host(clock=clock, states=states), definition)
        await trigger.async_start()

        await clock.advance(minutes=2)
        assert fired == []
        assert trigger.execution_count == 0

        states.set_state("input_boolean.enabled", "on")
        await clock.advance(minutes=1)
        await trigger.async_stop()
        assert fired == [DEFAULT_NOW + timedelta(minutes=3)]
        assert trigger.execution_count == 1

    async def test_interval_keeps_running_after_a_failing_function(self, clock: FakeClock) -> None:
        """Test a function that raises does not stop the interval; it fires again next time."""
        fired: list[datetime] = []

        async def on_trigger(**kwargs: Any) -> None:
            fired.append(clock.now())
            raise ValueError("boom")

        trigger = IntervalTrigger(
            make_host(clock=clock), trigger_definition(TRIGGER_INTERVAL, "60", on_trigger)
        )
        await trigger.async_start()
        await clock.advance(minutes=3)
        await trigger.async_stop()

        assert fired == [DEFAULT_NOW + timedelta(minutes=minutes) for minutes in (1, 2, 3)]

    async def test_cron_keeps_running_after_a_failing_function(self) -> None:
        """Test a function that raises does not stop the cron trigger."""
        clock = FakeClock(datetime(2025, 1, 6, 12, 0, 30, tzinfo=UTC))
        fired: list[datetime] = []

        async def on_trigger(**kwargs: Any) -> None:
            fired.append(clock.now())
            raise ValueError("boom")

        trigger = CronTrigger(
            make_host(clock=clock), trigger_definition(TRIGGER_CRON, "* * * * *", on_trigger)
        )
        await trigger.async_start()
        await clock.advance(minutes=3)
        await trigger.async_stop()

        assert fired == [datetime(2025, 1, 6, 12, minute, 0, tzinfo=UTC) for minute in (1, 2, 3)]
