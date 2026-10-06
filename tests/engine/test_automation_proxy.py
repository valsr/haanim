"""Tests for the automation proxy: haa.automation(), haa.automations() and haa.call().

See "Automation Interaction and Control" and "HAAnimAutomationProxy" in the design.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.action_dispatcher import ActionDispatcher
from haanim.engine.action_pool import ActionWorkerPool
from haanim.engine.automation_status import AutomationStatusManager
from haanim.engine.control import AutomationControl
from haanim.engine.errors import (
    ActionCancelledError,
    ActionDroppedError,
    ActionNotFoundError,
    ActionTimeOutError,
    AutomationNotLoadedError,
    AutomationNotRunningError,
    NonExistingAutomationError,
    PoolExhaustedError,
    QueueFullError,
)
from haanim.engine.haanim_api import HAAnim, HAAnimAutomationProxy
from haanim.testing.fakes import DEFAULT_NOW
from tests.engine.test_control import ControlWorld

TARGET = """
from haanim import ActionMode, action, haa, sleep

raised = []

@action
def send_alert(event):
    return "sent"

@action
def process_data(event):
    return {"source": event.data["source"], "limit": event.data["limit"], "caller": event.caller}

@action(name="Slow one", aliases=["slow"])
async def slow_action(event):
    await sleep(event.data.get("seconds", 60))
    return "done"

@action(execution_mode=ActionMode.QUEUE)
async def queued(event):
    await sleep(60)

@action(timeout=5)
async def timed(event):
    await sleep(60)

@action(disabled=True)
def switched_off(event):
    return "never"

@action
def failing(event):
    error = KeyError("room")
    raised.append(error)
    raise error

@action
async def calls_back(event):
    return await haa.automation("caller").call("relay")

@action
def status(event):
    haa.set_message(event.data["text"])
"""

CALLER = """
from haanim import action, haa

@action
async def relay(event):
    return await haa.automation("target").call("calls_back")

@action
async def local(event):
    return await haa.call("helper", value=20)

@action
def helper(event):
    return event.data["value"] + 1
"""


class ProxyWorld(ControlWorld):
    """Two automations, a caller and a target, with room for two actions and queues of one."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.pool = ActionWorkerPool(
            status_manager=AutomationStatusManager(), clock=self.clock, max_workers=2
        )
        self.dispatcher = ActionDispatcher(self.pool, queue_size=1)
        self.control = AutomationControl(self.flags, self.dispatcher)

    async def setup(self) -> tuple[HAAnim, HAAnimAutomationProxy]:
        """Start both automations; return the caller's haa and its proxy of the target."""
        caller = await self.started("caller", CALLER)
        await self.started("target", TARGET)
        haa = caller.context.get_symbol("haa")
        return haa, haa.automation("target")


@pytest.fixture
async def proxy_world(tmp_path: Path) -> Any:
    """A world for proxy tests; whatever still runs is cancelled afterwards."""
    world = ProxyWorld(tmp_path)
    yield world
    await world.dispatcher.shutdown()


