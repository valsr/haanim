"""Tests for the automation lifecycle: load, start, stop, unload."""

from __future__ import annotations

import asyncio
import gc
import weakref
from pathlib import Path
from typing import Any

import pytest

from haanim.const import DEFAULT_SHUTDOWN_TIMEOUT, DEFAULT_STARTUP_TIMEOUT, DEFAULT_STOP_GRACE_PERIOD
from haanim.engine.action_pool import ActionWorkerPool
from haanim.engine.automation_context import AutomationContext
from haanim.engine.automation_status import AutomationStatusManager
from haanim.engine.errors import (
    ActionCancelledError,
    ActionNotFoundError,
    AutomationAlreadyRunningError,
    AutomationNotLoadedError,
    AutomationNotRunningError,
    NonExistingAutomationError,
)
from haanim.engine.lifecycle import (
    Automation,
    AutomationState,
    LifecycleSettings,
    NoTriggers,
    load_all,
    start_all,
    stop_all,
    unload_all,
)
from haanim.testing import FakeClock, LocalFileSystem, make_host
from tests.engine.helpers import automation_file, make_context

OFF, ON, ERROR, UNAVAILABLE = (
    AutomationState.OFF,
    AutomationState.ON,
    AutomationState.ERROR,
    AutomationState.UNAVAILABLE,
)


class RecordingTriggers:
    """A trigger registrar that records what is registered and can be told to fail."""

    def __init__(self) -> None:
        self.registered: list[tuple[str, str]] = []
        self.history: list[tuple[str, str]] = []
        self.fail_on: str | None = None

    async def register_trigger(self, trigger_def: Any, constraints: Any = None) -> str:
        """Record a trigger as active, or fail if told to for its function."""
        if trigger_def.func_name == self.fail_on:
            raise RuntimeError(f"cannot register {trigger_def.func_name}")
        self.registered.append((trigger_def.automation_id, trigger_def.func_name))
        self.history.append(("register", trigger_def.func_name))
        return f"{trigger_def.automation_id}.{trigger_def.func_name}"

    async def unregister_automation_triggers(self, automation_id: str) -> int:
        """Forget the triggers of an automation."""
        mine = [entry for entry in self.registered if entry[0] == automation_id]
        self.registered = [entry for entry in self.registered if entry[0] != automation_id]
        self.history.append(("unregister", automation_id))
        return len(mine)


class World:
    """A set of automations in a temporary folder, sharing a clock, a pool and a registrar."""

    def __init__(self, root: Path, settings: LifecycleSettings | None = None) -> None:
        self.root = root
        self.clock = FakeClock()
        self.host = make_host(files=LocalFileSystem(), clock=self.clock)
        self.pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=self.clock)
        self.triggers = RecordingTriggers()
        self.settings = settings
        self.automations: dict[str, Automation] = {}
        self.log: list[Any] = []

    # --- AutomationRegistry, as far as haa needs it ------------------------------

    def get_all_contexts(self) -> list[AutomationContext]:
        """Return the contexts of all automations."""
        return [automation.context for automation in self.automations.values()]

    def get_context_by_name(self, automation_id: str) -> AutomationContext | None:
        """Return the context of an automation."""
        automation = self.automations.get(automation_id)
        return automation.context if automation else None

    async def async_call_action(
        self,
        automation_id: str,
        action_name: str,
        data: dict[str, Any] | None = None,
        *,
        caller: str | None = None,
    ) -> Any:
        """Call an action through the automation's lifecycle, as the integration does."""
        if automation_id not in self.automations:
            raise NonExistingAutomationError(automation_id)
        return await self.automations[automation_id].call_action(action_name, data, caller=caller)

    # --- Test controls ------------------------------------------------------------

    def write(self, name: str, source: str, **files: str) -> Path:
        """Write an automation's main.py and further files, returning its folder."""
        main = automation_file(self.root, name)
        main.write_text(source, encoding="utf-8")
        for filename, content in files.items():
            (main.parent / filename).write_text(content, encoding="utf-8")
        return main.parent

    def add(self, name: str, source: str, **files: str) -> Automation:
        """Create an automation from source. It is not loaded yet."""
        folder = self.write(name, source, **files)
        context = make_context(
            str(folder), host=self.host, registry=self, storage_path=str(self.root / ".storage")
        )
        automation = Automation(context, pool=self.pool, triggers=self.triggers, settings=self.settings)
        self.automations[automation.automation_id] = automation
        return automation

    async def started(self, name: str, source: str, **files: str) -> Automation:
        """Create, load and start an automation."""
        automation = self.add(name, source, **files)
        assert await automation.load(), automation.message
        assert await automation.start(), automation.message
        self.expose(automation)
        return automation

    def expose(self, automation: Automation) -> None:
        """Give a running automation's code access to the test's log."""
        automation.context.set_symbol("log", self.log)


