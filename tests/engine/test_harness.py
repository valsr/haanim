"""Tests for the automation harness: ``haanim.testing.AutomationHarness``.

See "Testing User Automations" in the design; one class per capability of its list.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.errors import (
    ActionNotFoundError,
    AutomationNotLoadedError,
    AutomationNotRunningError,
    HAAnimError,
    NonExistingAutomationError,
)
from haanim.events import ActionEvent, AutomationEvent, ManualEvent, StateEvent
from haanim.testing import AutomationCall, AutomationHarness, HarnessCard, HarnessError

SOURCE = """
import logging
from haanim import haa, action, startup, shutdown, on_state, on_event, on_interval, on_time

seen = []

@startup
def build(event):
    haa.card.text("intro", "## Demo")
    haa.card.button("press", label="Press", action="echo", confirm="Sure?", room="hall")
    haa.set_message("ready")

@shutdown
def bye(event):
    haa.set_variable("stopped", True)

@action(aliases=["repeat"])
def echo(event):
    seen.append(event)
    return {"source": event.source, "caller": event.caller, "data": event.data}

@action
def fail(event):
    raise ValueError("bad value")

@action
async def talk(event):
    logging.debug("quiet")
    logging.info("hello %s", "there")
    logging.warning("careful")
    print("printed")

@action
async def notify(event):
    call = await haa.service.notify.mobile_app(message="hi")
    return call.response_data if call.success else call.error

@action
async def weather(event):
    call = await haa.service.weather.get_forecasts(entity_id="weather.home", return_response=True)
    return call.response_data

@action
def has_light(event):
    return haa.service.light.turn_on.name

@action
async def slow(event):
    await haa.sleep(30)
    return "done"

@action
async def ask_other(event):
    other = haa.automation("notifications")
    return [other.state, await other.call("send_message", text="x")]

@action
async def logo(event):
    return [await haa.read_asset("logo.txt", text=True), haa.asset_url("logo.txt")]

@action
def remember(event):
    haa.set_variable("count", haa.get_variable("count", 0) + 1)
    return haa.get_variable("count")

@action
async def stop_myself(event):
    await haa.stop()

@on_state("sensor.temperature > 30")
async def hot(event):
    seen.append(event)
    await haa.service.notify.mobile_app(message=f"hot {event.new_state.state}")

@on_event("doorbell")
def ring(event):
    seen.append(event)

@on_event("explode")
def explode(event):
    raise RuntimeError("boom")

@on_interval("00:10:00")
def tick(event):
    seen.append(event)

@on_time("sunset")
def dusk(event):
    seen.append(haa.now())
"""


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """An automation folder called demo, with one asset on disk."""
    folder = tmp_path / "demo"
    (folder / "assets").mkdir(parents=True)
    (folder / "main.py").write_text(SOURCE, encoding="utf-8")
    (folder / "metadata.json").write_text('{"name": "Demo"}', encoding="utf-8")
    (folder / "assets" / "logo.txt").write_text("from disk", encoding="utf-8")
    return folder


def seen(automation: AutomationHarness) -> list[Any]:
    """Return what the automation's functions recorded."""
    return automation._context.get_symbol("seen")  # pylint: disable=protected-access


