"""Tests for waiting inside an action: haa.sleep and haa.wait_for.

See "Waiting" in the design.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.errors import (
    ActionCancelledError,
    ActionDroppedError,
    ActionTimeOutError,
    AutomationSyntaxError,
)
from haanim.engine.lifecycle import Automation, AutomationState
from haanim.testing.fakes import DEFAULT_NOW
from tests.engine.test_lifecycle import World, world  # noqa: F401  pylint: disable=unused-import

SOURCE = """
from haanim import ActionMode, AutomationSyntaxError, action, haa, on_state

@action
async def nap(event):
    await haa.sleep(event.data["duration"])
    return haa.now()

@action(timeout=5)
async def long_nap(event):
    await haa.sleep(60)

@action
async def wait(event):
    log.append("waiting")
    try:
        result = await haa.wait_for(event.data["expr"], timeout=event.data.get("timeout"))
    except BaseException as err:
        log.append(type(err).__name__)
        raise
    log.append(result)
    return result

@action(timeout=5)
async def wait_with_action_timeout(event):
    return await haa.wait_for("binary_sensor.door == 'on'")

@action
async def bad_expression(event):
    log.append("before")
    try:
        await haa.wait_for("sensor.temperature >")
    except AutomationSyntaxError as err:
        log.append(str(err))
        return "caught"

@action(execution_mode=ActionMode.CANCEL)
async def latest(event):
    log.append(f"start {event.data['n']}")
    result = await haa.wait_for("binary_sensor.door == 'on'")
    log.append(f"done {event.data['n']}")
    return result