@pytest.fixture
def world(tmp_path: Path) -> World:
    """A world of automations in a temporary folder."""
    return World(tmp_path)


SIMPLE = """
from haanim import action, startup, shutdown, on_state, haa

executed = ["main"]

@startup
def on_start():
    executed.append("startup")

@shutdown
def on_stop():
    executed.append("shutdown")

@action
def ping():
    return "pong"

@on_state("sensor.a == 'on'")
def on_a():
    pass
"""


class TestStates:
    """The four states and their messages."""

    def test_states_are_the_designs(self) -> None:
        """The state values are the entity states of the design."""
        assert [state.value for state in AutomationState] == ["unavailable", "off", "on", "error"]

    def test_default_time_limits_are_the_designs(self) -> None:
        """30 seconds to start, 10 to shut down, 0.5 of grace."""
        settings = LifecycleSettings()

        assert (settings.startup_timeout, settings.shutdown_timeout, settings.stop_grace_period) == (
            30,
            10,
            0.5,
        )
        assert (DEFAULT_STARTUP_TIMEOUT, DEFAULT_SHUTDOWN_TIMEOUT, DEFAULT_STOP_GRACE_PERIOD) == (30, 10, 0.5)

    def test_new_automation_is_unavailable(self, world: World) -> None:
        """Before it is loaded an automation is unavailable and has no message."""
        automation = world.add("lights", SIMPLE)

        assert automation.state is UNAVAILABLE
        assert automation.message is None
        assert automation.last_error is None
        assert automation.automation_id == "lights"

    async def test_full_cycle(self, world: World) -> None:
        """unavailable -> off -> on -> off -> unavailable."""
        automation = world.add("lights", SIMPLE)
        seen = [automation.state]

        await automation.load()
        seen.append(automation.state)
        await automation.start()
        seen.append(automation.state)
        await automation.stop()
        seen.append(automation.state)
        await automation.unload()
        seen.append(automation.state)

        assert seen == [UNAVAILABLE, OFF, ON, OFF, UNAVAILABLE]
        assert automation.message is None


class TestLoad:
    """Load reads the metadata and checks the files; no automation code is executed."""

    async def test_load_sets_off(self, world: World) -> None:
        """A valid automation is off after loading."""
        automation = world.add("lights", SIMPLE)

        assert await automation.load() is True
        assert automation.state is OFF
        assert automation.message is None

    async def test_no_code_is_executed(self, world: World) -> None:
        """Loading runs neither main.py nor @startup and registers nothing."""
        automation = world.add("lights", SIMPLE)

        await automation.load()

        assert automation.context.is_loaded
        assert not automation.context.is_executed
        assert automation.context.get_symbol("executed") is None
        assert automation.context.get_actions() == []
        assert world.triggers.history == []

    async def test_metadata_is_read(self, world: World) -> None:
        """metadata.json is read at load."""
        automation = world.add("lights", SIMPLE, **{"metadata.json": '{"name": "Lights", "author": "Jane"}'})

        await automation.load()

        metadata = automation.context.get_metadata()
        assert metadata is not None
        assert (metadata.name, metadata.author) == ("Lights", "Jane")

    @pytest.mark.parametrize(
        ("source", "files", "message"),
        [
            ("def broken(:\n", {}, "main.py:1: invalid syntax"),
            ("def gen():\n    yield 1\n", {}, "main.py:2: 'yield' is not supported"),
            ("import os\n", {}, "main.py:1: import of module 'os' is not allowed"),
            ("eval('1')\n", {}, "main.py:1: builtin 'eval' is not available"),
            ("x = 1\n", {"helper.py": "import os\n"}, "helper.py:1: import of module 'os' is not allowed"),
            ("x = 1\n", {"metadata.json": "{"}, "metadata.json:1: not valid JSON"),
            (
                "x = 1\n",
                {"metadata.json": '{"version": 2}'},
                "metadata.json: field 'version' must be a string",
            ),
        ],
        ids=["syntax", "unsupported", "import", "builtin", "other file", "invalid json", "field type"],
    )
    async def test_load_error(self, world: World, source: str, files: dict[str, str], message: str) -> None:
        """Any load error sets the error state with the reason, and loading stops."""
        automation = world.add("lights", source, **files)

        assert await automation.load() is False
        assert automation.state is ERROR
        assert automation.message is not None and automation.message.startswith(message)
        assert not automation.context.is_loaded

    async def test_missing_main(self, world: World) -> None:
        """A folder without main.py is a load error."""
        folder = world.root / "empty"
        folder.mkdir()
        automation = Automation(
            make_context(str(folder), host=world.host), pool=world.pool, triggers=world.triggers
        )

        assert await automation.load() is False
        assert automation.state is ERROR
        assert "has no main.py" in (automation.message or "")

    async def test_load_again_after_fixing(self, world: World) -> None:
        """Loading an automation in error again clears the error once the file is fixed."""
        automation = world.add("lights", "def broken(:\n")
        await automation.load()
        world.write("lights", SIMPLE)

        assert await automation.load() is True
        assert automation.state is OFF
        assert automation.message is None

    async def test_load_while_on_is_refused(self, world: World) -> None:
        """A running automation has to be stopped before it is loaded again."""
        automation = await world.started("lights", SIMPLE)

        with pytest.raises(AutomationAlreadyRunningError):
            await automation.load()
        assert automation.state is ON


