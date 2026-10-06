"""Tests for the interval trigger.

See "Interval Trigger" in the design: fires at a fixed rate from the moment the
triggers are registered, whatever the action does.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from haanim.const import EVENT_ACTION_ERROR, TRIGGER_INTERVAL
from haanim.engine.action_dispatcher import ActionDispatcher
from haanim.engine.action_pool import ActionWorkerPool
from haanim.engine.automation_context import TriggerDefinition
from haanim.engine.automation_status import AutomationStatusManager
from haanim.engine.lifecycle import Automation, AutomationState
from haanim.engine.triggers import IntervalTrigger
from haanim.engine.triggers.manager import TriggerManager
from haanim.events import IntervalEvent, ManualEvent
from haanim.testing import FakeClock, make_host
from haanim.testing.fakes import DEFAULT_NOW
from tests.engine.test_lifecycle import World


class IntervalWorld(World):
    """A world whose triggers are fired by the real trigger manager."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.triggers = TriggerManager(self.host, self.dispatcher)  # type: ignore[assignment]

    def seconds(self) -> list[tuple[int, float]]:
        """Return the log as (execution_count, seconds since the start of the test)."""
        return [(count, (when - DEFAULT_NOW).total_seconds()) for count, when in self.log]

    def errors(self) -> list[str]:
        """Return the error type of every haanim_action_error event fired so far."""
        return [
            event.data["error_type"]
            for event in self.host.events.fired
            if event.event_type == EVENT_ACTION_ERROR
        ]


@pytest.fixture
async def interval_world(tmp_path: Path) -> Any:
    """A world with a real trigger manager; whatever still runs is cancelled afterwards."""
    result = IntervalWorld(tmp_path)
    yield result
    for automation in result.automations.values():
        if automation.state is AutomationState.ON:
            stopping = asyncio.create_task(automation.stop())
            await result.clock.advance(seconds=1)
            await stopping
    await result.dispatcher.shutdown()


def source(decorator: str, body: str = "    log.append((event.execution_count, event.call_time))\n") -> str:
    """An automation with one interval trigger function."""
    return f"from haanim import ActionMode, action, on_interval, sleep\n\n{decorator}\nasync def tick(event):\n{body}"


