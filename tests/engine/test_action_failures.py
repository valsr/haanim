"""Tests for how failures of actions become visible.

See "Error Propagation" and "Trigger Functions Are Actions" (Trigger-fired
failures) in the design: a failure reaches the caller unchanged, or, when a
trigger called the action and there is no caller, it is logged, kept as
``last_error`` and announced with a ``haanim_action_error`` event.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest

from haanim.const import EVENT_ACTION_ERROR, ActionMode
from haanim.engine.action_dispatcher import ActionDispatcher
from haanim.engine.action_pool import ActionWorkerPool
from haanim.engine.automation_status import AutomationStatusManager
from haanim.engine.callables import as_coroutine_function
from haanim.engine.errors import (
    ActionCancelledError,
    ActionDroppedError,
    ActionNotFoundError,
    HAAnimError,
)
from haanim.engine.lifecycle import ActionFailure, Automation, AutomationState
from haanim.engine.triggers.manager import TriggerManager
from haanim.testing import FakeClock
from haanim.testing.fakes import DEFAULT_NOW
from tests.engine.helpers import automation_file, fire_trigger, load_and_run, make_context
from tests.engine.test_lifecycle import World, world  # noqa: F401  pylint: disable=unused-import

RAISING_SOURCE = """
from haanim import action, haa

raised = []
caught = []

@action
def risky_action(event):
    error = ValueError("Something went wrong")
    raised.append(error)
    raise error

@action
def missing_key(event):
    return {}[event.data["key"]]

@action
async def running_action(event):
    try:
        await haa.call("risky_action")
    except ValueError as e:
        caught.append(e)
        return f"Action failed: {e}"

@action
async def passes_it_on(event):
    return await haa.call("risky_action")
"""

REMOTE_SOURCE = """
from haanim import action, haa

caught = []

@action
async def call_remote(event):
    try:
        await haa.automation("lights").call(event.data.get("action", "risky_action"), **event.data)
    except Exception as e:
        caught.append(e)
        return type(e).__name__
"""


class TestOriginalExceptionReachesTheCaller:
    """The exception object an action raises is the one its caller receives."""

    async def test_same_object_for_a_manual_call(self, world: World) -> None:
        """Calling the action from outside raises the very object the action raised."""
        automation = await world.started("lights", RAISING_SOURCE)

        with pytest.raises(ValueError, match="Something went wrong") as exc_info:
            await automation.call_action("risky_action")

        (raised,) = automation.context.get_symbol("raised")
        assert exc_info.value is raised
        assert type(exc_info.value) is ValueError
        assert exc_info.value.__cause__ is None

    async def test_same_object_inside_the_automation(self, world: World) -> None:
        """The design's example: the calling action catches the action's own ValueError."""
        automation = await world.started("lights", RAISING_SOURCE)

        assert await automation.call_action("running_action") == "Action failed: Something went wrong"
        (raised,) = automation.context.get_symbol("raised")
        (caught,) = automation.context.get_symbol("caught")
        assert caught is raised

    async def test_same_object_in_another_automation(self, world: World) -> None:
        """The exception crosses from one automation to another unchanged."""
        lights = await world.started("lights", RAISING_SOURCE)
        remote = await world.started("remote", REMOTE_SOURCE)

        assert await remote.call_action("call_remote") == "ValueError"
        (raised,) = lights.context.get_symbol("raised")
        (caught,) = remote.context.get_symbol("caught")
        assert caught is raised

    async def test_same_object_through_two_calls(self, world: World) -> None:
        """An exception that passes through an action that does not handle it is still the same object."""
        automation = await world.started("lights", RAISING_SOURCE)

        with pytest.raises(ValueError) as exc_info:
            await automation.call_action("passes_it_on")
        assert exc_info.value is automation.context.get_symbol("raised")[0]

    async def test_builtin_exception_is_not_turned_into_a_haanim_error(self, world: World) -> None:
        """A KeyError stays a KeyError; HAAnim's own errors are for the conditions they name."""
        automation = await world.started("lights", RAISING_SOURCE)

        with pytest.raises(KeyError) as exc_info:
            await automation.call_action("missing_key", {"key": "room"})
        assert not isinstance(exc_info.value, HAAnimError)
        assert exc_info.value.args == ("room",)

    async def test_haanim_errors_keep_their_type(self, world: World) -> None:
        """A missing action is reported as ActionNotFoundError to the calling automation."""
        await world.started("lights", RAISING_SOURCE)
        remote = await world.started("remote", REMOTE_SOURCE)

        assert await remote.call_action("call_remote", {"action": "no_such_action"}) == "ActionNotFoundError"
        (caught,) = remote.context.get_symbol("caught")
        assert type(caught) is ActionNotFoundError

    async def test_a_failed_call_is_not_recorded_on_the_automation(self, world: World) -> None:
        """With a caller to raise to, nothing is written to last_error and no event is fired."""
        automation = await world.started("lights", RAISING_SOURCE)
        with pytest.raises(ValueError):
            await automation.call_action("risky_action")

        assert automation.last_error is None
        assert EVENT_ACTION_ERROR not in world.host.events.fired_types()
        assert automation.state is AutomationState.ON

    async def test_module_level_exception_is_reported_as_it_is(self, world: World) -> None:
        """An exception raised while main.py runs is the automation's error message, unwrapped."""
        automation = world.add("lights", "raise KeyError('boom')\n")
        await automation.load()
        assert not await automation.start()
        assert automation.message == "KeyError: 'boom'"

    async def test_module_level_exception_is_raised_unwrapped(self, tmp_path: Path) -> None:
        """Executing the code directly raises the original exception."""
        path = automation_file(tmp_path, "broken")
        path.write_text("values = [1, 2, 3]\nvalues[10]\n", encoding="utf-8")

        with pytest.raises(IndexError, match="list index out of range") as exc_info:
            await load_and_run(make_context(str(path)))
        assert exc_info.value.__cause__ is None

    async def test_helper_function_raises_the_original_exception(self, tmp_path: Path) -> None:
        """A helper function of the automation raises what it raises."""
        path = automation_file(tmp_path, "helpers")
        path.write_text("def helper():\n    raise LookupError('nothing there')\n", encoding="utf-8")
        context = make_context(str(path))
        await load_and_run(context)

        with pytest.raises(LookupError, match="nothing there") as exc_info:
            await as_coroutine_function(context.get_symbol("helper"))()
        assert type(exc_info.value) is LookupError