class TestStart:
    """Start runs main.py, validates, runs @startup, registers triggers, and sets on."""

    async def test_start_sets_on(self, world: World) -> None:
        """A loaded automation is on after starting."""
        automation = world.add("lights", SIMPLE)
        await automation.load()

        assert await automation.start() is True
        assert automation.state is ON
        assert automation.message is None

    async def test_main_is_executed_and_decorators_collect(self, world: World) -> None:
        """main.py runs top to bottom, which collects the actions and triggers."""
        automation = await world.started("lights", SIMPLE)

        assert automation.context.is_executed
        assert [action.name for action in automation.context.get_actions()] == ["ping", "on_a"]
        assert len(automation.context.get_triggers()) == 1
        assert automation.context.has_startup and automation.context.has_shutdown

    async def test_order_of_the_steps(self, world: World) -> None:
        """main.py, then @startup, then the triggers."""
        automation = world.add(
            "lights",
            "from haanim import startup, on_state\nseen = []\n\n@startup\ndef on_start():\n    seen.append(probe())\n\n"
            "@on_state(\"sensor.a == 'on'\")\ndef on_a():\n    pass\n\nseen.append('main')\n",
        )
        await automation.load()
        original = automation.context.execute

        async def execute_with_probe() -> Any:
            result = await original()
            automation.context.set_symbol("probe", lambda: ("startup", list(world.triggers.registered)))
            return result

        automation.context.execute = execute_with_probe  # type: ignore[method-assign]

        await automation.start()

        assert automation.context.get_symbol("seen") == ["main", ("startup", [])]
        assert world.triggers.registered == [("lights", "on_a")]

    async def test_startup_is_awaited(self, world: World) -> None:
        """Start does not finish, and the automation is not on, until @startup returns."""
        automation = world.add(
            "lights",
            "from haanim import startup, sleep\ndone = []\n\n@startup\nasync def on_start():\n"
            "    await sleep(5)\n    done.append(1)\n",
        )
        await automation.load()

        starting = asyncio.create_task(automation.start())
        await world.clock.advance(seconds=4)
        assert not starting.done()
        assert automation.state is OFF

        await world.clock.advance(seconds=1)
        assert await starting is True
        assert automation.state is ON
        assert automation.context.get_symbol("done") == [1]

    async def test_fresh_namespace_on_every_start(self, world: World) -> None:
        """Module-level state does not survive a stop."""
        automation = await world.started(
            "lights",
            "from haanim import action\ncount = 0\n\n@action\ndef bump():\n    global count\n    count += 1\n    return count\n",
        )
        assert await automation.call_action("bump") == 1
        assert await automation.call_action("bump") == 2

        await automation.stop()
        await automation.start()

        assert await automation.call_action("bump") == 1

    async def test_own_actions_can_be_called_during_startup(self, world: World) -> None:
        """@startup can call the automation's own actions; its triggers are not active yet."""
        automation = world.add(
            "lights",
            "from haanim import action, startup, haa\nresult = []\n\n@action\ndef ping():\n    return 'pong'\n\n"
            "@startup\nasync def on_start():\n    result.append(await haa.call('ping'))\n",
        )
        await automation.load()

        assert await automation.start() is True
        assert automation.context.get_symbol("result") == ["pong"]

    async def test_others_cannot_call_during_startup(self, world: World) -> None:
        """While @startup runs the automation is off for everyone else."""
        automation = world.add(
            "lights",
            "from haanim import action, startup, sleep\n\n@action\ndef ping():\n    return 'pong'\n\n"
            "@startup\nasync def on_start():\n    await sleep(5)\n",
        )
        await automation.load()
        starting = asyncio.create_task(automation.start())
        await world.clock.settle()

        assert automation.state is OFF
        assert not automation.accepts_calls()
        with pytest.raises(AutomationNotRunningError):
            await world.async_call_action("lights", "ping")

        await world.clock.advance(seconds=5)
        await starting
        assert await world.async_call_action("lights", "ping") == "pong"

    async def test_start_unavailable_is_refused(self, world: World) -> None:
        """An automation that is not loaded cannot be started."""
        automation = world.add("lights", SIMPLE)

        with pytest.raises(AutomationNotLoadedError):
            await automation.start()

    async def test_start_while_on_is_refused(self, world: World) -> None:
        """A running automation cannot be started again."""
        automation = await world.started("lights", SIMPLE)

        with pytest.raises(AutomationAlreadyRunningError):
            await automation.start()

    async def test_start_from_error_loads_again(self, world: World) -> None:
        """start() on an automation in error loads it again and starts it."""
        automation = world.add("lights", "def broken(:\n")
        await automation.load()
        assert automation.state is ERROR

        assert await automation.start() is False
        assert automation.state is ERROR

        world.write("lights", SIMPLE)
        assert await automation.start() is True
        assert automation.state is ON
        assert automation.message is None