class TestLoading:
    """The harness loads an automation exactly as the runtime does."""

    async def test_enter_loads_and_starts(self, folder: Path) -> None:
        """Test entering runs main.py and @startup, and leaving stops and unloads."""
        async with AutomationHarness(folder) as automation:
            assert automation.automation_id == "demo"
            assert automation.state == "on"
            assert automation.error is None
            assert automation.enabled is True
            assert "echo" in automation.actions
            assert automation.message == "ready"
        assert automation.state == "unavailable"
        assert automation.actions == []
        assert automation.get_variable("stopped") is True
        await automation.close()

    async def test_same_import_restrictions(self, tmp_path: Path) -> None:
        """Test an import the runtime refuses is refused, with the runtime's message."""
        folder = tmp_path / "bad"
        folder.mkdir()
        (folder / "main.py").write_text("import subprocess\n", encoding="utf-8")
        with pytest.raises(HAAnimError, match="subprocess"):
            async with AutomationHarness(folder):
                pass

    async def test_import_options(self, tmp_path: Path) -> None:
        """Test the import options of the integration can be given."""
        folder = tmp_path / "imports"
        folder.mkdir()
        (folder / "main.py").write_text(
            "import colorsys\nvalue = colorsys.rgb_to_hsv(1, 0, 0)\n", encoding="utf-8"
        )
        with pytest.raises(HAAnimError, match="colorsys"):
            async with AutomationHarness(folder):
                pass
        async with AutomationHarness(folder, additional_imports=["colorsys"]) as automation:
            assert automation.state == "on"
        async with AutomationHarness(folder, allow_all_imports=True) as automation:
            assert automation.state == "on"

    async def test_failing_start_says_why(self, tmp_path: Path) -> None:
        """Test an automation that cannot start raises with the automation's error."""
        folder = tmp_path / "broken"
        folder.mkdir()
        (folder / "main.py").write_text("raise KeyError('boom')\n", encoding="utf-8")
        with pytest.raises(HAAnimError, match="boom"):
            async with AutomationHarness(folder):
                pass

    async def test_missing_folder(self, tmp_path: Path) -> None:
        """Test a folder without main.py cannot be loaded."""
        with pytest.raises(HAAnimError, match="main.py"):
            async with AutomationHarness(tmp_path / "nothing"):
                pass

    async def test_automation_id_can_be_given(self, folder: Path) -> None:
        """Test the ID can differ from the folder's name."""
        async with AutomationHarness(folder, automation_id="other_name") as automation:
            assert automation.automation_id == "other_name"
            assert (await automation.call("echo"))["source"] == "manual"


class TestLifecycle:
    """Capability: trigger lifecycle steps: load, start, stop, reload, unload."""

    async def test_steps_by_hand(self, folder: Path) -> None:
        """Test each step moves the automation to the state the design gives."""
        async with AutomationHarness(folder, start=False) as automation:
            assert automation.state == "unavailable"
            assert await automation.load() is True
            assert automation.state == "off"
            assert await automation.start() is True
            assert automation.state == "on"
            await automation.stop()
            assert automation.state == "off"
            assert automation.card.blocks == []
            assert await automation.start() is True
            assert await automation.restart() is True
            assert automation.state == "on"
            await automation.unload()
            assert automation.state == "unavailable"

    async def test_reload_reads_the_files_again(self, folder: Path) -> None:
        """Test reload picks up changed code, as hot reload does."""
        async with AutomationHarness(folder) as automation:
            (folder / "main.py").write_text(
                "from haanim import action\n\n@action\ndef fresh(event):\n    return 'new'\n",
                encoding="utf-8",
            )
            assert await automation.reload() is True
            assert automation.actions == ["fresh"]
            assert await automation.call("fresh") == "new"

    async def test_reload_of_broken_code(self, folder: Path) -> None:
        """Test a reload that cannot load leaves the automation in error with the reason."""
        async with AutomationHarness(folder) as automation:
            (folder / "main.py").write_text("def broken(:\n", encoding="utf-8")
            assert await automation.reload() is False
            assert automation.state == "error"
            assert "main.py:1" in automation.error

    async def test_load_error_without_raising(self, tmp_path: Path) -> None:
        """Test with start=False a failing load is inspected, not raised."""
        folder = tmp_path / "broken"
        folder.mkdir()
        (folder / "main.py").write_text("def broken(:\n", encoding="utf-8")
        async with AutomationHarness(folder, start=False) as automation:
            assert await automation.load() is False
            assert automation.state == "error"
            assert await automation.reload() is False

    async def test_automation_controls_itself(self, folder: Path) -> None:
        """Test haa.stop() from an action stops the automation in the harness too."""
        async with AutomationHarness(folder) as automation:
            task = asyncio.ensure_future(automation.call("stop_myself"))
            await automation.advance_time(seconds=1)
            await asyncio.gather(task, return_exceptions=True)
            await automation.wait_idle()
            assert automation.state == "off"


