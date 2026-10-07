"""Tests for controlling automations: enable, disable, start, stop, restart."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.control import ENABLED_STORAGE_KEY, AutomationControl, EnabledFlags
from haanim.engine.errors import (
    ActionCancelledError,
    AutomationAlreadyRunningError,
    AutomationDisabledError,
    AutomationNotLoadedError,
    AutomationNotRunningError,
    NonExistingAutomationError,
)
from haanim.engine.lifecycle import Automation, AutomationState, load_all, start_all
from haanim.testing import FakeStorage
from tests.engine.test_lifecycle import World

OFF, ON, ERROR, UNAVAILABLE = (
    AutomationState.OFF,
    AutomationState.ON,
    AutomationState.ERROR,
    AutomationState.UNAVAILABLE,
)

SOURCE = """
from haanim import action, startup, shutdown, haa

@startup
def on_start():
    record("start")

@shutdown
def on_stop():
    record("stop")

@action
def ping():
    return "pong"
"""


class ControlWorld(World):
    """A world whose automations are controlled through AutomationControl, as the integration does."""

    def __init__(self, root: Path, storage: FakeStorage | None = None) -> None:
        super().__init__(root)
        self.storage = storage or FakeStorage()
        self.flags = EnabledFlags(self.storage)
        self.control = AutomationControl(self.flags, self.dispatcher)

    def add(self, name: str, source: str, **files: str) -> Automation:
        """Create an automation whose code can call ``record()`` to write to the log."""
        automation = super().add(name, source, **files)
        original = automation.context.execute

        async def execute() -> Any:
            result = await original()
            automation.context.set_symbol("record", self.log.append)
            automation.context.set_symbol("log", self.log)
            return result

        automation.context.execute = execute  # type: ignore[method-assign]
        return automation

    async def in_state(self, state: str, *, enabled: bool = True, name: str = "lights") -> Automation:
        """Create an automation and bring it into a state, enabled or disabled."""
        source = "def broken(:\n" if state == "error" else SOURCE
        automation = self.add(name, source)
        if state != "unavailable":
            await automation.load()
        if state == "on":
            await automation.start()
        if not enabled:
            await self.flags.set_enabled(automation.automation_id, False)
        assert automation.state.value == state
        self.log.clear()
        return automation

    def _get(self, automation_id: str) -> Automation:
        if automation_id not in self.automations:
            raise NonExistingAutomationError(automation_id)
        return self.automations[automation_id]

    # --- The rest of AutomationRegistry, as the integration implements it ---------

    async def async_enable_automation(self, automation_id: str) -> None:
        """Enable an automation."""
        await self.control.enable(self._get(automation_id))

    async def async_disable_automation(self, automation_id: str) -> None:
        """Disable an automation."""
        await self.control.disable(self._get(automation_id))

    async def async_start_automation(self, automation_id: str) -> None:
        """Start an automation."""
        await self.control.start(self._get(automation_id))

    async def async_stop_automation(self, automation_id: str) -> None:
        """Stop an automation."""
        await self.control.stop(self._get(automation_id))

    async def async_restart_automation(self, automation_id: str) -> None:
        """Restart an automation."""
        await self.control.restart(self._get(automation_id))

    def automation_state(self, automation_id: str) -> str:
        """Return the state of an automation."""
        automation = self.automations.get(automation_id)
        return automation.state.value if automation else "unavailable"

    def automation_message(self, automation_id: str) -> str | None:
        """Return the error message of an automation."""
        automation = self.automations.get(automation_id)
        return automation.message if automation else None

    def is_automation_enabled(self, automation_id: str) -> bool:
        """Return whether an automation is enabled."""
        return self.control.is_enabled(automation_id)


@pytest.fixture
def world(tmp_path: Path) -> ControlWorld:
    """A world of controllable automations in a temporary folder."""
    return ControlWorld(tmp_path)


class TestEnabledFlags:
    """The enabled flag is stored per automation ID and survives restarts."""

    async def test_new_automations_are_enabled(self) -> None:
        """An automation never seen before is enabled, with or without stored flags."""
        flags = EnabledFlags(FakeStorage())

        assert flags.is_enabled("lights")
        await flags.load()
        assert flags.is_enabled("lights")

    async def test_set_and_read(self) -> None:
        """A flag that is set is read back; setting reports whether it changed."""
        flags = EnabledFlags(FakeStorage())

        assert await flags.set_enabled("lights", False) is True
        assert not flags.is_enabled("lights")
        assert flags.is_enabled("heating")
        assert await flags.set_enabled("lights", False) is False
        assert await flags.set_enabled("lights", True) is True
        assert flags.is_enabled("lights")
        assert await flags.set_enabled("lights", True) is False

    async def test_survives_a_restart(self) -> None:
        """Flags written by one instance are read by the next, as after a restart of the host."""
        storage = FakeStorage()
        before = EnabledFlags(storage)
        await before.set_enabled("lights", False)
        await before.set_enabled("heating", False)
        await before.set_enabled("heating", True)

        after = EnabledFlags(storage)
        assert after.is_enabled("lights")
        await after.load()

        assert not after.is_enabled("lights")
        assert after.is_enabled("heating")
        assert after.is_enabled("garden")

    async def test_stored_only_when_changed(self) -> None:
        """Setting a flag to the value it has does not write."""
        storage = FakeStorage()
        flags = EnabledFlags(storage)

        await flags.set_enabled("lights", True)
        assert storage.saves == []
        await flags.set_enabled("lights", False)
        await flags.set_enabled("lights", False)
        assert storage.saves == [ENABLED_STORAGE_KEY]
        assert storage.peek(ENABLED_STORAGE_KEY) == {"disabled": ["lights"]}

    async def test_flag_is_kept_for_an_automation_that_is_gone(self) -> None:
        """Nothing removes a flag, so a folder moved away and back keeps it."""
        storage = FakeStorage()
        flags = EnabledFlags(storage)
        await flags.set_enabled("lights", False)
        await flags.set_enabled("heating", False)

        await flags.set_enabled("heating", True)

        assert storage.peek(ENABLED_STORAGE_KEY) == {"disabled": ["lights"]}

    @pytest.mark.parametrize(
        "stored", [None, [], "text", 5, {}, {"disabled": "lights"}, {"disabled": [1, None]}]
    )
    async def test_unusable_stored_data_means_all_enabled(self, stored: Any) -> None:
        """Stored data HAAnim cannot use is ignored rather than failing the start."""
        storage = FakeStorage()
        if stored is not None:
            await storage.save(ENABLED_STORAGE_KEY, stored)
        flags = EnabledFlags(storage)

        await flags.load()

        assert flags.is_enabled("lights")


class TestEnable:
    """enable() marks the automation enabled and starts it; on an enabled automation it does nothing."""

    async def test_enable_a_disabled_automation(self, world: ControlWorld) -> None:
        """A disabled automation is marked enabled and started."""
        automation = await world.in_state("off", enabled=False)

        await world.control.enable(automation)

        assert world.control.is_enabled("lights")
        assert automation.state is ON
        assert world.log == ["start"]
        assert world.storage.peek(ENABLED_STORAGE_KEY) == {"disabled": []}

    @pytest.mark.parametrize("state", ["off", "on", "error"])
    async def test_enable_an_enabled_automation_does_nothing(self, world: ControlWorld, state: str) -> None:
        """Enabling an enabled automation neither starts it nor writes anything."""
        automation = await world.in_state(state)

        await world.control.enable(automation)

        assert automation.state.value == state
        assert world.log == []
        assert world.storage.saves == []

    async def test_enable_a_disabled_automation_in_error(self, world: ControlWorld) -> None:
        """Enabling loads an automation in error again; it starts if the cause is fixed."""
        automation = await world.in_state("error", enabled=False)
        await world.control.enable(automation)
        assert automation.state is ERROR
        assert world.control.is_enabled("lights")

        await world.control.disable(automation)
        world.write("lights", SOURCE)
        await world.control.enable(automation)
        assert automation.state is ON


class TestDisable:
    """disable() stops the automation and marks it disabled; on a disabled automation it does nothing."""

    async def test_disable_a_running_automation(self, world: ControlWorld) -> None:
        """A running automation is stopped, with its @shutdown, and marked disabled."""
        automation = await world.in_state("on")

        await world.control.disable(automation)

        assert not world.control.is_enabled("lights")
        assert automation.state is OFF
        assert world.log == ["stop"]
        assert world.storage.peek(ENABLED_STORAGE_KEY) == {"disabled": ["lights"]}

    @pytest.mark.parametrize("state", ["off", "error"])
    async def test_disable_an_automation_that_is_not_running(self, world: ControlWorld, state: str) -> None:
        """An automation that is not running is only marked."""
        automation = await world.in_state(state)

        await world.control.disable(automation)

        assert not world.control.is_enabled("lights")
        assert automation.state.value == state
        assert world.log == []

    async def test_disable_a_disabled_automation_does_nothing(self, world: ControlWorld) -> None:
        """Disabling twice writes once."""
        automation = await world.in_state("off", enabled=False)
        saves = list(world.storage.saves)

        await world.control.disable(automation)

        assert world.storage.saves == saves
        assert automation.state is OFF

    async def test_disabled_automation_is_loaded_but_never_started(self, world: ControlWorld) -> None:
        """A disabled automation loads, so its errors are visible, and is skipped when starting."""
        disabled = await world.in_state("unavailable", enabled=False, name="alpha")
        enabled = await world.in_state("unavailable", name="beta")

        await load_all([disabled, enabled])
        await start_all([disabled, enabled], world.control.is_enabled)

        assert (disabled.state, enabled.state) == (OFF, ON)

    async def test_disabled_survives_a_restart(self, world: ControlWorld, tmp_path: Path) -> None:
        """After a restart of the host a disabled automation is loaded and not started."""
        automation = await world.in_state("on")
        await world.control.disable(automation)

        restarted = ControlWorld(tmp_path, storage=world.storage)
        await restarted.flags.load()
        again = restarted.add("lights", SOURCE)
        await load_all([again])
        await start_all([again], restarted.control.is_enabled)

        assert again.state is OFF
        assert not restarted.control.is_enabled("lights")
        assert restarted.log == []

        await restarted.control.enable(again)
        assert again.state is ON


class TestStart:
    """start() is temporary: it does not change the enabled flag."""

    async def test_start(self, world: ControlWorld) -> None:
        """A stopped, enabled automation is started."""
        automation = await world.in_state("off")

        await world.control.start(automation)

        assert automation.state is ON
        assert world.storage.saves == []

    @pytest.mark.parametrize("state", ["unavailable", "off", "on", "error"])
    async def test_start_disabled(self, world: ControlWorld, state: str) -> None:
        """A disabled automation cannot be started, whatever state it is in."""
        automation = await world.in_state(state, enabled=False)

        with pytest.raises(AutomationDisabledError) as raised:
            await world.control.start(automation)

        assert raised.value.automation_id == "lights"
        assert automation.state.value == state

    async def test_start_running(self, world: ControlWorld) -> None:
        """A running automation cannot be started again."""
        automation = await world.in_state("on")

        with pytest.raises(AutomationAlreadyRunningError):
            await world.control.start(automation)

    async def test_start_in_error_loads_the_files_again(self, world: ControlWorld) -> None:
        """start() on an automation in error reads its files again before starting."""
        automation = await world.in_state("error")
        world.write("lights", SOURCE)

        await world.control.start(automation)

        assert automation.state is ON
        assert automation.message is None

    async def test_start_in_error_that_is_still_broken(self, world: ControlWorld) -> None:
        """If the files are still wrong the automation stays in error; nothing is raised."""
        automation = await world.in_state("error")

        await world.control.start(automation)

        assert automation.state is ERROR

    async def test_start_unavailable(self, world: ControlWorld) -> None:
        """An automation that is not loaded cannot be started."""
        automation = await world.in_state("unavailable")

        with pytest.raises(AutomationNotLoadedError):
            await world.control.start(automation)


class TestStop:
    """stop() is temporary: it does not change the enabled flag."""

    async def test_stop(self, world: ControlWorld) -> None:
        """A running automation is stopped and stays enabled."""
        automation = await world.in_state("on")

        await world.control.stop(automation)

        assert automation.state is OFF
        assert world.log == ["stop"]
        assert world.control.is_enabled("lights")
        assert world.storage.saves == []

    @pytest.mark.parametrize("state", ["unavailable", "off", "error"])
    async def test_stop_not_running(self, world: ControlWorld, state: str) -> None:
        """An automation that is not running cannot be stopped."""
        automation = await world.in_state(state)

        with pytest.raises(AutomationNotRunningError):
            await world.control.stop(automation)

    @pytest.mark.parametrize("state", ["off", "on", "error"])
    async def test_stop_disabled(self, world: ControlWorld, state: str) -> None:
        """A disabled automation reports that it is disabled, before anything else."""
        automation = await world.in_state(state, enabled=False)

        with pytest.raises(AutomationDisabledError):
            await world.control.stop(automation)

    async def test_stopped_automation_starts_again_at_the_next_restart(
        self, world: ControlWorld, tmp_path: Path
    ) -> None:
        """A stopped but enabled automation is started again when the host restarts."""
        automation = await world.in_state("on")
        await world.control.stop(automation)

        restarted = ControlWorld(tmp_path, storage=world.storage)
        await restarted.flags.load()
        again = restarted.add("lights", SOURCE)
        await load_all([again])
        await start_all([again], restarted.control.is_enabled)

        assert again.state is ON


class TestRestart:
    """restart() stops and starts a running automation."""

    async def test_restart(self, world: ControlWorld) -> None:
        """A running automation is stopped and started, with both handlers, in a fresh namespace."""
        automation = await world.in_state("on")
        automation.context.set_symbol("marker", "old namespace")

        await world.control.restart(automation)

        assert automation.state is ON
        assert world.log == ["stop", "start"]
        assert automation.context.get_symbol("marker") is None
        assert world.storage.saves == []

    @pytest.mark.parametrize("state", ["unavailable", "off", "error"])
    async def test_restart_not_running(self, world: ControlWorld, state: str) -> None:
        """An automation that is not running cannot be restarted."""
        automation = await world.in_state(state)

        with pytest.raises(AutomationNotRunningError):
            await world.control.restart(automation)

        assert automation.state.value == state

    async def test_restart_disabled(self, world: ControlWorld) -> None:
        """A disabled automation cannot be restarted."""
        automation = await world.in_state("off", enabled=False)

        with pytest.raises(AutomationDisabledError):
            await world.control.restart(automation)


SELF_CONTROL = """
from haanim import action, startup, shutdown, haa