class TestSchedule:
    """Fires at delay, delay + interval, delay + 2 * interval, and so on."""

    async def test_first_fire_is_one_interval_after_registration(self, interval_world: IntervalWorld) -> None:
        """Without a delay, the delay is the interval."""
        await interval_world.started("ticker", source('@on_interval("01:00:00")'))

        await interval_world.clock.advance(seconds=3599)
        assert interval_world.log == []
        await interval_world.clock.advance(seconds=1)
        assert interval_world.seconds() == [(1, 3600)]

        await interval_world.clock.advance(hours=2)
        assert interval_world.seconds() == [(1, 3600), (2, 7200), (3, 10800)]

    async def test_explicit_delay(self, interval_world: IntervalWorld) -> None:
        """The design's example: every 5 minutes, first after 1 minute."""
        await interval_world.started("ticker", source('@on_interval("00:05:00", delay="00:01:00")'))

        await interval_world.clock.advance(seconds=59)
        assert interval_world.log == []
        await interval_world.clock.advance(minutes=11)
        assert interval_world.seconds() == [(1, 60), (2, 360), (3, 660)]

    async def test_delay_longer_than_the_interval(self, interval_world: IntervalWorld) -> None:
        """The delay only moves the first fire."""
        await interval_world.started("ticker", source('@on_interval(60, delay="00:10:00")'))
        await interval_world.clock.advance(minutes=12)
        assert interval_world.seconds() == [(1, 600), (2, 660), (3, 720)]

    @pytest.mark.parametrize(
        ("interval", "expected"),
        [
            ("30", 30.0),
            ("3600", 3600.0),
            ('"3600"', 3600.0),
            ('"0.5"', 0.5),
            ('"00:05:00"', 300.0),
            ("2.5", 2.5),
        ],
    )
    async def test_interval_formats(
        self, interval_world: IntervalWorld, interval: str, expected: float
    ) -> None:
        """Seconds as a number or string, or HH:MM:SS."""
        await interval_world.started(
            "ticker",
            source(
                f"@on_interval({interval})", "    log.append((event.interval_seconds, event.call_time))\n"
            ),
        )
        await interval_world.clock.advance(seconds=expected * 2)
        assert interval_world.seconds() == [(expected, expected), (expected, expected * 2)]

    async def test_schedule_does_not_accumulate_error(self) -> None:
        """Each fire is at its exact place in the schedule, also after many fires."""
        clock = FakeClock()
        dispatcher = ActionDispatcher(ActionWorkerPool(status_manager=AutomationStatusManager(), clock=clock))
        fired: list[datetime] = []

        def on_trigger() -> None:
            fired.append(clock.now())

        trigger = IntervalTrigger(
            make_host(clock=clock),
            TriggerDefinition(
                trigger_type=TRIGGER_INTERVAL,
                trigger_expr="0.1",
                func_name="tick",
                func=on_trigger,
                automation_id="auto",
            ),
            dispatcher,
        )
        await trigger.async_start()
        await clock.advance(seconds=30)
        await trigger.async_stop()

        assert len(fired) == 300
        offsets = [round((when - DEFAULT_NOW).total_seconds(), 6) for when in fired]
        assert offsets == [round(0.1 * number, 6) for number in range(1, 301)]
        assert trigger.execution_count == 300

    async def test_registered_after_startup(self, interval_world: IntervalWorld) -> None:
        """The schedule starts when the triggers are registered, which is after @startup has finished."""
        automation = interval_world.add(
            "ticker",
            "from haanim import on_interval, startup, sleep\n\n@startup\nasync def on_start():\n    await sleep(20)\n\n"
            "@on_interval(60)\ndef tick(event):\n    log.append((event.execution_count, event.call_time))\n",
        )
        await automation.load()
        starting = asyncio.create_task(automation.start())
        await interval_world.clock.advance(seconds=20)
        assert await starting
        interval_world.expose(automation)

        await interval_world.clock.advance(seconds=59)
        assert interval_world.log == []
        await interval_world.clock.advance(seconds=1)
        assert interval_world.seconds() == [(1, 80)]

    async def test_two_interval_triggers_on_one_function(self, interval_world: IntervalWorld) -> None:
        """Each trigger has its own schedule and its own count."""
        await interval_world.started(
            "ticker",
            "from haanim import on_interval, action, ActionMode\n\n@on_interval(60)\n@on_interval(90)\n"
            "@action(execution_mode=ActionMode.QUEUE)\n"
            "def tick(event):\n    log.append((event.interval_seconds, event.execution_count, event.call_time))\n",
        )
        await interval_world.clock.advance(seconds=180)
        fires = sorted(
            (interval, count, (when - DEFAULT_NOW).total_seconds())
            for interval, count, when in interval_world.log
        )
        assert fires == [(60, 1, 60), (60, 2, 120), (60, 3, 180), (90, 1, 90), (90, 2, 180)]


class TestEvent:
    """The IntervalEvent a fire delivers."""

    async def test_fields(self, interval_world: IntervalWorld) -> None:
        """interval_seconds, execution_count and the common fields."""
        await interval_world.started("ticker", source('@on_interval("00:05:00")', "    log.append(event)\n"))
        await interval_world.clock.advance(minutes=10)

        first, second = interval_world.log
        assert type(first) is IntervalEvent
        assert (first.interval_seconds, type(first.interval_seconds)) == (300.0, float)
        assert (first.execution_count, second.execution_count) == (1, 2)
        assert (first.automation_id, first.source, first.caller, first.data) == (
            "ticker",
            "trigger",
            None,
            {},
        )
        assert first.call_time == DEFAULT_NOW.replace(minute=5)

    async def test_direct_call_is_not_an_interval_event(self, interval_world: IntervalWorld) -> None:
        """Called by hand, the function gets a ManualEvent and the count is untouched."""
        automation = await interval_world.started(
            "ticker", source("@on_interval(60)", "    log.append(event)\n    return type(event).__name__\n")
        )
        assert await automation.call_action("tick") == "ManualEvent"
        await interval_world.clock.advance(seconds=60)

        manual, fired = interval_world.log
        assert type(manual) is ManualEvent
        assert fired.execution_count == 1


SLOW = """
from haanim import ActionMode, action, on_interval, sleep

@on_interval(60)
@action(execution_mode=ActionMode.%s)
async def tick(event):
    log.append((event.execution_count, event.call_time))
    try:
        await sleep(150)
    except BaseException as err:
        log.append((type(err).__name__, haa_now()))
        raise
    log.append(("done", haa_now()))
"""