class TestStatesAndEvents:
    """Capability: set entity states/attributes and fire events."""

    async def test_state_trigger(self, folder: Path) -> None:
        """Test a state change fires the trigger with the change as its event."""
        async with AutomationHarness(folder) as automation:
            automation.set_state("sensor.temperature", 25)
            automation.set_state("sensor.temperature", 31, {"unit_of_measurement": "°C"})
            await automation.wait_idle()

            (event,) = seen(automation)
            assert isinstance(event, StateEvent)
            assert event.new_state.state == "31"
            assert event.new_state.attributes == {"unit_of_measurement": "°C"}
            assert automation.get_state("sensor.temperature") == "31"
            assert automation.service_calls("notify.mobile_app")[0].data == {"message": "hot 31"}

    async def test_initial_states(self, folder: Path) -> None:
        """Test states given to the harness exist before the automation starts."""
        states = {"sensor.temperature": "20", "light.a": ("on", {"brightness": 10})}
        async with AutomationHarness(folder, states=states) as automation:
            assert automation.get_state("sensor.temperature") == "20"
            assert automation.states.get("light.a").attributes == {"brightness": 10}
            automation.set_state("sensor.temperature", "35")
            await automation.wait_idle()
            assert len(seen(automation)) == 1

    async def test_remove_state(self, folder: Path) -> None:
        """Test an entity can be removed."""
        async with AutomationHarness(folder, states={"light.a": "on"}) as automation:
            automation.remove_state("light.a")
            assert automation.get_state("light.a") is None

    async def test_fire_event(self, folder: Path) -> None:
        """Test a fired event reaches the event trigger."""
        async with AutomationHarness(folder) as automation:
            automation.fire_event("doorbell", {"button": 1}, user_id="u1")
            await automation.wait_idle()
            (event,) = seen(automation)
            assert event.event_data == {"button": 1}
            assert event.user_id == "u1"
            assert [fired.event_type for fired in automation.events()] == ["doorbell"]
            assert automation.bus.fired_types() == ["doorbell"]


class TestTime:
    """Capability: freeze and advance time (including sunrise/sunset)."""

    async def test_time_stands_still(self, folder: Path) -> None:
        """Test the clock starts at the default Monday noon and only moves when told."""
        async with AutomationHarness(folder) as automation:
            assert automation.now == datetime(2025, 1, 6, 12, 0, tzinfo=timezone.utc)
            await automation.wait_idle()
            assert automation.now == datetime(2025, 1, 6, 12, 0, tzinfo=timezone.utc)

    @pytest.mark.parametrize(
        ("now", "zone", "expected"),
        [
            ("2025-01-06 08:59:00", "UTC", "2025-01-06T08:59:00+00:00"),
            ("2025-07-01 08:00", "Europe/Sofia", "2025-07-01T08:00:00+03:00"),
            ("2025-01-06T08:59:00+02:00", "UTC", "2025-01-06T08:59:00+02:00"),
            (datetime(2025, 3, 1, 7, 30), "UTC", "2025-03-01T07:30:00+00:00"),
            (
                datetime(2025, 3, 1, 7, 30, tzinfo=timezone(timedelta(hours=1))),
                "UTC",
                "2025-03-01T07:30:00+01:00",
            ),
        ],
    )
    async def test_start_time(self, folder: Path, now: Any, zone: str, expected: str) -> None:
        """Test now is taken as text or datetime, in the given zone if it names none."""
        async with AutomationHarness(folder, now=now, time_zone=zone) as automation:
            assert automation.now.isoformat() == expected

    async def test_advance_fires_interval(self, folder: Path) -> None:
        """Test advancing runs everything that falls due on the way, and returns the new time."""
        async with AutomationHarness(folder) as automation:
            moment = await automation.advance_time(minutes=25)
            assert moment == datetime(2025, 1, 6, 12, 25, tzinfo=timezone.utc)
            assert [event.execution_count for event in seen(automation)] == [1, 2]
            assert await automation.advance_time(timedelta(minutes=5)) == moment + timedelta(minutes=5)
            assert len(seen(automation)) == 3

    async def test_sunset(self, folder: Path) -> None:
        """Test a sunset trigger fires at the harness's sunset."""
        async with AutomationHarness(folder, now="2025-01-06 16:59:00", sunset="17:00") as automation:
            await automation.advance_time(minutes=2)
            assert [moment for moment in seen(automation) if isinstance(moment, datetime)] == [
                datetime(2025, 1, 6, 17, 0, tzinfo=timezone.utc)
            ]

    async def test_set_sun(self, folder: Path) -> None:
        """Test the sun's times can be changed for the events that are scheduled from then on."""
        async with AutomationHarness(folder, now="2025-01-06 12:00:00") as automation:
            automation.set_sun(sunset="18:30")
            assert automation.host.sun.next_event("sunset", automation.now).hour == 18
            automation.set_sun(sunrise=None, sunset=None)
            assert automation.host.sun.next_event("sunrise", automation.now) is None

    async def test_wait_idle_needs_time_for_a_sleeping_action(self, folder: Path) -> None:
        """Test wait_idle says so when an action sleeps, and advancing time finishes it."""
        async with AutomationHarness(folder) as automation:
            task = asyncio.ensure_future(automation.call("slow"))
            with pytest.raises(HarnessError, match=r"still running: slow.*advance_time"):
                await automation.wait_idle()
            await automation.advance_time(seconds=30)
            assert await task == "done"
            await automation.wait_idle()