class TestStartFailure:
    """If any start step fails: namespace discarded, no @shutdown, no triggers, state error."""

    FAILURES = {
        "main.py raises": (
            "from haanim import shutdown, on_state\n\n@shutdown\ndef on_stop():\n    record('shutdown')\n\n"
            "@on_state(\"sensor.a == 'on'\")\ndef on_a():\n    pass\n\nraise KeyError('boom')\n",
            "AutomationRuntimeError: Runtime error: 'boom'",
        ),
        "name not imported": (
            "@action\ndef go():\n    pass\n",
            "AutomationRuntimeError: Runtime error: name 'action' is not defined",
        ),
        "@startup raises": (
            "from haanim import startup, shutdown, on_state\n\n@startup\ndef on_start():\n    raise KeyError('boom')\n\n"
            "@shutdown\ndef on_stop():\n    record('shutdown')\n\n@on_state(\"sensor.a == 'on'\")\ndef on_a():\n    pass\n",
            "@startup failed: KeyError: 'boom'",
        ),
        "@startup raises without a message": (
            "from haanim import startup\n\n@startup\ndef on_start():\n    raise ValueError\n",
            "@startup failed: ValueError",
        ),
    }

    @pytest.mark.parametrize("case", FAILURES)
    async def test_failure(self, world: World, case: str) -> None:
        """The automation ends in error with the reason, with nothing left behind."""
        source, message = self.FAILURES[case]
        automation = world.add("lights", source)
        await automation.load()

        assert await automation.start() is False

        assert automation.state is ERROR
        assert automation.message == message
        assert not automation.context.is_executed
        assert automation.context.get_actions() == []
        assert world.triggers.registered == []
        assert world.log == []

    async def test_startup_timeout(self, world: World) -> None:
        """A @startup that takes longer than the startup timeout fails the start."""
        automation = world.add(
            "lights",
            "from haanim import startup, shutdown, sleep, on_state\nlog = []\n\n@startup\nasync def on_start():\n"
            "    try:\n        await sleep(1000)\n    finally:\n        log.append('cancelled')\n\n"
            "@shutdown\ndef on_stop():\n    log.append('shutdown')\n\n@on_state(\"sensor.a == 'on'\")\ndef on_a():\n    pass\n",
        )
        await automation.load()
        starting = asyncio.create_task(automation.start())
        await world.clock.settle()
        log = automation.context.get_symbol("log")

        await world.clock.advance(seconds=29)
        assert not starting.done()

        await world.clock.advance(seconds=1)
        assert await starting is False
        assert automation.state is ERROR
        assert automation.message == "@startup did not finish within 30 seconds"
        assert log == ["cancelled"]
        assert world.triggers.registered == []
        assert not automation.context.is_executed

    async def test_endless_startup_without_await_times_out(self, world: World) -> None:
        """A @startup that loops forever is ended at a checkpoint by the timeout."""
        automation = world.add(
            "lights",
            "from haanim import startup\n\n@startup\ndef on_start():\n    while True:\n        pass\n",
        )
        world.settings = None
        automation = Automation(
            automation.context,
            pool=world.pool,
            triggers=world.triggers,
            settings=LifecycleSettings(startup_timeout=2),
        )
        await automation.load()
        starting = asyncio.create_task(automation.start())

        await world.clock.advance(seconds=2)

        assert await starting is False
        assert automation.message == "@startup did not finish within 2 seconds"

    async def test_trigger_registration_failure(self, world: World) -> None:
        """If a trigger cannot be registered, those already registered are removed again."""
        world.triggers.fail_on = "second"
        automation = world.add(
            "lights",
            "from haanim import on_state\n\n@on_state(\"sensor.a == 'on'\")\ndef first():\n    pass\n\n"
            "@on_state(\"sensor.b == 'on'\")\ndef second():\n    pass\n",
        )
        await automation.load()

        assert await automation.start() is False

        assert automation.state is ERROR
        assert automation.message == "RuntimeError: cannot register second"
        assert world.triggers.history == [("register", "first"), ("unregister", "lights")]
        assert world.triggers.registered == []

    async def test_cancelled_start_leaves_the_automation_off(self, world: World) -> None:
        """Cancelling a start (not a failure of the automation) cleans up without an error state."""
        automation = world.add(
            "lights",
            "from haanim import startup, sleep\n\n@startup\nasync def on_start():\n    await sleep(5)\n",
        )
        await automation.load()
        starting = asyncio.create_task(automation.start())
        await world.clock.settle()

        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting

        assert automation.state is OFF
        assert not automation.context.is_executed

    async def test_failed_start_can_be_retried(self, world: World) -> None:
        """After a failed start the automation starts once the cause is fixed."""
        automation = world.add("lights", "raise KeyError('boom')\n")
        await automation.load()
        await automation.start()
        assert automation.state is ERROR

        world.write("lights", SIMPLE)
        assert await automation.start() is True
        assert automation.state is ON