@startup
def on_start():
    record("start")

@shutdown
def on_stop():
    record("stop")

@action
async def {name}():
    record("before")
    try:
        await {call}
        record("after")
    finally:
        record("finally")
    record("after finally")
"""


class TestSelfControl:
    """An action that stops, restarts or disables its own automation ends at that call."""

    async def run(self, world: ControlWorld, call: str) -> Automation:
        """Start an automation with an action that makes the call, and call the action."""
        automation = world.add("lights", SELF_CONTROL.format(name="act", call=call))
        await automation.load()
        await automation.start()
        world.log.clear()

        with pytest.raises(ActionCancelledError):
            await automation.call_action("act")
        await world.control.wait_scheduled()
        return automation

    @pytest.mark.parametrize("call", ["haa.stop()", "haa.automation('lights').stop()"], ids=["haa", "proxy"])
    async def test_self_stop(self, world: ControlWorld, call: str) -> None:
        """Statements after the call do not run, finally does, and the automation is stopped."""
        automation = await self.run(world, call)

        assert world.log == ["before", "finally", "stop"]
        assert automation.state is OFF
        assert world.control.is_enabled("lights")

    async def test_self_restart(self, world: ControlWorld) -> None:
        """The automation is stopped and started again; the calling action does not continue."""
        automation = await self.run(world, "haa.restart()")

        assert world.log == ["before", "finally", "stop", "start"]
        assert automation.state is ON

    async def test_self_disable(self, world: ControlWorld) -> None:
        """The automation is stopped and stays disabled."""
        automation = await self.run(world, "haa.disable()")

        assert world.log == ["before", "finally", "stop"]
        assert automation.state is OFF
        assert not world.control.is_enabled("lights")
        with pytest.raises(AutomationDisabledError):
            await world.control.start(automation)

    async def test_no_grace_period_for_the_calling_action(self, world: ControlWorld) -> None:
        """The calling action is ended at once; the stop does not wait out the grace period for it."""
        automation = world.add("lights", SELF_CONTROL.format(name="act", call="haa.stop()"))
        await automation.load()
        await automation.start()
        before = world.clock.now()

        with pytest.raises(ActionCancelledError):
            await automation.call_action("act")
        await world.control.wait_scheduled()

        assert automation.state is OFF
        assert world.clock.now() == before
        assert world.clock.pending_timers == 0

    async def test_other_running_actions_still_get_the_grace_period(self, world: ControlWorld) -> None:
        """Only the calling action is ended at once; the others get the grace period."""
        automation = world.add(
            "lights",
            "from haanim import action, haa\n\n@action\nasync def quit():\n    await haa.stop()\n\n"
            "@action\nasync def work():\n    await haa.sleep(0.3)\n    record('work finished')\n    return 'done'\n",
        )
        await automation.load()
        await automation.start()
        working = asyncio.create_task(automation.call_action("work"))
        await world.clock.settle()

        with pytest.raises(ActionCancelledError):
            await automation.call_action("quit")
        assert automation.state is ON

        await world.clock.advance(seconds=0.3)
        await world.control.wait_scheduled()
        assert await working == "done"
        assert automation.state is OFF

    async def test_stopping_another_automation_waits_and_continues(self, world: ControlWorld) -> None:
        """An action that stops a different automation waits for the stop and then goes on."""
        target = await world.in_state("on", name="heating")
        caller = world.add(
            "lights",
            "from haanim import action, haa\n\n@action\nasync def stop_other():\n"
            "    await haa.automation('heating').stop()\n    record('continued')\n    return haa.automation('heating').state\n",
        )
        await caller.load()
        await caller.start()

        assert await caller.call_action("stop_other") == "off"

        assert world.log == ["stop", "continued"]
        assert (target.state, caller.state) == (OFF, ON)

    async def test_self_stop_cannot_raise_the_state_errors(self, world: ControlWorld) -> None:
        """Called from a running action, stop cannot find the automation disabled or stopped."""
        automation = await self.run(world, "haa.stop()")

        assert "after" not in world.log
        assert automation.last_error is None

    async def test_failure_of_a_scheduled_operation_is_logged(
        self, world: ControlWorld, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Nobody waits for a scheduled restart, so its failure goes to the log."""
        automation = world.add("lights", SELF_CONTROL.format(name="act", call="haa.restart()"))
        await automation.load()
        await automation.start()

        async def broken_start() -> bool:
            raise RuntimeError("cannot start")

        automation.start = broken_start  # type: ignore[method-assign]
        with pytest.raises(ActionCancelledError):
            await automation.call_action("act")
        await world.control.wait_scheduled()

        assert "Scheduled automation control operation failed" in caplog.text
        assert "cannot start" in caplog.text