TRIGGERED_SOURCE = """
from haanim import ActionMode, action, haa, on_state, sleep

@on_state("sensor.a == 'on'")
def raises():
    raise ValueError("bad value")

@on_state("sensor.a == 'on'")
def raises_without_message():
    raise RuntimeError

@on_state("sensor.a == 'on'")
@action(name="slow", timeout=5)
async def too_slow():
    await sleep(60)

@on_state("sensor.a == 'on'")
async def dropping():
    log.append("dropping started")
    await sleep(60)

@on_state("sensor.a == 'on'")
@action(execution_mode=ActionMode.QUEUE)
async def queueing():
    log.append("queueing started")
    await sleep(60)

@on_state("sensor.a == 'on'")
@action(execution_mode=ActionMode.CANCEL)
async def latest():
    log.append("latest started")
    await sleep(60)

@on_state("sensor.a == 'on'")
def fine():
    log.append("fine")
    return "fine"

@on_state("sensor.a == 'on'")
async def calls_failing():
    await haa.call("raises")
"""

AUTOMATION_LOGGER = "haanim.engine.automation_context.lights"


class TriggerWorld(World):
    """A world with a real trigger manager, room for two concurrent actions and queues of one."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.pool = ActionWorkerPool(
            status_manager=AutomationStatusManager(), clock=self.clock, max_workers=2
        )
        self.dispatcher = ActionDispatcher(self.pool, queue_size=1)
        self.triggers = TriggerManager(self.host, self.dispatcher)  # type: ignore[assignment]

    async def fire(self, func_name: str) -> asyncio.Task[None]:
        """Fire the trigger of a function, as the trigger manager does when its condition is met."""
        manager: Any = self.triggers
        # pylint: disable-next=protected-access
        (trigger_id,) = [
            trigger_id
            for trigger_id in manager.get_trigger_ids()
            if manager.get_trigger(trigger_id).trigger_def.func_name == func_name
        ]
        # pylint: disable-next=protected-access
        task = asyncio.create_task(fire_trigger(manager, trigger_id))
        await self.clock.settle()
        return task

    def errors(self) -> list[dict[str, Any]]:
        """Return the data of every haanim_action_error event fired so far."""
        return [event.data for event in self.host.events.fired if event.event_type == EVENT_ACTION_ERROR]


@pytest.fixture
async def triggered(tmp_path: Path) -> Any:
    """A running automation whose trigger functions fail in the ways the design lists."""
    trigger_world = TriggerWorld(tmp_path)
    automation = await trigger_world.started("lights", TRIGGERED_SOURCE)
    yield trigger_world, automation
    await trigger_world.dispatcher.shutdown()


def check_recorded(
    trigger_world: TriggerWorld,
    automation: Automation,
    caplog: pytest.LogCaptureFixture,
    *,
    action: str,
    error_type: str,
    message: str,
    level: int = logging.ERROR,
) -> None:
    """Assert the three records of a trigger-fired failure: log, last_error and event."""
    failure = automation.last_error
    assert failure == ActionFailure(trigger_world.clock.now(), action, error_type, message)

    assert trigger_world.errors()[-1] == {
        "automation_id": "lights",
        "action": action,
        "error_type": error_type,
        "message": message,
    }

    records = [record for record in caplog.records if record.name == AUTOMATION_LOGGER]
    assert records, "nothing was logged to the automation's logger"
    assert records[-1].levelno == level
    logged = records[-1].getMessage()
    assert action in logged and error_type in logged and message in logged

    assert automation.state is AutomationState.ON
    assert automation.message is None


class TestTriggerFiredFailures:
    """Each kind of failure of an action called by a trigger is logged, recorded and announced."""

    async def test_action_raises(self, triggered: Any, caplog: pytest.LogCaptureFixture) -> None:
        """The action's exception: its type and message are recorded."""
        trigger_world, automation = triggered
        with caplog.at_level(logging.DEBUG):
            await trigger_world.fire("raises")
        check_recorded(
            trigger_world, automation, caplog, action="raises", error_type="ValueError", message="bad value"
        )

    async def test_action_raises_without_a_message(
        self, triggered: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An exception without a message is recorded with an empty message."""
        trigger_world, automation = triggered
        with caplog.at_level(logging.DEBUG):
            await trigger_world.fire("raises_without_message")
        check_recorded(
            trigger_world,
            automation,
            caplog,
            action="raises_without_message",
            error_type="RuntimeError",
            message="",
        )
        assert str(automation.last_error) == "raises_without_message: RuntimeError"

    async def test_action_times_out(self, triggered: Any, caplog: pytest.LogCaptureFixture) -> None:
        """A timeout is recorded under the action's name, not the function's."""
        trigger_world, automation = triggered
        with caplog.at_level(logging.DEBUG):
            firing = await trigger_world.fire("too_slow")
            assert automation.last_error is None
            await trigger_world.clock.advance(seconds=5)
            await firing
        check_recorded(
            trigger_world,
            automation,
            caplog,
            action="slow",
            error_type="ActionTimeOutError",
            message="Action 'slow' in automation 'lights' exceeded timeout of 5s",
        )

    async def test_request_is_dropped(self, triggered: Any, caplog: pytest.LogCaptureFixture) -> None:
        """A fire that DROP mode skips is recorded; it is a warning, not an error."""
        trigger_world, automation = triggered
        with caplog.at_level(logging.DEBUG):
            await trigger_world.fire("dropping")
            assert automation.last_error is None
            await trigger_world.fire("dropping")
        check_recorded(
            trigger_world,
            automation,
            caplog,
            action="dropping",
            error_type="ActionDroppedError",
            message="Action 'dropping' in automation 'lights' was dropped: already executing",
            level=logging.WARNING,
        )
        assert trigger_world.log == ["dropping started"]

    async def test_queue_is_full(self, triggered: Any, caplog: pytest.LogCaptureFixture) -> None:
        """A fire that does not fit in the action's queue is recorded."""
        trigger_world, automation = triggered
        with caplog.at_level(logging.DEBUG):
            await trigger_world.fire("queueing")
            await trigger_world.fire("queueing")
            assert automation.last_error is None
            await trigger_world.fire("queueing")
        check_recorded(
            trigger_world,
            automation,
            caplog,
            action="queueing",
            error_type="QueueFullError",
            message="Queue for action 'queueing' in automation 'lights' is full (max: 1)",
        )

    async def test_concurrency_limit_is_reached(
        self, triggered: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A fire rejected by the concurrency limit is recorded."""
        trigger_world, automation = triggered
        with caplog.at_level(logging.DEBUG):
            await trigger_world.fire("dropping")
            await trigger_world.fire("queueing")
            assert automation.last_error is None
            await trigger_world.fire("fine")
        failure = automation.last_error
        assert failure is not None
        check_recorded(
            trigger_world,
            automation,
            caplog,
            action="fine",
            error_type="PoolExhaustedError",
            message=failure.message,
        )
        assert "Maximum of 2 concurrent actions" in failure.message
        assert "fine" not in trigger_world.log

    async def test_failure_of_an_action_it_called(
        self, triggered: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An exception that propagates out of a called action is the triggered action's failure."""
        trigger_world, automation = triggered
        with caplog.at_level(logging.DEBUG):
            await trigger_world.fire("calls_failing")
        check_recorded(
            trigger_world,
            automation,
            caplog,
            action="calls_failing",
            error_type="ValueError",
            message="bad value",
        )
        assert len(trigger_world.errors()) == 1


class TestWhatIsNotAFailure:
    """Outcomes that are recorded nowhere."""

    async def test_success(self, triggered: Any) -> None:
        """An action that returns leaves no trace."""
        trigger_world, automation = triggered
        await trigger_world.fire("fine")
        assert trigger_world.log == ["fine"]
        assert automation.last_error is None
        assert trigger_world.errors() == []

    async def test_replaced_by_a_newer_cancel_request(self, triggered: Any) -> None:
        """CANCEL mode replacing a running execution is the mode at work, not a failure."""
        trigger_world, automation = triggered
        first = await trigger_world.fire("latest")
        await trigger_world.fire("latest")
        await first

        assert trigger_world.log == ["latest started", "latest started"]
        assert automation.last_error is None
        assert trigger_world.errors() == []

    async def test_cancelled_because_the_automation_stops(self, triggered: Any) -> None:
        """Actions cancelled by stopping the automation are not reported as failures."""
        trigger_world, automation = triggered
        firing = await trigger_world.fire("dropping")
        stopping = asyncio.create_task(automation.stop())
        await trigger_world.clock.advance(seconds=1)
        await stopping
        await firing

        assert automation.state is AutomationState.OFF
        assert automation.last_error is None
        assert trigger_world.errors() == []


class TestLastError:
    """The last_error value of an automation."""

    async def test_empty_until_something_fails(self, triggered: Any) -> None:
        """A freshly started automation has no last error."""
        _, automation = triggered
        assert automation.last_error is None

    async def test_holds_the_most_recent_failure(self, triggered: Any) -> None:
        """A later failure replaces an earlier one, with its own time."""
        trigger_world, automation = triggered
        await trigger_world.fire("raises")
        first = automation.last_error
        await trigger_world.clock.advance(seconds=90)
        await trigger_world.fire("raises_without_message")

        assert first is not None and first.time == DEFAULT_NOW
        assert automation.last_error == ActionFailure(
            trigger_world.clock.now(), "raises_without_message", "RuntimeError", ""
        )
        assert [event["action"] for event in trigger_world.errors()] == ["raises", "raises_without_message"]

    async def test_a_success_does_not_clear_it(self, triggered: Any) -> None:
        """last_error is the most recent failure, however long ago."""
        trigger_world, automation = triggered
        await trigger_world.fire("raises")
        await trigger_world.fire("fine")
        assert automation.last_error is not None and automation.last_error.action == "raises"

    async def test_action_keeps_working_after_a_failure(self, triggered: Any) -> None:
        """The automation stays on and its triggers keep firing."""
        trigger_world, automation = triggered
        for _ in range(3):
            await trigger_world.fire("raises")
        await trigger_world.fire("fine")

        assert len(trigger_world.errors()) == 3
        assert trigger_world.log == ["fine"]
        assert automation.state is AutomationState.ON

    def test_one_line_description(self) -> None:
        """str() of a failure names the action, the error type and the message."""
        failure = ActionFailure(DEFAULT_NOW, "door", "ValueError", "bad value")
        assert str(failure) == "door: ValueError: bad value"


class TestFire:
    """ActionDispatcher.fire: a request with no caller to raise to."""

    @staticmethod
    def dispatcher() -> ActionDispatcher:
        """A dispatcher on a fake clock."""
        return ActionDispatcher(ActionWorkerPool(status_manager=AutomationStatusManager(), clock=FakeClock()))

    async def test_returns_the_result(self) -> None:
        """A successful execution returns its result."""

        async def action() -> str:
            return "done"

        assert await self.dispatcher().fire("auto", "work", action) == "done"

    async def test_reports_to_the_handler_and_raises_nothing(self) -> None:
        """The automation's failure handler gets the action name and the exception object."""
        dispatcher = self.dispatcher()
        reported: list[tuple[str, BaseException]] = []
        dispatcher.set_failure_handler("auto", lambda name, error: reported.append((name, error)))
        error = ValueError("boom")

        async def action() -> None:
            raise error

        assert await dispatcher.fire("auto", "work", action) is None
        assert reported == [("work", error)]
        assert reported[0][1] is error

    async def test_handler_of_another_automation_is_not_told(self) -> None:
        """Failures go to the handler of the automation the action belongs to."""
        dispatcher = self.dispatcher()
        reported: list[str] = []
        dispatcher.set_failure_handler("other", lambda name, error: reported.append(name))

        async def action() -> None:
            raise ValueError("boom")

        await dispatcher.fire("auto", "work", action)
        assert reported == []

    async def test_without_a_handler_the_failure_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """A failure nobody is registered for still leaves a log record."""

        async def action() -> None:
            raise ValueError("boom")

        with caplog.at_level(logging.ERROR, logger="haanim.engine.action_dispatcher"):
            assert await self.dispatcher().fire("auto", "work", action) is None
        assert "Action 'work' of 'auto' failed: ValueError: boom" in caplog.text

    async def test_removed_handler_is_no_longer_told(self) -> None:
        """Setting the handler to None removes it."""
        dispatcher = self.dispatcher()
        reported: list[str] = []
        dispatcher.set_failure_handler("auto", lambda name, error: reported.append(name))
        dispatcher.set_failure_handler("auto", None)
        dispatcher.set_failure_handler("never_set", None)

        async def action() -> None:
            raise ValueError("boom")

        await dispatcher.fire("auto", "work", action)
        assert reported == []

    async def test_own_cancellation_is_not_reported(self) -> None:
        """An execution the dispatcher cancelled is not a failure."""
        dispatcher = self.dispatcher()
        reported: list[str] = []
        dispatcher.set_failure_handler("auto", lambda name, error: reported.append(name))
        started = asyncio.Event()

        async def action() -> None:
            started.set()
            await asyncio.Event().wait()

        firing = asyncio.create_task(dispatcher.fire("auto", "work", action))
        await started.wait()
        dispatcher.cancel_running("auto", "stopped")

        assert await firing is None
        assert reported == []

    async def test_cancellation_of_a_called_action_is_reported(self) -> None:
        """ActionCancelledError that an action lets through from a call it made is that action's failure."""
        dispatcher = self.dispatcher()
        reported: list[tuple[str, BaseException]] = []
        dispatcher.set_failure_handler("auto", lambda name, error: reported.append((name, error)))
        started = asyncio.Event()

        async def inner() -> None:
            started.set()
            await asyncio.Event().wait()

        async def outer() -> None:
            await dispatcher.dispatch("other", "inner", inner)

        firing = asyncio.create_task(dispatcher.fire("auto", "outer", outer))
        await started.wait()
        dispatcher.cancel_running("other", "stopped")

        assert await firing is None
        ((name, error),) = reported
        assert name == "outer"
        assert type(error) is ActionCancelledError and error.action_name == "inner"

    async def test_dropped_request_is_reported(self) -> None:
        """A fire while the action runs in DROP mode is reported as dropped."""
        dispatcher = self.dispatcher()
        reported: list[BaseException] = []
        dispatcher.set_failure_handler("auto", lambda name, error: reported.append(error))
        release = asyncio.Event()

        first = asyncio.create_task(dispatcher.fire("auto", "work", release.wait, mode=ActionMode.DROP))
        await asyncio.sleep(0)
        assert await dispatcher.fire("auto", "work", release.wait, mode=ActionMode.DROP) is None
        release.set()
        await first

        assert [type(error) for error in reported] == [ActionDroppedError]


class TestFailureHandlerLifetime:
    """The automation is told about failures while it runs, and only then."""

    async def test_registered_while_on(self, triggered: Any) -> None:
        """A running automation records the failures of its triggered actions."""
        trigger_world, automation = triggered

        async def failing() -> None:
            raise ValueError("boom")

        await trigger_world.dispatcher.fire("lights", "anything", failing)
        assert automation.last_error is not None and automation.last_error.action == "anything"

    async def test_removed_when_stopped(self, triggered: Any) -> None:
        """After stop, nothing is recorded on the automation any more."""
        trigger_world, automation = triggered
        await automation.stop()

        async def failing() -> None:
            raise ValueError("boom")

        await trigger_world.dispatcher.fire("lights", "anything", failing)
        assert automation.last_error is None
        assert trigger_world.errors() == []

    async def test_removed_when_start_fails(self, tmp_path: Path) -> None:
        """An automation that did not start records nothing."""
        trigger_world = TriggerWorld(tmp_path)
        automation = trigger_world.add(
            "lights",
            "from haanim import startup\n\n@startup\ndef on_start():\n    raise RuntimeError('no')\n",
        )
        await automation.load()
        assert not await automation.start()

        async def failing() -> None:
            raise ValueError("boom")

        await trigger_world.dispatcher.fire("lights", "anything", failing)
        assert automation.last_error is None
        assert trigger_world.errors() == []