RUNNING = """
from haanim import action, shutdown, sleep, on_state, haa

@action
async def work(event):
    seconds = event.data["seconds"]
    log.append("work started")
    try:
        await sleep(seconds)
        log.append("work finished")
        return "finished"
    except BaseException as err:
        log.append("work " + type(err).__name__)
        raise

@action
def ping():
    return "pong"

@shutdown
async def on_stop():
    log.append("shutdown")

@on_state("sensor.a == 'on'")
def on_a():
    pass
"""


class TestStop:
    """Stop unregisters triggers, ends running actions, runs @shutdown, discards the namespace."""

    async def test_stop_sets_off(self, world: World) -> None:
        """A running automation is off after stopping."""
        automation = await world.started("lights", RUNNING)

        await automation.stop()

        assert automation.state is OFF
        assert automation.message is None

    async def test_triggers_are_unregistered(self, world: World) -> None:
        """No trigger of the automation stays registered."""
        automation = await world.started("lights", RUNNING)
        other = await world.started("heating", RUNNING)
        assert sorted(world.triggers.registered) == [("heating", "on_a"), ("lights", "on_a")]

        await automation.stop()

        assert world.triggers.registered == [("heating", "on_a")]
        assert other.state is ON

    async def test_triggers_are_unregistered_before_shutdown(self, world: World) -> None:
        """The order is: triggers, running actions, @shutdown."""
        automation = await world.started("lights", RUNNING)
        automation.context.set_symbol("log", world.triggers.history)

        await automation.stop()

        assert world.triggers.history[-2:] == [("unregister", "lights"), "shutdown"]

    async def test_running_action_finishes_within_the_grace_period(self, world: World) -> None:
        """An action that ends within the grace period is not cancelled, and its caller gets the result."""
        automation = await world.started("lights", RUNNING)
        call = asyncio.create_task(automation.call_action("work", {"seconds": 0.3}))
        await world.clock.settle()

        stopping = asyncio.create_task(automation.stop())
        await world.clock.advance(seconds=0.3)
        await stopping

        assert await call == "finished"
        assert world.log == ["work started", "work finished", "shutdown"]

    async def test_running_action_is_cancelled_after_the_grace_period(self, world: World) -> None:
        """An action still running after the grace period is cancelled; its caller gets ActionCancelledError."""
        automation = await world.started("lights", RUNNING)
        call = asyncio.create_task(automation.call_action("work", {"seconds": 100}))
        await world.clock.settle()

        stopping = asyncio.create_task(automation.stop())
        await world.clock.advance(seconds=0.4)
        assert not stopping.done()
        assert world.log == ["work started"]

        await world.clock.advance(seconds=0.1)
        await stopping

        with pytest.raises(ActionCancelledError):
            await call
        assert world.log == ["work started", "work CancelledError", "shutdown"]
        assert automation.state is OFF

    async def test_calls_into_other_automations_are_not_cancelled(self, world: World) -> None:
        """A call a cancelled action already made into another automation runs to completion there."""
        await world.started("heating", RUNNING)
        caller = await world.started(
            "lights",
            "from haanim import action, haa\n\n@action\nasync def relay():\n"
            "    other = haa.automation('heating')\n    return await other.call('work', seconds=3)\n",
        )
        call = asyncio.create_task(caller.call_action("relay"))
        await world.clock.settle()
        assert world.log == ["work started"]

        stopping = asyncio.create_task(caller.stop())
        await world.clock.advance(seconds=1)
        await stopping
        with pytest.raises(ActionCancelledError):
            await call

        await world.clock.advance(seconds=2)
        assert world.log == ["work started", "work finished"]

    async def test_no_new_calls_while_stopping(self, world: World) -> None:
        """Once stopping has begun, actions can no longer be called from outside."""
        automation = await world.started("lights", RUNNING)
        call = asyncio.create_task(automation.call_action("work", {"seconds": 100}))
        await world.clock.settle()
        stopping = asyncio.create_task(automation.stop())
        await world.clock.settle()

        assert not automation.accepts_calls()
        with pytest.raises(AutomationNotRunningError):
            await automation.call_action("ping")
        with pytest.raises(AutomationNotRunningError):
            await automation.stop()

        await world.clock.advance(seconds=1)
        await stopping
        with pytest.raises(ActionCancelledError):
            await call

    async def test_shutdown_is_awaited_and_may_call_own_actions(self, world: World) -> None:
        """@shutdown runs to its end before the automation is off, and can call the automation's actions."""
        automation = await world.started(
            "lights",
            "from haanim import action, shutdown, sleep, haa\n\n@action\ndef ping():\n    return 'pong'\n\n"
            "@shutdown\nasync def on_stop():\n    await sleep(3)\n    log.append(await haa.call('ping'))\n",
        )

        stopping = asyncio.create_task(automation.stop())
        await world.clock.advance(seconds=2)
        assert not stopping.done()
        assert automation.state is ON

        await world.clock.advance(seconds=1)
        await stopping
        assert world.log == ["pong"]
        assert automation.state is OFF

    @pytest.mark.parametrize(
        ("body", "error"),
        [
            ("    raise KeyError('boom')\n", "@shutdown failed: KeyError: 'boom'"),
            ("    raise RuntimeError\n", "@shutdown failed: RuntimeError"),
        ],
        ids=["with message", "without message"],
    )
    async def test_failing_shutdown(self, world: World, body: str, error: str) -> None:
        """A @shutdown that raises is recorded in last_error and stopping continues."""
        automation = await world.started(
            "lights", "from haanim import shutdown, on_state\n\n@shutdown\ndef on_stop():\n" + body
        )

        await automation.stop()

        assert automation.state is OFF
        assert automation.message is None
        assert automation.last_error == error
        assert not automation.context.is_executed

    async def test_shutdown_timeout(self, world: World) -> None:
        """A @shutdown that takes longer than the shutdown timeout is ended and recorded."""
        automation = await world.started(
            "lights",
            "from haanim import shutdown, sleep\n\n@shutdown\nasync def on_stop():\n    try:\n        await sleep(1000)\n"
            "    finally:\n        log.append('cancelled')\n",
        )

        stopping = asyncio.create_task(automation.stop())
        await world.clock.advance(seconds=9)
        assert not stopping.done()

        await world.clock.advance(seconds=1)
        await stopping
        assert automation.state is OFF
        assert automation.last_error == "@shutdown did not finish within 10 seconds"
        assert world.log == ["cancelled"]

    async def test_namespace_is_discarded(self, world: World) -> None:
        """Module-level variables and the automation's haa instance are released."""
        automation = await world.started(
            "lights", "from haanim import haa\n\nclass Thing:\n    pass\n\nthing = Thing()\n"
        )
        references = [weakref.ref(automation.context.get_symbol(name)) for name in ("thing", "haa")]

        await automation.stop()
        gc.collect()

        assert [reference() for reference in references] == [None, None]
        assert not automation.context.is_executed
        assert automation.context.is_loaded

    async def test_actions_cannot_be_called_after_stop(self, world: World) -> None:
        """A stopped automation is not running."""
        automation = await world.started("lights", RUNNING)
        await automation.stop()

        with pytest.raises(AutomationNotRunningError):
            await automation.call_action("ping")

    @pytest.mark.parametrize("state", ["unavailable", "off", "error"])
    async def test_stop_when_not_on_is_refused(self, world: World, state: str) -> None:
        """Only a running automation can be stopped."""
        automation = world.add("lights", "def broken(:\n" if state == "error" else SIMPLE)
        if state != "unavailable":
            await automation.load()
        assert automation.state.value == state

        with pytest.raises(AutomationNotRunningError):
            await automation.stop()

    async def test_stop_without_shutdown_handler(self, world: World) -> None:
        """An automation without @shutdown stops."""
        automation = await world.started("lights", "x = 1\n")

        await automation.stop()

        assert automation.state is OFF
        assert automation.last_error is None

    async def test_action_ignoring_cancellation(self, world: World) -> None:
        """An action that swallows its cancellation does not keep the automation from stopping."""
        automation = await world.started(
            "lights",
            "from haanim import action, sleep\n\n@action\nasync def stubborn():\n    try:\n"
            "        await sleep(100)\n    except BaseException:\n        log.append('ignored')\n"
            "    await sleep(100)\n    log.append('finished anyway')\n",
        )
        call = asyncio.create_task(automation.call_action("stubborn"))
        await world.clock.settle()

        stopping = asyncio.create_task(automation.stop())
        await world.clock.advance(seconds=0.5)
        await world.clock.advance(seconds=0.5)
        await stopping

        assert automation.state is OFF
        assert world.log == ["ignored"]

        await world.clock.advance(seconds=100)
        await call
        assert world.log == ["ignored", "finished anyway"]


