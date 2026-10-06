"""Tests for the basics demo: what is on its card, and what its buttons do."""

from __future__ import annotations

from pathlib import Path

from haanim.testing import AutomationHarness

DEMO = Path(__file__).parents[1] / "demo_basics"


async def test_card_is_built_at_startup() -> None:
    """The card has a heading, the counter, the last line and a row of four buttons."""
    async with AutomationHarness(DEMO) as automation:
        assert [(block["id"], block["type"]) for block in automation.card.blocks] == [
            ("intro", "text"),
            ("count", "value"),
            ("last", "text"),
            ("add", "button"),
            ("add5", "button"),
            ("reset", "button"),
            ("frame", "button"),
        ]
        assert automation.card.layout[-1] == {"cells": 4, "elements": ["add", "add5", "reset", "frame"]}
        assert automation.card.block("count")["value"] == 0
        assert automation.card.title == "Basics demo"
        assert automation.message == "Card ready"


async def test_count_button_adds_its_step() -> None:
    """A button passes its data to the action, which returns the new count."""
    async with AutomationHarness(DEMO, now="2025-01-06 12:00:00") as automation:
        assert await automation.press("add") == 1
        assert await automation.press("add5") == 6
        assert automation.card.block("count")["value"] == 6
        assert automation.card.block("last")["markdown"] == "Last: **counted 5** at 12:00:00"
        assert automation.card.title == "Basics: 6 pressed"
        assert automation.message == "Counted to 6"
        assert automation.get_variable("count") == 6
        assert "Counted to 6" in automation.logs()


async def test_count_takes_a_step() -> None:
    """The action can be called with another step."""
    async with AutomationHarness(DEMO) as automation:
        assert await automation.call("count", step=5) == 5


async def test_reset_button() -> None:
    """Pressing Reset sets the counter to zero; the button asks first."""
    async with AutomationHarness(DEMO, variables={"count": 9}) as automation:
        assert automation.card.block("count")["value"] == 9
        assert automation.card.block("reset")["confirm"] == "Reset the counter to zero?"
        assert automation.card.title == "Basics: 9 pressed"
        assert await automation.press("reset") == 0
        assert automation.card.block("count")["value"] == 0
        assert automation.card.title == "Basics demo"
        assert automation.message == "Counter reset"


async def test_counter_is_kept_across_a_restart() -> None:
    """The count is stored: after a stop and a start the card shows it again."""
    async with AutomationHarness(DEMO) as automation:
        await automation.press("add5")
        await automation.stop()
        assert automation.card.blocks == []
        await automation.start()
        assert automation.card.block("count")["value"] == 5


async def test_bare_card() -> None:
    """The frame button hides every fixed part of the card, and shows them again."""
    async with AutomationHarness(DEMO) as automation:
        assert await automation.press("frame") is False
        assert not any(automation.card.options.values())
        assert len(automation.card.blocks) == 7, "the content stays"
        assert await automation.press("frame") is True
        assert all(automation.card.options.values())


async def test_events_are_counted() -> None:
    """Every demo_count event adds its step; by hand the step comes from the call."""
    async with AutomationHarness(DEMO) as automation:
        automation.fire_event("demo_count")
        automation.fire_event("demo_count", {"step": 3})
        await automation.wait_idle()
        assert automation.card.block("count")["value"] == 4
        await automation.call("count_event", step=2)
        assert automation.card.block("count")["value"] == 6


async def test_midnight_starts_a_new_day() -> None:
    """At midnight the counter goes back to zero."""
    async with AutomationHarness(DEMO, now="2025-01-06 23:59:00", variables={"count": 7}) as automation:
        await automation.advance_time(minutes=2)
        assert automation.card.block("count")["value"] == 0
        assert automation.message == "New day: counter reset"
