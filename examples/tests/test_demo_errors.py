"""Tests for the errors demo: who gets a failure, and how the automation handles one."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from haanim import ActionTimeOutError
from haanim.testing import AutomationHarness

DEMO = Path(__file__).parents[1] / "demo_errors"


async def test_card_is_built_at_startup() -> None:
    """The card has the count of failures, a badge, a line for the result and seven buttons."""
    async with AutomationHarness(DEMO, variables={"seen": 2}) as automation:
        buttons = [block["id"] for block in automation.card.blocks if block["type"] == "button"]
        assert buttons == ["fail", "slow", "careful", "patient", "twice", "missing", "arm"]
        assert automation.card.block("seen")["value"] == 2
        assert automation.card.block("status")["text"] == "Nothing yet"


async def test_a_failure_goes_to_the_caller() -> None:
    """An action that raises: the caller gets the exception, nothing is recorded, the automation stays on."""
    async with AutomationHarness(DEMO) as automation:
        with pytest.raises(ValueError, match="This action always fails"):
            await automation.press("fail")
        assert automation.state == "on"
        assert automation.last_error is None
        assert automation.events("haanim_action_error") == []


async def test_a_timeout_goes_to_the_caller() -> None:
    """An action that takes longer than its timeout: the caller gets ActionTimeOutError after two seconds."""
    async with AutomationHarness(DEMO) as automation:
        task = asyncio.ensure_future(automation.call("slow"))
        await automation.advance_time(seconds=3)
        (answer,) = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(answer, ActionTimeOutError)
        assert automation.state == "on"


async def test_catching_an_error() -> None:
    """The automation calls the failing action itself and handles what it raises."""
    async with AutomationHarness(DEMO) as automation:
        assert await automation.press("careful") == "Caught `ValueError`: This action always fails"
        assert automation.card.block("result")["markdown"] == "Caught `ValueError`: This action always fails"
        status = automation.card.block("status")
        assert (status["text"], status["icon"], status["color"]) == ("Handled", "mdi:check", "success")
        assert automation.message == "Caught ValueError: This action always fails"


async def test_catching_a_timeout() -> None:
    """The automation calls the slow action itself and handles the timeout."""
    async with AutomationHarness(DEMO) as automation:
        task = asyncio.ensure_future(automation.call("patient"))
        await automation.advance_time(seconds=3)
        answer = await task
        assert answer.startswith("Caught `ActionTimeOutError`")
        assert automation.card.block("status")["text"] == "Handled"


async def test_a_busy_action_drops_the_second_request() -> None:
    """Asked twice at once, the busy action runs once; the other request is dropped."""
    async with AutomationHarness(DEMO) as automation:
        task = asyncio.ensure_future(automation.call("twice"))
        await automation.advance_time(seconds=4)
        assert await task == "1 finished, 1 dropped with `ActionDroppedError`"


async def test_missing_automation_and_service() -> None:
    """Calling an automation or a service that does not exist raises an error that says so."""
    async with AutomationHarness(DEMO) as automation:
        # In the harness every service exists until the test says otherwise
        automation.remove_service("no_such_domain.no_such_service")
        answer = await automation.press("missing")
        assert "`NonExistingAutomationError`: Automation 'no_such_automation' does not exist" in answer
        assert "`NonExistingServiceError`" in answer
        assert "no_such_domain.no_such_service" in answer


async def test_a_failure_in_a_trigger() -> None:
    """Armed, the trigger fails: the failure is kept, announced, and counted on the card."""
    async with AutomationHarness(DEMO) as automation:
        await automation.advance_time(seconds=11)
        assert automation.last_error is None, "not armed, the trigger does nothing"

        assert await automation.press("arm") == "Armed: the trigger fails within five seconds"
        await automation.advance_time(seconds=6)
        await automation.wait_idle()

        assert automation.state == "on", "the automation keeps running"
        assert automation.last_error is not None
        assert (automation.last_error.action, automation.last_error.error_type) == (
            "watchdog",
            "RuntimeError",
        )
        (event,) = automation.events("haanim_action_error")
        assert event.data["message"] == "The watchdog was armed"

        assert automation.card.block("seen")["value"] == 1
        assert automation.card.block("result")["markdown"] == (
            "`watchdog` failed in a trigger with `RuntimeError`: The watchdog was armed"
        )
        assert automation.card.block("status")["text"] == "Failed"
        assert automation.get_variable("armed") is False

        await automation.advance_time(seconds=11)
        assert automation.card.block("seen")["value"] == 1, "it fails once for each time it is armed"


async def test_trigger_functions_run_by_hand_do_nothing() -> None:
    """Run from the Actions popup, the trigger functions neither fail nor count."""
    async with AutomationHarness(DEMO, variables={"armed": True}) as automation:
        await automation.call("watchdog")
        await automation.call("failure_seen")
        assert automation.card.block("seen")["value"] == 0
        assert automation.get_variable("armed") is True