class TestUnload:
    """Unload releases the checked code and sets unavailable."""

    async def test_unload_sets_unavailable(self, world: World) -> None:
        """A loaded automation is unavailable after unloading and its code is released."""
        automation = world.add("lights", SIMPLE)
        await automation.load()

        await automation.unload()

        assert automation.state is UNAVAILABLE
        assert not automation.context.is_loaded
        assert automation.context.get_metadata() is None
        assert automation.context.source is None

    async def test_unload_stops_a_running_automation(self, world: World) -> None:
        """Unloading a running automation stops it first, including @shutdown."""
        automation = await world.started("lights", RUNNING)

        await automation.unload()

        assert automation.state is UNAVAILABLE
        assert world.log == ["shutdown"]
        assert world.triggers.registered == []

    async def test_unload_from_error(self, world: World) -> None:
        """An automation in error can be unloaded, which clears the message."""
        automation = world.add("lights", "def broken(:\n")
        await automation.load()

        await automation.unload()

        assert automation.state is UNAVAILABLE
        assert automation.message is None

    async def test_unloaded_automation_can_be_loaded_again(self, world: World) -> None:
        """Unloading is not final."""
        automation = await world.started("lights", SIMPLE)
        await automation.unload()

        assert await automation.load() is True
        assert await automation.start() is True
        assert await automation.call_action("ping") == "pong"

    async def test_storage_is_kept(self, world: World) -> None:
        """Persistent storage survives stop and unload, as for a folder that is removed and put back."""
        source = (
            "from haanim import action, haa\n\n@action\nasync def remember(event):\n"
            "    await haa.set_variable('kept', event.data['value'])\n\n@action\ndef recall():\n    return haa.get_variable('kept')\n"
        )
        automation = await world.started("lights", source)
        await automation.call_action("remember", {"value": "42"})
        await automation.unload()

        again = await world.started("lights", source)

        assert again is not automation
        assert await again.call_action("recall") == "42"