class TestProxyProperties:
    """Every property row of the HAAnimAutomationProxy table."""

    async def test_id(self, proxy_world: ProxyWorld) -> None:
        """id is the automation's unique identifier."""
        _, proxy = await proxy_world.setup()
        assert type(proxy) is HAAnimAutomationProxy
        assert proxy.id == "target"

    async def test_state(self, proxy_world: ProxyWorld) -> None:
        """state is 'on', 'off', 'error' or 'unavailable', read each time."""
        _, proxy = await proxy_world.setup()
        target = proxy_world.automations["target"]
        assert proxy.state == "on"

        await target.stop()
        assert proxy.state == "off"
        await target.unload()
        assert proxy.state == "unavailable"

        broken = proxy_world.add("broken", "def nope(:\n")
        await broken.load()
        haa = proxy_world.automations["caller"].context.get_symbol("haa")
        assert haa.automation("broken").state == "error"

    async def test_message(self, proxy_world: ProxyWorld) -> None:
        """message is the status message the automation set; empty until it sets one."""
        _, proxy = await proxy_world.setup()
        assert proxy.message == ""
        await proxy.call("status", text="Starting task...")
        assert proxy.message == "Starting task..."

    async def test_file_path(self, proxy_world: ProxyWorld) -> None:
        """file_path is the absolute path of the automation's folder."""
        _, proxy = await proxy_world.setup()
        assert proxy.file_path == str(proxy_world.root / "target")
        assert Path(proxy.file_path).is_absolute()
        assert (Path(proxy.file_path) / "main.py").exists()

    async def test_load_time_and_run_time(self, proxy_world: ProxyWorld) -> None:
        """load_time is when it was loaded, run_time when it was last started."""
        target = proxy_world.add("target", TARGET)
        caller = await proxy_world.started("caller", CALLER)
        proxy = caller.context.get_symbol("haa").automation("target")
        assert (proxy.load_time, proxy.run_time) == (None, None)

        await proxy_world.clock.advance(minutes=1)
        await target.load()
        assert (proxy.load_time, proxy.run_time) == (DEFAULT_NOW + timedelta(minutes=1), None)

        await proxy_world.clock.advance(minutes=1)
        await target.start()
        assert proxy.run_time == DEFAULT_NOW + timedelta(minutes=2)
        assert proxy.load_time == DEFAULT_NOW + timedelta(minutes=1)

        await proxy_world.clock.advance(minutes=1)
        await target.stop()
        await target.start()
        assert proxy.run_time == DEFAULT_NOW + timedelta(minutes=3)

    async def test_actions(self, proxy_world: ProxyWorld) -> None:
        """actions lists the action names, a disabled action included."""
        _, proxy = await proxy_world.setup()
        assert sorted(proxy.actions) == [
            "Slow one",
            "calls_back",
            "failing",
            "process_data",
            "queued",
            "send_alert",
            "status",
            "switched_off",
            "timed",
        ]

    async def test_last_action_time(self, proxy_world: ProxyWorld) -> None:
        """last_action_time is when an action of the automation last started executing."""
        _, proxy = await proxy_world.setup()
        assert proxy.last_action_time is None

        await proxy_world.clock.advance(minutes=5)
        await proxy.call("send_alert")
        assert proxy.last_action_time == DEFAULT_NOW + timedelta(minutes=5)

        await proxy_world.clock.advance(minutes=5)
        with pytest.raises(ActionNotFoundError):
            await proxy.call("no_such_action")
        assert proxy.last_action_time == DEFAULT_NOW + timedelta(minutes=5)

    async def test_error_message(self, proxy_world: ProxyWorld) -> None:
        """error_message has the details while the state is 'error', and is None otherwise."""
        haa, proxy = await proxy_world.setup()
        assert proxy.error_message is None

        broken = proxy_world.add("broken", "raise KeyError('boom')\n")
        await broken.load()
        await broken.start()
        assert haa.automation("broken").error_message == "KeyError: 'boom'"

    async def test_is_running(self, proxy_world: ProxyWorld) -> None:
        """is_running() is True if the state is 'on'."""
        _, proxy = await proxy_world.setup()
        assert proxy.is_running() is True
        await proxy_world.automations["target"].stop()
        assert proxy.is_running() is False

    async def test_is_enabled(self, proxy_world: ProxyWorld) -> None:
        """is_enabled() follows the enabled flag."""
        _, proxy = await proxy_world.setup()
        assert proxy.is_enabled() is True
        await proxy.disable()
        assert proxy.is_enabled() is False
        await proxy.enable()
        assert proxy.is_enabled() is True


class TestProxyControl:
    """The control rows of the table."""

    async def test_stop_and_start(self, proxy_world: ProxyWorld) -> None:
        """stop() and start()."""
        _, proxy = await proxy_world.setup()
        await proxy.stop()
        assert proxy.state == "off"
        await proxy.start()
        assert proxy.state == "on"

    async def test_restart(self, proxy_world: ProxyWorld) -> None:
        """restart() stops and starts: run_time moves."""
        _, proxy = await proxy_world.setup()
        before = proxy.run_time
        await proxy_world.clock.advance(seconds=30)
        await proxy.restart()
        assert proxy.state == "on"
        assert proxy.run_time == before + timedelta(seconds=30)

    async def test_disable_and_enable(self, proxy_world: ProxyWorld) -> None:
        """disable() stops and disables; enable() enables and starts."""
        _, proxy = await proxy_world.setup()
        await proxy.disable()
        assert (proxy.state, proxy.is_enabled()) == ("off", False)
        await proxy.enable()
        assert (proxy.state, proxy.is_enabled()) == ("on", True)