class TestSlowAction:
    """The schedule does not drift with how long the action takes; the mode decides about overruns."""

    @staticmethod
    async def run(interval_world: IntervalWorld, mode: str, seconds: float) -> list[tuple[Any, float]]:
        """Run the slow action in a mode for a while and return what it logged."""
        automation = interval_world.add("ticker", SLOW % mode)
        await automation.load()
        original = automation.context.execute

        async def execute() -> Any:
            result = await original()
            automation.context.set_symbol("haa_now", interval_world.clock.now)
            automation.context.set_symbol("log", interval_world.log)
            return result

        automation.context.execute = execute  # type: ignore[method-assign]
        assert await automation.start(), automation.message
        await interval_world.clock.advance(seconds=seconds)
        return interval_world.seconds()

    async def test_drop_skips_fires_and_keeps_the_schedule(self, interval_world: IntervalWorld) -> None:
        """With DROP, fires during a run are skipped, and the next run starts on the schedule."""
        log = await self.run(interval_world, "DROP", 420)

        # Runs 60-210 and 240-390; the fires at 120, 180, 300 and 360 are dropped
        assert log == [(1, 60), ("done", 210), (4, 240), ("done", 390), (7, 420)]

    async def test_dropped_fires_are_trigger_fired_failures(self, interval_world: IntervalWorld) -> None:
        """Each skipped fire is recorded as a failure of the action."""
        await self.run(interval_world, "DROP", 420)
        assert interval_world.errors() == ["ActionDroppedError"] * 4
        (automation,) = interval_world.automations.values()
        assert automation.last_error is not None
        assert (automation.last_error.action, automation.last_error.error_type) == (
            "tick",
            "ActionDroppedError",
        )
        assert automation.state is AutomationState.ON

    async def test_count_includes_dropped_fires(self, interval_world: IntervalWorld) -> None:
        """execution_count counts every fire, also the ones that were dropped."""
        log = await self.run(interval_world, "DROP", 420)
        assert [count for count, _ in log if isinstance(count, int)] == [1, 4, 7]

    async def test_queue_runs_every_fire_in_order(self, interval_world: IntervalWorld) -> None:
        """With QUEUE, each fire waits its turn; its event keeps the time it was due."""
        log = await self.run(interval_world, "QUEUE", 520)

        # One run takes 150 s: 60-210, 210-360, 360-510; the events were made at 60, 120, 180
        assert log == [(1, 60), ("done", 210), (2, 120), ("done", 360), (3, 180), ("done", 510), (4, 240)]
        assert interval_world.errors() == []

    async def test_cancel_restarts_the_action_at_every_fire(self, interval_world: IntervalWorld) -> None:
        """With CANCEL, each fire cancels the run before it."""
        log = await self.run(interval_world, "CANCEL", 185)

        assert log == [(1, 60), ("CancelledError", 120), (2, 120), ("CancelledError", 180), (3, 180)]
        assert interval_world.errors() == []


