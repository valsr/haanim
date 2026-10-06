"""Tests for the controls demo: what its values, icons, gauges and badges show."""

from __future__ import annotations

from pathlib import Path

from haanim.testing import AutomationHarness

DEMO = Path(__file__).parents[1] / "demo_controls"


async def test_card_is_built_at_startup() -> None:
    """The card has a value, an entity, three icons, three gauges and three badges."""
    async with AutomationHarness(DEMO) as automation:
        kinds = [block["type"] for block in automation.card.blocks]
        assert {
            kind: kinds.count(kind) for kind in ("value", "entity", "icon", "gauge", "badge", "button")
        } == {
            "value": 1,
            "entity": 1,
            "icon": 3,
            "gauge": 3,
            "badge": 3,
            "button": 3,
        }
        assert {"cells": 2, "elements": ["dial", "load"]} in automation.card.layout
        assert automation.card.block("status")["text"] == "Not started"


async def test_elements_that_follow_entities() -> None:
    """The fan's icon and badge, the sun's icon and the dial name the entity they follow."""
    async with AutomationHarness(DEMO) as automation:
        fan = automation.card.block("fan")
        assert (fan["entity_id"], fan["icon"], fan["spin"], fan["follow_entity"]) == (
            "input_boolean.fan",
            "mdi:fan",
            True,
            True,
        )
        assert automation.card.block("sun")["icon"] is None, "the entity's own icon"
        assert automation.card.block("info")["follow_entity"] is False
        assert automation.card.block("fan_state")["entity_id"] == "input_boolean.fan"
        dial = automation.card.block("dial")
        assert (dial["entity_id"], dial["value"], dial["min"], dial["max"], dial["kind"]) == (
            "sensor.temperature",
            None,
            10,
            35,
            "dial",
        )


async def test_work_moves_the_progress() -> None:
    """Every step shows in the value, the bar and the badge."""
    async with AutomationHarness(DEMO) as automation:
        assert await automation.press("work") == 1
        assert automation.card.block("steps")["value"] == 1
        assert automation.card.block("progress")["value"] == 1
        status = automation.card.block("status")
        assert (status["text"], status["icon"], status["color"]) == (
            "Working",
            "mdi:progress-wrench",
            "primary",
        )
        assert automation.card.block("progress")["color"] is None


async def test_colour_follows_the_value() -> None:
    """The automation sets the colour of the bar itself: a warning from seven, success at ten."""
    async with AutomationHarness(DEMO) as automation:
        assert await automation.call("work", steps=7) == 7
        assert automation.card.block("progress")["color"] == "warning"
        assert await automation.call("work", steps=7) == 10, "never more than ten"
        assert automation.card.block("progress")["color"] == "success"
        status = automation.card.block("status")
        assert (status["text"], status["icon"], status["color"]) == ("Done", "mdi:check", "success")


async def test_start_over() -> None:
    """Start over forgets the work, also after a restart."""
    async with AutomationHarness(DEMO, variables={"done": 4}) as automation:
        assert automation.card.block("progress")["value"] == 4
        await automation.press("again")
        assert automation.card.block("progress")["value"] == 0
        assert automation.card.block("status") == {
            "id": "status",
            "type": "badge",
            "text": "Not started",
            "entity_id": None,
            "icon": None,
            "color": "disabled",
        }
        assert automation.get_variable("done") == 0


async def test_fan_button_calls_the_service() -> None:
    """The fan button toggles the fan through its service; the card follows the entity by itself."""
    async with AutomationHarness(DEMO) as automation:
        await automation.press("toggle")
        (call,) = automation.service_calls("input_boolean.toggle")
        assert call.data == {"entity_id": "input_boolean.fan"}