"""


async def seconds_slept(world: World, automation: Automation, action: str, duration: Any) -> float:
    """Call a sleeping action and return how long it slept on the clock."""
    call = asyncio.create_task(automation.call_action(action, {"duration": duration}))
    await world.clock.advance(hours=3)
    return (await call - DEFAULT_NOW).total_seconds()


async def waiting(world: World, expr: str, timeout: Any = None) -> tuple[Automation, asyncio.Task[Any]]:
    """Start an automation and an action that waits for an expression."""
    automation = await world.started("waiter", SOURCE)
    call = asyncio.create_task(automation.call_action("wait", {"expr": expr, "timeout": timeout}))
    await world.clock.settle()
    return automation, call


async def change(world: World, entity_id: str, state: str, **attributes: Any) -> None:
    """Change an entity and let the waiting action react."""
    world.host.states.set_state(entity_id, state, attributes)
    await world.clock.settle()


class TestSleep:
    """await haa.sleep(duration)."""

    @pytest.mark.parametrize(
        ("duration", "seconds"),
        [(30, 30), (0.5, 0.5), ("90", 90), ("0.25", 0.25), ("00:05:00", 300), ("01:00:00", 3600)],
    )
    async def test_duration_formats(self, world: World, duration: Any, seconds: float) -> None:
        """A number, a numeric string, or HH:MM:SS."""
        automation = await world.started("waiter", SOURCE)
        assert await seconds_slept(world, automation, "nap", duration) == seconds

    async def test_follows_the_injected_clock(self, world: World) -> None:
        """Nothing happens until the clock is moved."""
        automation = await world.started("waiter", SOURCE)
        call = asyncio.create_task(automation.call_action("nap", {"duration": 10}))
        await world.clock.settle()
        assert not call.done()
        await world.clock.advance(seconds=9.9)
        assert not call.done()
        await world.clock.advance(seconds=0.1)
        assert call.done()

    async def test_zero_yields_without_waiting(self, world: World) -> None:
        """haa.sleep(0) returns without any time passing."""
        automation = await world.started("waiter", SOURCE)
        assert await automation.call_action("nap", {"duration": 0}) == DEFAULT_NOW

    @pytest.mark.parametrize(
        ("duration", "reason"),
        [
            (-1, "greater than zero"),
            ("05:00", "two-part form"),
            ("soon", "seconds or 'HH:MM:SS'"),
            (None, "NoneType"),
        ],
    )
    async def test_invalid_duration(self, world: World, duration: Any, reason: str) -> None:
        """A duration that cannot be read raises ValueError in the action."""
        automation = await world.started("waiter", SOURCE)
        with pytest.raises(ValueError, match=reason) as exc_info:
            await automation.call_action("nap", {"duration": duration})
        assert str(exc_info.value).startswith("haa.sleep: ")

    async def test_sleep_is_only_on_haa(self, world: World) -> None:
        """`sleep` cannot be imported from haanim: the one way to sleep is haa.sleep()."""
        automation = world.add("importer", "from haanim import sleep\n")
        assert await automation.load()
        assert not await automation.start()
        assert "cannot import name 'sleep' from 'haanim'" in (automation.message or "")

    async def test_counts_towards_the_action_timeout(self, world: World) -> None:
        """An action asleep past its timeout is timed out."""
        automation = await world.started("waiter", SOURCE)
        call = asyncio.create_task(automation.call_action("long_nap"))
        await world.clock.advance(seconds=5)
        with pytest.raises(ActionTimeOutError):
            await call

    async def test_ends_when_the_automation_is_stopped(self, world: World) -> None:
        """A sleeping action is cancelled by stop; its caller gets ActionCancelledError."""
        automation = await world.started("waiter", SOURCE)
        call = asyncio.create_task(automation.call_action("nap", {"duration": 3600}))
        await world.clock.settle()
        stopping = asyncio.create_task(automation.stop())
        await world.clock.advance(seconds=1)
        await stopping

        with pytest.raises(ActionCancelledError):
            await call
        assert world.clock.pending_timers == 0


class TestWaitForRules:
    """One test or more per wait_for rule."""

    async def test_already_true_returns_at_once(self, world: World) -> None:
        """Level-based: no suspension if the expression holds when it is called."""
        world.host.states.set_state("binary_sensor.door", "on")
        automation = await world.started("waiter", SOURCE)

        assert await automation.call_action("wait", {"expr": "binary_sensor.door == 'on'"}) is True
        assert world.clock.now() == DEFAULT_NOW
        assert world.host.states.subscriber_count("binary_sensor.door") == 0

    async def test_becomes_true(self, world: World) -> None:
        """The wait ends when a change makes the expression true."""
        world.host.states.set_state("binary_sensor.door", "off")
        _, call = await waiting(world, "binary_sensor.door == 'on'")
        assert not call.done()

        await world.clock.advance(minutes=30)
        assert not call.done()
        await change(world, "binary_sensor.door", "on")
        assert await call is True
        assert world.log == ["waiting", True]

    async def test_waits_indefinitely_without_a_timeout(self, world: World) -> None:
        """No timeout means no timer at all."""
        world.host.states.set_state("binary_sensor.door", "off")
        _, call = await waiting(world, "binary_sensor.door == 'on'")
        assert world.clock.pending_timers == 0
        await world.clock.advance(days=30)
        assert not call.done()
        await change(world, "binary_sensor.door", "on")
        assert await call is True

    async def test_timeout_returns_false(self, world: World) -> None:
        """When the timeout passes first, the result is False."""
        world.host.states.set_state("binary_sensor.door", "off")
        _, call = await waiting(world, "binary_sensor.door == 'on'", timeout=600)

        await world.clock.advance(seconds=599)
        assert not call.done()
        await world.clock.advance(seconds=1)
        assert await call is False
        assert world.log == ["waiting", False]

    @pytest.mark.parametrize(
        ("timeout", "seconds"), [(600, 600), ("600", 600), ("00:10:00", 600), (0.5, 0.5)]
    )
    async def test_timeout_formats(self, world: World, timeout: Any, seconds: float) -> None:
        """The timeout takes the formats of sleep."""
        _, call = await waiting(world, "binary_sensor.door == 'on'", timeout=timeout)
        await world.clock.advance(seconds=seconds)
        assert await call is False

    async def test_true_before_the_timeout(self, world: World) -> None:
        """Becoming true in time returns True and leaves no timer."""
        world.host.states.set_state("binary_sensor.door", "off")
        _, call = await waiting(world, "binary_sensor.door == 'on'", timeout=600)
        await world.clock.advance(seconds=100)
        await change(world, "binary_sensor.door", "on")

        assert await call is True
        assert world.clock.pending_timers == 0

    async def test_re_evaluated_only_for_referenced_entities(self, world: World) -> None:
        """Changes to other entities do not wake the wait."""
        world.host.states.set_state("binary_sensor.door", "off")
        _, call = await waiting(world, "binary_sensor.door == 'on'")
        assert world.host.states.subscriber_count("binary_sensor.door") == 1
        assert world.host.states.subscriber_count() == 0

        await change(world, "binary_sensor.window", "on")
        await change(world, "sensor.temperature", "30")
        assert not call.done()
        await change(world, "binary_sensor.door", "on")
        assert await call is True

    async def test_attribute_change_re_evaluates(self, world: World) -> None:
        """As for a state trigger, an attribute change is a change."""
        world.host.states.set_state("light.hall", "on", {"brightness": 10})
        _, call = await waiting(world, "light.hall['brightness'] > 100")
        await change(world, "light.hall", "on", brightness=200)
        assert await call is True

    async def test_several_entities(self, world: World) -> None:
        """A change to any referenced entity causes an evaluation."""
        world.host.states.set_state("sensor.indoor", "20")
        world.host.states.set_state("sensor.outdoor", "25")
        _, call = await waiting(world, "sensor.indoor > sensor.outdoor")
        await change(world, "sensor.outdoor", "22")
        assert not call.done()
        await change(world, "sensor.indoor", "23")
        assert await call is True

    async def test_brief_true_is_not_missed(self, world: World) -> None:
        """Each change is evaluated: on and off again before the action runs still ends the wait."""
        world.host.states.set_state("binary_sensor.door", "off")
        _, call = await waiting(world, "binary_sensor.door == 'on'")
        world.host.states.set_state("binary_sensor.door", "on")
        world.host.states.set_state("binary_sensor.door", "off")
        await world.clock.settle()
        assert await call is True

    async def test_unusable_value_is_false(self, world: World) -> None:
        """A missing entity makes the expression false; the wait goes on until it is usable and true."""
        _, call = await waiting(world, "sensor.temperature > 25")
        assert not call.done()

        await change(world, "sensor.temperature", "unavailable")
        await change(world, "sensor.temperature", "unknown")
        assert not call.done()
        await change(world, "sensor.temperature", "30")
        assert await call is True

    async def test_negation_is_false_while_unusable(self, world: World) -> None:
        """not (...) does not become true because the value is unavailable."""
        world.host.states.set_state("sensor.temperature", "30")
        _, call = await waiting(world, "not (sensor.temperature > 25)", timeout=60)
        await change(world, "sensor.temperature", "unavailable")
        assert not call.done()
        await world.clock.advance(seconds=60)
        assert await call is False

    async def test_explicit_wait_for_unavailable(self, world: World) -> None:
        """Comparing with 'unavailable' is usable."""
        world.host.states.set_state("sensor.temperature", "30")
        _, call = await waiting(world, "sensor.temperature == 'unavailable'")
        await change(world, "sensor.temperature", "unavailable")
        assert await call is True

    async def test_invalid_expression_raises_when_called(self, world: World) -> None:
        """AutomationSyntaxError is raised by the call, not when the automation starts."""
        automation = await world.started("waiter", SOURCE)
        assert automation.state is AutomationState.ON

        assert await automation.call_action("bad_expression") == "caught"
        assert world.log[0] == "before"
        assert "Invalid state expression 'sensor.temperature >'" in world.log[1]

    async def test_invalid_expression_reaches_the_caller(self, world: World) -> None:
        """Uncaught, the error is raised to the caller of the action."""
        automation = await world.started("waiter", SOURCE)
        with pytest.raises(AutomationSyntaxError):
            await automation.call_action("wait", {"expr": "temperature > 5"})
        assert world.log == ["waiting", "AutomationSyntaxError"]

    async def test_invalid_timeout(self, world: World) -> None:
        """A timeout that is not a duration raises ValueError."""
        automation = await world.started("waiter", SOURCE)
        with pytest.raises(ValueError, match="haa.wait_for: timeout '10:00' is not valid"):
            await automation.call_action("wait", {"expr": "binary_sensor.door == 'on'", "timeout": "10:00"})

    async def test_counts_towards_the_action_timeout(self, world: World) -> None:
        """A wait without its own timeout is still ended by the action's timeout."""
        automation = await world.started("waiter", SOURCE)
        call = asyncio.create_task(automation.call_action("wait_with_action_timeout"))
        await world.clock.advance(seconds=5)

        with pytest.raises(ActionTimeOutError):
            await call
        assert world.host.states.subscriber_count("binary_sensor.door") == 0

    async def test_cancelled_while_waiting(self, world: World) -> None:
        """Cancelling the action ends the wait; nothing stays subscribed or scheduled."""
        _, call = await waiting(world, "binary_sensor.door == 'on'", timeout=600)
        assert world.host.states.subscriber_count("binary_sensor.door") == 1

        world.dispatcher.cancel_running("waiter", "test")
        with pytest.raises(ActionCancelledError):
            await call
        assert world.log == ["waiting", "CancelledError"]
        assert world.host.states.subscriber_count("binary_sensor.door") == 0
        assert world.clock.pending_timers == 0

    async def test_ends_when_the_automation_is_stopped(self, world: World) -> None:
        """Stopping the automation ends the wait with ActionCancelledError for the caller."""
        automation, call = await waiting(world, "binary_sensor.door == 'on'")
        stopping = asyncio.create_task(automation.stop())
        await world.clock.advance(seconds=1)
        await stopping

        with pytest.raises(ActionCancelledError):
            await call
        assert world.host.states.subscriber_count("binary_sensor.door") == 0

    async def test_waiting_action_holds_its_slot_and_drops_new_requests(self, world: World) -> None:
        """A suspended action is still running: its slot is held and DROP drops new requests."""
        automation, call = await waiting(world, "binary_sensor.door == 'on'")
        assert world.pool.used_slots == 1
        with pytest.raises(ActionDroppedError):
            await automation.call_action("wait", {"expr": "binary_sensor.door == 'on'"})

        await change(world, "binary_sensor.door", "on")
        assert await call is True
        assert world.pool.used_slots == 0

    async def test_cancel_mode_replaces_a_waiting_action(self, world: World) -> None:
        """Long waits combine with CANCEL mode: a new request ends the old wait."""
        automation = await world.started("waiter", SOURCE)
        first = asyncio.create_task(automation.call_action("latest", {"n": 1}))
        await world.clock.settle()
        second = asyncio.create_task(automation.call_action("latest", {"n": 2}))
        await world.clock.settle()

        with pytest.raises(ActionCancelledError):
            await first
        await change(world, "binary_sensor.door", "on")
        assert await second is True
        assert world.log == ["start 1", "start 2", "done 2"]
        assert world.host.states.subscriber_count("binary_sensor.door") == 0