class TestCalls:
    """Capability: call actions directly with a chosen event (source, caller)."""

    async def test_manual_by_default(self, folder: Path) -> None:
        """Test a call is manual, with the keyword arguments as event.data."""
        async with AutomationHarness(folder) as automation:
            assert await automation.call("echo", room="hall", level=2) == {
                "source": "manual",
                "caller": None,
                "data": {"room": "hall", "level": 2},
            }
            assert isinstance(seen(automation)[0], ManualEvent)

    async def test_alias(self, folder: Path) -> None:
        """Test an action is called by its alias."""
        async with AutomationHarness(folder) as automation:
            assert (await automation.call("repeat"))["source"] == "manual"

    async def test_caller(self, folder: Path) -> None:
        """Test a caller makes it a call from another automation."""
        async with AutomationHarness(folder) as automation:
            result = await automation.call("echo", caller="lights", x=1)
            assert result == {"source": "automation", "caller": "lights", "data": {"x": 1}}
            assert isinstance(seen(automation)[0], AutomationEvent)

    async def test_trigger_source(self, folder: Path) -> None:
        """Test source='trigger' calls the action as a trigger does."""
        async with AutomationHarness(folder) as automation:
            assert (await automation.call("echo", source="trigger"))["source"] == "trigger"

    async def test_chosen_event(self, folder: Path) -> None:
        """Test a trigger function can be called with exactly the event the test builds."""
        async with AutomationHarness(folder) as automation:
            automation.set_state("sensor.attic", "40")
            event = StateEvent(
                call_time=automation.now,
                automation_id="demo",
                source="trigger",
                entity_id="sensor.attic",
                old_state=None,
                new_state=automation.states.get("sensor.attic"),
            )
            await automation.call("hot", event=event)
            assert seen(automation) == [event]
            assert automation.service_calls("notify.mobile_app")[0].data == {"message": "hot 40"}

    async def test_what_the_action_raises_reaches_the_test(self, folder: Path) -> None:
        """Test an exception of the action is raised by call, for every kind of call."""
        async with AutomationHarness(folder) as automation:
            with pytest.raises(ValueError, match="bad value"):
                await automation.call("fail")
            with pytest.raises(ValueError, match="bad value"):
                await automation.call("fail", source="trigger")

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [({"source": "automation"}, "needs a caller"), ({"source": "voice"}, "Unknown source 'voice'")],
    )
    async def test_invalid_source(self, folder: Path, kwargs: dict[str, Any], message: str) -> None:
        """Test a source that makes no sense is refused."""
        async with AutomationHarness(folder) as automation:
            with pytest.raises(ValueError, match=message):
                await automation.call("echo", **kwargs)

    async def test_errors_of_the_runtime(self, folder: Path) -> None:
        """Test calls fail as they do in Home Assistant: unknown action, stopped, not loaded."""
        async with AutomationHarness(folder) as automation:
            for kwargs in ({}, {"source": "trigger"}):
                with pytest.raises(ActionNotFoundError):
                    await automation.call("missing", **kwargs)
            await automation.stop()
            for kwargs in ({}, {"source": "trigger"}):
                with pytest.raises(AutomationNotRunningError):
                    await automation.call("echo", **kwargs)
            await automation.unload()
            for kwargs in ({}, {"source": "trigger"}):
                with pytest.raises(AutomationNotLoadedError):
                    await automation.call("echo", **kwargs)