class TestCalls:
    """Actions can be called only while the automation is on."""

    async def test_call_action(self, world: World) -> None:
        """A running automation's action returns its value to the caller."""
        automation = await world.started("lights", RUNNING)

        assert await automation.call_action("ping") == "pong"
        assert automation.accepts_calls()

    async def test_unknown_action(self, world: World) -> None:
        """An unknown action is reported as such, with the automation's ID."""
        automation = await world.started("lights", RUNNING)

        with pytest.raises(ActionNotFoundError) as raised:
            await automation.call_action("missing")

        assert (raised.value.automation_id, raised.value.action_name) == ("lights", "missing")

    @pytest.mark.parametrize("state", ["unavailable", "off", "error"])
    async def test_not_running(self, world: World, state: str) -> None:
        """Calling an action of an automation that is not on raises AutomationNotRunningError."""
        automation = world.add("lights", "def broken(:\n" if state == "error" else RUNNING)
        if state != "unavailable":
            await automation.load()

        with pytest.raises(AutomationNotRunningError) as raised:
            await automation.call_action("ping")

        assert raised.value.automation_id == "lights"
        assert not automation.accepts_calls()


class TestOrder:
    """Automations start one at a time in ascending ID order and stop in descending order."""

    SOURCE = (
        "from haanim import startup, shutdown\n\n@startup\ndef on_start():\n    record('start ' + __name__)\n\n"
        "@shutdown\ndef on_stop():\n    log.append('stop ' + __name__)\n"
    )

    def build(self, world: World, names: list[str]) -> list[Automation]:
        """Create automations whose startup and shutdown write to the world's log."""
        automations = []
        for name in names:
            automation = world.add(name, self.SOURCE)
            original = automation.context.execute

            async def execute(original: Any = original, automation: Automation = automation) -> Any:
                result = await original()
                automation.context.set_symbol("record", world.log.append)
                automation.context.set_symbol("log", world.log)
                return result

            automation.context.execute = execute  # type: ignore[method-assign]
            automations.append(automation)
        return automations

    async def test_start_all_in_ascending_id_order(self, world: World) -> None:
        """Whatever order they are given in, automations start by ascending ID."""
        automations = self.build(world, ["Zeta", "alpha", "Mid", "3d printer"])

        await load_all(automations)
        await start_all(reversed(automations))

        assert world.log == ["start 3d_printer", "start alpha", "start mid", "start zeta"]
        assert all(automation.state is ON for automation in automations)

    async def test_stop_all_in_descending_id_order(self, world: World) -> None:
        """Automations stop by descending ID."""
        automations = self.build(world, ["Zeta", "alpha", "Mid"])
        await load_all(automations)
        await start_all(automations)
        world.log.clear()

        await stop_all(automations)

        assert world.log == ["stop zeta", "stop mid", "stop alpha"]
        assert all(automation.state is OFF for automation in automations)

    async def test_one_at_a_time(self, world: World) -> None:
        """An automation is not started until the one before it has finished starting."""
        slow = world.add(
            "alpha",
            "from haanim import startup, sleep\n\n@startup\nasync def on_start():\n    await sleep(5)\n",
        )
        fast = world.add("beta", "x = 1\n")
        await load_all([slow, fast])

        starting = asyncio.create_task(start_all([fast, slow]))
        await world.clock.advance(seconds=4)
        assert (slow.state, fast.state) == (OFF, OFF)
        assert not fast.context.is_executed

        await world.clock.advance(seconds=1)
        await starting
        assert (slow.state, fast.state) == (ON, ON)

    async def test_startup_can_rely_on_smaller_ids_only(self, world: World) -> None:
        """During @startup, automations with a smaller ID are on; the others raise AutomationNotRunningError."""
        target = "from haanim import action\n\n@action\ndef ping():\n    return 'pong from ' + __name__\n"
        caller = (
            "from haanim import startup, haa, AutomationNotRunningError\nresults = []\n\n@startup\nasync def on_start():\n"
            "    results.append(await haa.automation('alpha').call('ping'))\n    try:\n"
            "        await haa.automation('zeta').call('ping')\n    except AutomationNotRunningError as err:\n"
            "        results.append(str(err))\n"
        )
        automations = [world.add("zeta", target), world.add("mid", caller), world.add("alpha", target)]

        await load_all(automations)
        await start_all(automations)

        assert automations[1].context.get_symbol("results") == [
            "pong from alpha",
            "Automation 'zeta' is not running",
        ]
        assert all(automation.state is ON for automation in automations)

    async def test_start_all_skips_automations_in_error(self, world: World) -> None:
        """An automation that failed to load is not started and does not stop the others."""
        good, bad, also_good = (
            world.add("alpha", "x = 1\n"),
            world.add("beta", "def broken(:\n"),
            world.add("gamma", "x = 1\n"),
        )

        await load_all([good, bad, also_good])
        await start_all([good, bad, also_good])

        assert [automation.state for automation in (good, bad, also_good)] == [ON, ERROR, ON]

    async def test_failed_start_does_not_stop_the_others(self, world: World) -> None:
        """An automation whose @startup fails goes to error; the next one still starts."""
        bad = world.add(
            "alpha", "from haanim import startup\n\n@startup\ndef on_start():\n    raise KeyError('x')\n"
        )
        good = world.add("beta", "x = 1\n")

        await load_all([bad, good])
        await start_all([bad, good])

        assert (bad.state, good.state) == (ERROR, ON)

    async def test_stop_all_skips_automations_that_are_not_on(self, world: World) -> None:
        """Only running automations are stopped."""
        running = await world.started("alpha", "x = 1\n")
        loaded = world.add("beta", "x = 1\n")
        await loaded.load()
        unloaded = world.add("gamma", "x = 1\n")

        await stop_all([running, loaded, unloaded])

        assert [automation.state for automation in (running, loaded, unloaded)] == [OFF, OFF, UNAVAILABLE]

    async def test_load_all_leaves_running_automations_alone(self, world: World) -> None:
        """Loading everything does not disturb an automation that is on."""
        running = await world.started("alpha", "x = 1\n")
        new = world.add("beta", "x = 1\n")

        await load_all([running, new])

        assert (running.state, new.state) == (ON, OFF)

    async def test_unload_all_stops_in_descending_order(self, world: World) -> None:
        """Unloading everything stops running automations by descending ID first."""
        automations = self.build(world, ["alpha", "beta", "gamma"])
        await load_all(automations)
        await start_all(automations)
        world.log.clear()

        await unload_all(automations)

        assert world.log == ["stop gamma", "stop beta", "stop alpha"]
        assert all(automation.state is UNAVAILABLE for automation in automations)


class TestNoTriggers:
    """A host that fires no triggers still runs automations."""

    async def test_automation_with_triggers_starts_and_stops(self, world: World) -> None:
        """Registering with the null registrar succeeds and does nothing."""
        folder = world.write("lights", SIMPLE)
        automation = Automation(
            make_context(str(folder), host=world.host), pool=world.pool, triggers=NoTriggers()
        )

        await automation.load()
        assert await automation.start() is True
        await automation.stop()

        assert automation.state is OFF