class TestProxyQueries:
    """A proxy reports the state and the enabled flag of its automation."""

    async def test_state_and_flag_through_haa(self, world: ControlWorld) -> None:
        """An automation sees the others as the lifecycle has them."""
        await world.in_state("on", name="heating")
        await world.in_state("error", name="broken")
        await world.in_state("off", enabled=False, name="paused")
        observer = world.add(
            "lights",
            "from haanim import action, haa\n\n@action\ndef look():\n"
            "    return [(a.id, a.state, a.is_running(), a.is_enabled(), a.error_message) for a in haa.automations()]\n",
        )
        await observer.load()
        await observer.start()

        seen = {entry[0]: entry[1:] for entry in await observer.call_action("look")}

        assert seen["heating"] == ("on", True, True, None)
        assert seen["paused"] == ("off", False, False, None)
        assert seen["lights"] == ("on", True, True, None)
        assert seen["broken"][:3] == ("error", False, True)
        assert seen["broken"][3].startswith("main.py:1: invalid syntax")

    async def test_enable_through_a_proxy(self, world: ControlWorld) -> None:
        """Another automation can enable a disabled one; there is no way to enable oneself."""
        paused = await world.in_state("off", enabled=False, name="paused")
        other = world.add(
            "lights",
            "from haanim import action, haa\n\n@action\nasync def wake():\n    await haa.automation('paused').enable()\n",
        )
        await other.load()
        await other.start()

        await other.call_action("wake")

        assert paused.state is ON
        assert world.control.is_enabled("paused")
