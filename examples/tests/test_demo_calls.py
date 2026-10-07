"""Tests for the calls demo: what it reads, which services it calls, and which automations."""

from __future__ import annotations

from pathlib import Path

from haanim.testing import AutomationHarness

DEMO = Path(__file__).parents[1] / "demo_calls"
STATES = {"sensor.temperature": "21.5", "input_number.temperature": "21.5", "input_boolean.fan": "off"}


async def test_card_shows_what_the_automation_reads() -> None:
    """The summary says what the automation read from the entities."""
    async with AutomationHarness(DEMO, states=STATES) as automation:
        assert automation.card.block("summary")["markdown"] == (
            "The automation reads **21.5 °C** (fine) and the fan **off**."
        )
        assert automation.card.block("temperature")["entity_id"] == "sensor.temperature"
        assert {"cells": 3, "elements": ["cooler", "warmer", "toggle"]} in automation.card.layout


async def test_entities_that_are_not_there() -> None:
    """Without the entities the automation still starts, and says what it could not read."""
    async with AutomationHarness(DEMO, states={"sensor.temperature": "unavailable"}) as automation:
        assert automation.card.block("summary")["markdown"] == (
            "The automation reads **unknown** (fine) and the fan **not there**."
        )


async def test_refresh_reads_again() -> None:
    """The summary is what the automation read last; Read again brings it up to date."""
    async with AutomationHarness(DEMO, states=STATES) as automation:
        automation.set_state("input_boolean.fan", "on")
        automation.set_state("sensor.temperature", "24")
        await automation.press("refresh")
        assert automation.card.block("summary")["markdown"] == (
            "The automation reads **24 °C** (fine) and the fan **on**."
        )


async def test_services_change_entities() -> None:
    """Warmer and Cooler call input_number.set_value with the new value; Fan calls input_boolean.toggle."""
    async with AutomationHarness(DEMO, states=STATES) as automation:
        assert await automation.press("warmer") == 22.5
        assert await automation.press("cooler") == 20.5
        assert await automation.call("change_temperature", by=5) == 26.5
        values = [call.data for call in automation.service_calls("input_number.set_value")]
        assert values == [
            {"entity_id": "input_number.temperature", "value": 22.5},
            {"entity_id": "input_number.temperature", "value": 20.5},
            {"entity_id": "input_number.temperature", "value": 26.5},
        ]
        assert automation.message == "Set to 26.5 °C"

        await automation.press("toggle")
        assert automation.service_calls("input_boolean.toggle")[0].data == {"entity_id": "input_boolean.fan"}


async def test_a_service_call_that_fails_is_reported() -> None:
    """A failing service call does not raise: its result says so, and the automation shows it."""
    async with AutomationHarness(DEMO, states=STATES) as automation:
        automation.stub_service("input_number.set_value", success=False)
        await automation.press("warmer")
        assert (automation.message or "").startswith("Could not set it")


async def test_calling_another_automation() -> None:
    """Send a message calls notifications.send_message with data, and shows what it returned."""
    async with AutomationHarness(DEMO, states=STATES) as automation:
        automation.stub_automation("notifications", send_message="sent it")
        assert await automation.press("notify") == "sent it"
        (call,) = automation.automation_calls("notifications")
        assert (call.action, call.caller) == ("send_message", "demo_calls")
        assert call.data == {"text": "Hello from the calls demo", "title": "Demo: calls"}
        assert (
            automation.card.block("answer")["markdown"] == "`notifications.send_message` returned **sent it**"
        )


async def test_another_automation_that_is_not_there() -> None:
    """Without the notifications automation the action says so instead of failing."""
    async with AutomationHarness(DEMO, states=STATES) as automation:
        assert await automation.press("notify") == ""
        assert "There is no `notifications` automation" in automation.card.block("answer")["markdown"]


async def test_the_result_of_another_automations_action() -> None:
    """Count on Basics runs demo_basics.count with a step and shows the count it returns."""
    async with AutomationHarness(DEMO, states=STATES) as automation:
        automation.stub_automation("demo_basics", count=7)
        assert await automation.press("count") == 7
        (call,) = automation.automation_calls("demo_basics")
        assert (call.action, call.data) == ("count", {"step": 1})
        assert automation.card.block("answer")["markdown"] == "`demo_basics.count` returned **7**"


async def test_too_warm_turns_the_fan_on_and_sends_a_message() -> None:
    """Crossing 28 degrees: the fan's service is called and notifications is asked to send a message."""
    async with AutomationHarness(DEMO, states=STATES) as automation:
        automation.stub_automation("notifications", send_message="sent")
        automation.set_state("sensor.temperature", "29")
        await automation.wait_idle()

        assert automation.service_calls("input_boolean.turn_on")[0].data == {"entity_id": "input_boolean.fan"}
        (call,) = automation.automation_calls("notifications")
        assert call.data["text"] == "It is 29 °C: the fan is on"
        assert automation.message == "Warm: fan turned on"
        assert "(warm)" in automation.card.block("summary")["markdown"]