class TestInspection:
    """Capability: inspect service calls, fired events, log records, status message, state and variables."""

    async def test_service_calls(self, folder: Path) -> None:
        """Test every call is recorded, and can be asked for by service."""
        async with AutomationHarness(folder) as automation:
            await automation.call("notify")
            await automation.call("weather")
            assert [f"{call.domain}.{call.service}" for call in automation.service_calls()] == [
                "notify.mobile_app",
                "weather.get_forecasts",
            ]
            assert automation.service_calls("notify.mobile_app")[0].data == {"message": "hi"}
            assert automation.service_calls("light.turn_on") == []
            with pytest.raises(ValueError, match="domain.service"):
                automation.service_calls("notify")

    async def test_log_records(self, folder: Path) -> None:
        """Test everything the automation logs and prints is captured, at every level."""
        async with AutomationHarness(folder) as automation:
            await automation.call("talk")
            assert automation.logs() == ["quiet", "hello there", "careful", "printed"]
            assert automation.logs("WARNING") == ["careful"]
            assert automation.logs(logging.INFO) == ["hello there", "printed"]
            assert [record.levelname for record in automation.log_records] == [
                "DEBUG",
                "INFO",
                "WARNING",
                "INFO",
            ]
        assert logging.getLogger("custom_components.haanim.automation.demo").handlers == []

    async def test_trigger_failure(self, folder: Path) -> None:
        """Test a failing trigger-fired action is visible as last_error, an event and a log record."""
        async with AutomationHarness(folder) as automation:
            assert automation.last_error is None
            automation.fire_event("explode")
            await automation.wait_idle()
            assert automation.state == "on"
            assert automation.last_error.action == "explode"
            assert automation.last_error.error_type == "RuntimeError"
            (event,) = automation.events("haanim_action_error")
            assert event.data["message"] == "boom"
            assert any("boom" in message for message in automation.logs("ERROR"))

    async def test_variables(self, folder: Path) -> None:
        """Test stored variables are read while the automation runs and after it stopped."""
        async with AutomationHarness(folder) as automation:
            assert await automation.call("remember") == 1
            assert automation.get_variable("count") == 1
            assert automation.get_variable("missing", "default") == "default"
            assert automation.variables == {"count": 1}
            await automation.stop()
            assert automation.variables == {"count": 1, "stopped": True}

    async def test_initial_variables(self, folder: Path) -> None:
        """Test variables given to the harness are there when the automation starts."""
        async with AutomationHarness(folder, variables={"count": 41}) as automation:
            assert await automation.call("remember") == 42

    async def test_no_variables(self, tmp_path: Path) -> None:
        """Test an automation that never stored anything has no variables."""
        folder = tmp_path / "plain"
        folder.mkdir()
        (folder / "main.py").write_text("x = 1\n", encoding="utf-8")
        async with AutomationHarness(folder, start=False) as automation:
            assert automation.variables == {}
            assert automation.message is None