class TestAutomations:
    """haa.automation() and haa.automations()."""

    async def test_automations_lists_every_automation(self, proxy_world: ProxyWorld) -> None:
        """One proxy per loaded automation, the caller's own included."""
        haa, _ = await proxy_world.setup()
        proxies = haa.automations()
        assert all(type(proxy) is HAAnimAutomationProxy for proxy in proxies)
        assert sorted(proxy.id for proxy in proxies) == ["caller", "target"]

    async def test_automation_that_does_not_exist(self, proxy_world: ProxyWorld) -> None:
        """haa.automation(id) raises NonExistingAutomationError for an unknown ID."""
        haa, _ = await proxy_world.setup()
        with pytest.raises(NonExistingAutomationError) as exc_info:
            haa.automation("nowhere")
        assert exc_info.value.automation_id == "nowhere"

    async def test_proxy_of_itself(self, proxy_world: ProxyWorld) -> None:
        """An automation can get a proxy of itself."""
        haa, _ = await proxy_world.setup()
        assert haa.automation("caller").id == haa.id == "caller"


class TestCallingActions:
    """The Behaviour list under Calling Actions."""

    async def test_call_returns_the_result(self, proxy_world: ProxyWorld) -> None:
        """The design's first example."""
        _, proxy = await proxy_world.setup()
        assert await proxy.call("send_alert") == "sent"

    async def test_data_and_returned_value(self, proxy_world: ProxyWorld) -> None:
        """The design's second example: data is delivered as event.data, and the caller is named."""
        _, proxy = await proxy_world.setup()
        result = await proxy.call("process_data", source="kitchen", limit=10)
        assert result == {"source": "kitchen", "limit": 10, "caller": "caller"}

    async def test_call_by_alias(self, proxy_world: ProxyWorld) -> None:
        """An action can be called by its name or an alias."""
        _, proxy = await proxy_world.setup()
        calls = [
            asyncio.create_task(proxy.call("Slow one", seconds=1)),
        ]
        await proxy_world.clock.advance(seconds=1)
        assert await calls[0] == "done"
        call = asyncio.create_task(proxy.call("slow", seconds=1))
        await proxy_world.clock.advance(seconds=1)
        assert await call == "done"

    async def test_local_call(self, proxy_world: ProxyWorld) -> None:
        """The design's third example: haa.call() calls an action of the current automation."""
        await proxy_world.setup()
        assert await proxy_world.automations["caller"].call_action("local") == 21

    async def test_each_call_is_a_new_request(self, proxy_world: ProxyWorld) -> None:
        """Each call triggers a new action request."""
        _, proxy = await proxy_world.setup()
        assert [await proxy.call("send_alert") for _ in range(3)] == ["sent"] * 3
        assert proxy_world.dispatcher.is_idle()

    async def test_automation_does_not_exist(self, proxy_world: ProxyWorld) -> None:
        """NonExistingAutomationError if the automation doesn't exist (any more)."""
        haa, proxy = await proxy_world.setup()
        del proxy_world.automations["target"]
        with pytest.raises(NonExistingAutomationError):
            await proxy.call("send_alert")
        with pytest.raises(NonExistingAutomationError):
            haa.automation("target")

    async def test_automation_not_loaded(self, proxy_world: ProxyWorld) -> None:
        """AutomationNotLoadedError if the automation is not loaded."""
        _, proxy = await proxy_world.setup()
        await proxy_world.automations["target"].unload()
        with pytest.raises(AutomationNotLoadedError) as exc_info:
            await proxy.call("send_alert")
        assert exc_info.value.automation_id == "target"

    async def test_automation_stopped(self, proxy_world: ProxyWorld) -> None:
        """AutomationNotRunningError if the automation is stopped."""
        _, proxy = await proxy_world.setup()
        await proxy.stop()
        with pytest.raises(AutomationNotRunningError):
            await proxy.call("send_alert")

    async def test_automation_disabled(self, proxy_world: ProxyWorld) -> None:
        """AutomationNotRunningError if the automation is disabled."""
        _, proxy = await proxy_world.setup()
        await proxy.disable()
        with pytest.raises(AutomationNotRunningError):
            await proxy.call("send_alert")

    async def test_automation_in_error(self, proxy_world: ProxyWorld) -> None:
        """AutomationNotRunningError if the automation is in the error state."""
        haa, _ = await proxy_world.setup()
        broken = proxy_world.add("broken", "raise KeyError('boom')\n")
        await broken.load()
        await broken.start()
        with pytest.raises(AutomationNotRunningError):
            await haa.automation("broken").call("anything")

    async def test_action_does_not_exist(self, proxy_world: ProxyWorld) -> None:
        """ActionNotFoundError if the action doesn't exist."""
        _, proxy = await proxy_world.setup()
        with pytest.raises(ActionNotFoundError) as exc_info:
            await proxy.call("no_such_action")
        assert (exc_info.value.automation_id, exc_info.value.action_name) == ("target", "no_such_action")

    async def test_action_disabled(self, proxy_world: ProxyWorld) -> None:
        """ActionNotFoundError if the action is disabled."""
        _, proxy = await proxy_world.setup()
        with pytest.raises(ActionNotFoundError):
            await proxy.call("switched_off")

    async def test_request_dropped(self, proxy_world: ProxyWorld) -> None:
        """ActionDroppedError if the request is dropped in DROP mode."""
        _, proxy = await proxy_world.setup()
        running = asyncio.create_task(proxy.call("slow"))
        await proxy_world.clock.settle()
        with pytest.raises(ActionDroppedError):
            await proxy.call("slow")
        await proxy_world.clock.advance(seconds=60)
        assert await running == "done"

    async def test_reentrant_call(self, proxy_world: ProxyWorld) -> None:
        """ActionDroppedError for a re-entrant call: caller.relay -> target.calls_back -> caller.relay."""
        await proxy_world.setup()
        with pytest.raises(ActionDroppedError) as exc_info:
            await proxy_world.automations["caller"].call_action("relay")
        assert (exc_info.value.automation_id, exc_info.value.action_name) == ("caller", "relay")
        assert exc_info.value.reason == "re-entrant call"

    async def test_queue_full(self, proxy_world: ProxyWorld) -> None:
        """QueueFullError if the action's queue is full."""
        _, proxy = await proxy_world.setup()
        for _ in range(2):
            asyncio.create_task(proxy.call("queued"))
        await proxy_world.clock.settle()
        with pytest.raises(QueueFullError) as exc_info:
            await proxy.call("queued")
        assert exc_info.value.queue_size == 1

    async def test_action_raises(self, proxy_world: ProxyWorld) -> None:
        """If the action raises an exception, that same exception is raised to the caller."""
        _, proxy = await proxy_world.setup()
        with pytest.raises(KeyError) as exc_info:
            await proxy.call("failing")
        (raised,) = proxy_world.automations["target"].context.get_symbol("raised")
        assert exc_info.value is raised

    async def test_concurrency_limit(self, proxy_world: ProxyWorld) -> None:
        """PoolExhaustedError if the concurrency limit is reached."""
        _, proxy = await proxy_world.setup()
        asyncio.create_task(proxy.call("slow"))
        asyncio.create_task(proxy.call("queued"))
        await proxy_world.clock.settle()
        with pytest.raises(PoolExhaustedError) as exc_info:
            await proxy.call("send_alert")
        assert exc_info.value.max_workers == 2

    async def test_action_times_out(self, proxy_world: ProxyWorld) -> None:
        """ActionTimeOutError if the action times out."""
        _, proxy = await proxy_world.setup()
        call = asyncio.create_task(proxy.call("timed"))
        await proxy_world.clock.advance(seconds=5)
        with pytest.raises(ActionTimeOutError) as exc_info:
            await call
        assert (exc_info.value.action_name, exc_info.value.timeout) == ("timed", 5)

    async def test_action_cancelled(self, proxy_world: ProxyWorld) -> None:
        """ActionCancelledError if the action is cancelled, here by its automation being stopped."""
        _, proxy = await proxy_world.setup()
        call = asyncio.create_task(proxy.call("slow"))
        await proxy_world.clock.settle()
        stopping = asyncio.create_task(proxy_world.automations["target"].stop())
        await proxy_world.clock.advance(seconds=1)
        await stopping
        with pytest.raises(ActionCancelledError):
            await call