HALL_LIGHT = """
from haanim import haa, on_state

@on_state("binary_sensor.hall_motion == 'on'")
async def hall_light(event):
    await haa.service.light.turn_on(entity_id="light.hall")
    stopped = await haa.wait_for("binary_sensor.hall_motion == 'off'", timeout=600)
    if not stopped:
        log.append("Motion still active after 10 minutes")
    await haa.service.light.turn_off(entity_id="light.hall")
"""


class TestDesignExample:
    """The hall light example of the design."""

    @staticmethod
    async def started(world: World) -> Automation:
        """Start the example with the light services available."""
        world.host.services.register("light", "turn_on")
        world.host.services.register("light", "turn_off")
        return await world.started("hall", HALL_LIGHT)

    @staticmethod
    def calls(world: World) -> list[str]:
        """Return the service calls made so far."""
        return [f"{call.domain}.{call.service}" for call in world.host.services.calls]

    async def test_motion_stops(self, world: World) -> None:
        """Light on with motion, off when motion stops."""
        automation = await self.started(world)
        call = asyncio.create_task(automation.call_action("hall_light"))
        await world.clock.settle()
        assert self.calls(world) == ["light.turn_on"]

        await world.clock.advance(seconds=120)
        await change(world, "binary_sensor.hall_motion", "off")
        await call
        assert self.calls(world) == ["light.turn_on", "light.turn_off"]
        assert world.log == []

    async def test_motion_continues(self, world: World) -> None:
        """After 10 minutes at the latest the light goes off anyway."""
        world.host.states.set_state("binary_sensor.hall_motion", "on")
        automation = await self.started(world)
        call = asyncio.create_task(automation.call_action("hall_light"))
        await world.clock.advance(seconds=600)
        await call

        assert self.calls(world) == ["light.turn_on", "light.turn_off"]
        assert world.log == ["Motion still active after 10 minutes"]