class TestServiceStubs:
    """Capability: stub service responses and failures (success=False, missing service)."""

    async def test_every_service_works_by_default(self, folder: Path) -> None:
        """Test a service nobody stubbed exists, succeeds and gives no response."""
        async with AutomationHarness(folder) as automation:
            assert await automation.call("notify") == {}
            assert await automation.call("weather") == {}
            assert await automation.call("has_light") == "turn_on"

    async def test_response(self, folder: Path) -> None:
        """Test a stubbed response is what the automation gets."""
        async with AutomationHarness(folder) as automation:
            automation.stub_service("weather.get_forecasts", response={"weather.home": {"forecast": []}})
            assert await automation.call("weather") == {"weather.home": {"forecast": []}}

    async def test_failure(self, folder: Path) -> None:
        """Test success=False makes the call fail: the automation gets a result with the reason."""
        async with AutomationHarness(folder) as automation:
            automation.stub_service("notify.mobile_app", success=False, reason="phone is off")
            assert "phone is off" in await automation.call("notify")
            assert len(automation.service_calls("notify.mobile_app")) == 1

            automation.stub_service("notify.mobile_app")
            assert await automation.call("notify") == {}

    async def test_missing_service(self, folder: Path) -> None:
        """Test a removed service does not exist for the automation, until it is stubbed again."""
        async with AutomationHarness(folder) as automation:
            automation.remove_service("notify.mobile_app")
            with pytest.raises(HAAnimError):
                await automation.call("notify")
            automation.stub_service("notify.mobile_app")
            assert await automation.call("notify") == {}


class TestOtherAutomations:
    """Calls to other automations, which the harness stubs."""

    async def test_stubbed_automation(self, folder: Path) -> None:
        """Test a stubbed automation exists, is on, and answers its actions."""
        async with AutomationHarness(folder) as automation:
            automation.stub_automation("notifications", send_message=lambda text: f"sent {text}")
            assert await automation.call("ask_other") == ["on", "sent x"]
            assert automation.automation_calls() == [
                AutomationCall("notifications", "send_message", {"text": "x"}, "demo")
            ]
            assert automation.automation_calls("lights") == []
            assert automation.automation_calls("notifications") == automation.automation_calls()

    async def test_stub_values_and_coroutines(self, folder: Path) -> None:
        """Test an action of a stub is a value, a function or a coroutine function."""

        async def later(text: str) -> str:
            return text.upper()

        async with AutomationHarness(folder) as automation:
            automation.stub_automation("notifications", send_message="fixed")
            assert await automation.call("ask_other") == ["on", "fixed"]
            automation.stub_automation("notifications", send_message=later)
            assert await automation.call("ask_other") == ["on", "X"]

    async def test_unknown_automation_and_action(self, folder: Path) -> None:
        """Test an automation or action that was not stubbed does not exist."""
        async with AutomationHarness(folder) as automation:
            with pytest.raises(NonExistingAutomationError):
                await automation.call("ask_other")
            automation.stub_automation("notifications")
            with pytest.raises(ActionNotFoundError):
                await automation.call("ask_other")

    async def test_registry_view(self, folder: Path) -> None:
        """Test what haa sees of the automations: itself and the stubs."""
        async with AutomationHarness(folder) as automation:
            automation.stub_automation("notifications")
            assert [context.automation_id for context in automation.get_all_contexts()] == [
                "demo",
                "notifications",
            ]
            assert automation.get_context_by_name("nobody") is None
            assert automation.get_context_by_name("notifications").get_actions() == []
            assert automation.get_context_by_name("notifications").get_metadata() is None
            assert automation.get_context_by_name("notifications").get_action("x") is None
            assert automation.automation_state("demo") == "on"
            assert automation.automation_state("notifications") == "on"
            assert automation.automation_state("nobody") == "unavailable"
            assert automation.automation_message("demo") is None
            assert automation.automation_message("nobody") is None
            assert automation.is_automation_enabled("demo") is True
            assert automation.automation_times("demo").run_time == automation.now
            assert automation.automation_times("nobody").run_time is None
            with pytest.raises(NonExistingAutomationError):
                await automation.async_call_action("nobody", "x")
            with pytest.raises(NonExistingAutomationError):
                await automation.async_stop_automation("notifications")

    async def test_control_through_the_registry(self, folder: Path) -> None:
        """Test enable, disable, start, stop and restart work on the automation."""
        async with AutomationHarness(folder) as automation:
            await automation.async_disable_automation("demo")
            assert (automation.state, automation.enabled) == ("off", False)
            await automation.async_enable_automation("demo")
            assert (automation.state, automation.enabled) == ("on", True)
            await automation.async_stop_automation("demo")
            assert automation.state == "off"
            await automation.async_start_automation("demo")
            await automation.async_restart_automation("demo")
            assert automation.state == "on"