class TestRestart:
    """The count and the schedule start again when the automation is started again."""

    async def test_count_resets_on_restart(self, interval_world: IntervalWorld) -> None:
        """execution_count starts at 1 again after stop and start."""
        automation = await interval_world.started("ticker", source("@on_interval(60)"))
        await interval_world.clock.advance(seconds=180)
        assert [count for count, _ in interval_world.log] == [1, 2, 3]

        await automation.stop()
        assert await automation.start()
        interval_world.expose(automation)
        await interval_world.clock.advance(seconds=120)
        assert [count for count, _ in interval_world.log] == [1, 2, 3, 1, 2]

    async def test_schedule_restarts_from_the_new_registration(self, interval_world: IntervalWorld) -> None:
        """After a restart the first fire is one delay after the restart, not on the old schedule."""
        automation = await interval_world.started("ticker", source("@on_interval(60)"))
        await interval_world.clock.advance(seconds=90)
        await automation.stop()
        assert await automation.start()
        interval_world.expose(automation)

        await interval_world.clock.advance(seconds=59)
        assert interval_world.seconds() == [(1, 60)]
        await interval_world.clock.advance(seconds=1)
        assert interval_world.seconds() == [(1, 60), (1, 150)]

    async def test_missed_fires_are_not_caught_up(self, interval_world: IntervalWorld) -> None:
        """Nothing fires while stopped, and nothing is made up for afterwards."""
        automation = await interval_world.started("ticker", source("@on_interval(60)"))
        await interval_world.clock.advance(seconds=60)
        await automation.stop()

        await interval_world.clock.advance(minutes=30)
        assert interval_world.seconds() == [(1, 60)]

        assert await automation.start()
        interval_world.expose(automation)
        await interval_world.clock.advance(seconds=60)
        assert interval_world.seconds() == [(1, 60), (1, 60 + 1800 + 60)]

    async def test_stop_leaves_no_timer(self, interval_world: IntervalWorld) -> None:
        """Stopping the automation cancels the trigger's timer."""
        automation = await interval_world.started("ticker", source("@on_interval(60)"))
        assert interval_world.clock.pending_timers == 1
        await automation.stop()
        assert interval_world.clock.pending_timers == 0

    async def test_failed_start_leaves_no_timer(self, interval_world: IntervalWorld) -> None:
        """If a later trigger cannot be registered, the interval trigger is unregistered again."""
        automation = interval_world.add(
            "ticker",
            "from haanim import on_interval, startup\n\n@on_interval(60)\ndef tick(event):\n    pass\n\n"
            "@startup\ndef on_start():\n    raise RuntimeError('no')\n",
        )
        await automation.load()
        assert not await automation.start()
        assert interval_world.clock.pending_timers == 0


INVALID = [
    (
        '@on_interval("05:00")',
        "@on_interval: the interval '05:00' is not valid: the two-part form is not accepted",
    ),
    ("@on_interval(0)", "@on_interval: the interval 0 is not valid: a duration must be greater than zero"),
    (
        '@on_interval("-10")',
        "@on_interval: the interval '-10' is not valid: a duration must be greater than zero",
    ),
    (
        '@on_interval("soon")',
        "@on_interval: the interval 'soon' is not valid: a duration is seconds or 'HH:MM:SS'",
    ),
    ('@on_interval(60, delay="01:00")', "@on_interval: delay '01:00' is not valid: the two-part form"),
    ("@on_interval(60, delay=0)", "@on_interval: delay 0 is not valid: a duration must be greater than zero"),
    ('@on_interval("00:61:00")', "@on_interval: the interval '00:61:00' is not valid: minutes and seconds"),
    (
        "@on_state(\"sensor.a == 'on'\", hold='5 minutes')",
        "@on_state: hold '5 minutes' is not valid: a duration is seconds or 'HH:MM:SS'",
    ),
    (
        "@on_state(\"sensor.a == 'on'\", hold='10:00')",
        "@on_state: hold '10:00' is not valid: the two-part form",
    ),
    (
        "@on_state(\"sensor.a == 'on'\", hold=-1)",
        "@on_state: hold -1 is not valid: a duration must be greater",
    ),
]


class TestInvalidDurations:
    """An invalid duration puts the automation in error, naming the decorator and the value."""

    @pytest.mark.parametrize(("decorator", "message"), INVALID, ids=[decorator for decorator, _ in INVALID])
    async def test_start_error(self, interval_world: IntervalWorld, decorator: str, message: str) -> None:
        """The automation does not start; the message names the decorator and the value."""
        automation: Automation = interval_world.add(
            "ticker", f"from haanim import on_interval, on_state\n\n{decorator}\ndef tick(event):\n    pass\n"
        )
        assert await automation.load()
        assert not await automation.start()

        assert automation.state is AutomationState.ERROR
        assert automation.message is not None
        assert automation.message.startswith(f"ValueError: {message}")
        assert interval_world.clock.pending_timers == 0

    @pytest.mark.parametrize(
        "decorator",
        [
            "@on_interval(60)",
            '@on_interval("00:05:00", delay=1)',
            "@on_state(\"sensor.a == 'on'\", hold=30)",
            "@on_state(\"sensor.a == 'on'\", hold='00:00:30')",
        ],
    )
    async def test_valid_durations_start(self, interval_world: IntervalWorld, decorator: str) -> None:
        """Valid durations do not keep an automation from starting."""
        automation = interval_world.add(
            "ticker", f"from haanim import on_interval, on_state\n\n{decorator}\ndef tick(event):\n    pass\n"
        )
        assert await automation.load()
        assert await automation.start(), automation.message