class TestCard:
    """Capability: inspect card content (automation.card.blocks) and press card buttons."""

    async def test_blocks(self, folder: Path) -> None:
        """Test the card built in @startup is there."""
        async with AutomationHarness(folder) as automation:
            assert [block["id"] for block in automation.card.blocks] == ["intro", "press"]
            assert automation.card.block("intro")["markdown"] == "## Demo"
            assert isinstance(automation.card, HarnessCard)
            assert automation.card_updates[-1] == automation.card.blocks
            with pytest.raises(KeyError):
                automation.card.block("missing")

    async def test_press(self, folder: Path) -> None:
        """Test pressing a button calls its action manually with the button's data."""
        async with AutomationHarness(folder) as automation:
            assert await automation.press("press") == {
                "source": "manual",
                "caller": None,
                "data": {"room": "hall"},
            }

    async def test_press_something_else(self, folder: Path) -> None:
        """Test only a button can be pressed."""
        async with AutomationHarness(folder) as automation:
            with pytest.raises(HarnessError, match="'intro' is a text block, not a button"):
                await automation.press("intro")
            with pytest.raises(KeyError):
                await automation.press("missing")

    async def test_empty_when_stopped(self, folder: Path) -> None:
        """Test the card is empty while the automation is not running."""
        async with AutomationHarness(folder) as automation:
            await automation.stop()
            assert automation.card.blocks == []
            assert automation.card_updates[-1] == []


class TestAssets:
    """Capability: provide assets from the automation's own assets/ folder or from an in-memory mapping."""

    async def test_from_the_folder(self, folder: Path) -> None:
        """Test the files in the folder's assets/ are read."""
        async with AutomationHarness(folder) as automation:
            assert await automation.call("logo") == ["from disk", "/api/haanim/assets/demo/logo.txt"]

    async def test_from_a_mapping(self, folder: Path) -> None:
        """Test assets given to the harness are served, in front of the files on disk."""
        assets = {"logo.txt": "from memory", "icons/bell.png": b"\x89PNG"}
        async with AutomationHarness(folder, assets=assets) as automation:
            assert (await automation.call("logo"))[0] == "from memory"
            haa = automation._context._haa  # pylint: disable=protected-access
            assert await haa.read_asset("icons/bell.png") == b"\x89PNG"
            assert await haa.read_asset("logo.txt") == b"from memory"
            assert haa.asset_url("icons/bell.png") == "/api/haanim/assets/demo/icons/bell.png"
            with pytest.raises(FileNotFoundError):
                await haa.read_asset("icons")
            with pytest.raises(FileNotFoundError):
                await haa.read_asset("nothing.txt")
            assert automation.host.files.size(folder / "assets" / "logo.txt") == len(b"from memory")
            assert automation.host.files.size(folder / "main.py") == len(SOURCE.encode("utf-8"))

    async def test_mapping_without_a_folder_on_disk(self, tmp_path: Path) -> None:
        """Test an automation without an assets/ folder gets its assets from the mapping."""
        folder = tmp_path / "plain"
        folder.mkdir()
        (folder / "main.py").write_text("x = 1\n", encoding="utf-8")
        async with AutomationHarness(folder, assets={"data.json": "[]"}) as automation:
            haa = automation._context._haa  # pylint: disable=protected-access
            assert await haa.read_asset("data.json", text=True) == "[]"


WAITING = """
from haanim import haa, action, startup, shutdown

@startup
async def warm_up(event):
    await haa.sleep(3)
    haa.set_message("warm")

@action
async def wait_forever(event):
    await haa.wait_for("binary_sensor.never == 'on'")

@shutdown
async def cool_down(event):
    await haa.sleep(2)
    haa.set_variable("cooled", True)
"""


class TestLifecycleTakesItsTime:
    """Lifecycle steps that wait for time get it: the harness moves the clock for them."""

    @pytest.fixture
    def waiting(self, tmp_path: Path) -> Path:
        """An automation whose startup and shutdown sleep, with an action that never finishes."""
        folder = tmp_path / "waiting"
        folder.mkdir()
        (folder / "main.py").write_text(WAITING, encoding="utf-8")
        return folder

    async def test_startup_that_sleeps(self, waiting: Path) -> None:
        """Test entering waits for a sleeping @startup by moving the clock, and no further than needed."""
        async with AutomationHarness(waiting, now="2025-01-06 12:00:00") as automation:
            assert automation.message == "warm"
            assert automation.now == datetime(2025, 1, 6, 12, 0, 3, tzinfo=timezone.utc)

    async def test_leaving_with_an_action_still_waiting(self, waiting: Path) -> None:
        """Test leaving the harness stops an action that would wait forever: grace period, then cancel."""
        async with AutomationHarness(waiting) as automation:
            task = asyncio.ensure_future(automation.call("wait_forever"))
            await automation.clock.settle()
            assert not task.done()
        assert automation.state == "unavailable"
        assert automation.get_variable("cooled") is True
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        assert isinstance(result, HAAnimError)

    async def test_stop_moves_the_clock_by_what_it_takes(self, waiting: Path) -> None:
        """Test stop takes the shutdown handler's two seconds and no more."""
        async with AutomationHarness(waiting, now="2025-01-06 12:00:00") as automation:
            before = automation.now
            await automation.stop()
            assert automation.now - before == timedelta(seconds=2)
            assert automation.state == "off"

    async def test_step_without_waiting_leaves_the_clock_alone(self, folder: Path) -> None:
        """Test a lifecycle that waits for nothing moves no time."""
        async with AutomationHarness(folder) as automation:
            start = automation.now
            await automation.restart()
            await automation.reload()
            assert automation.now == start

    async def test_startup_that_never_finishes_fails_at_the_timeout(self, tmp_path: Path) -> None:
        """Test a @startup that waits forever fails the start at the startup timeout, as in Home Assistant."""
        folder = tmp_path / "stuck"
        folder.mkdir()
        (folder / "main.py").write_text(
            "from haanim import haa, startup\n\n@startup\nasync def stuck(event):\n"
            "    await haa.wait_for(\"binary_sensor.never == 'on'\")\n",
            encoding="utf-8",
        )
        async with AutomationHarness(folder, start=False) as automation:
            assert await automation.load() is True
            assert await automation.start() is False
            assert automation.state == "error"
            assert "30" in automation.error

    async def test_step_that_cannot_finish(self, folder: Path) -> None:
        """Test a step that outlasts every limit of the lifecycle is reported, not waited for forever."""
        async with AutomationHarness(folder) as automation:
            with pytest.raises(HarnessError, match="did not finish"):
                await automation._drive(asyncio.Event().wait())  # pylint: disable=protected-access

    async def test_step_that_raises(self, folder: Path) -> None:
        """Test what a step raises reaches the test."""
        async with AutomationHarness(folder) as automation:
            with pytest.raises(AutomationNotRunningError):
                await automation.stop() or await automation.stop()
