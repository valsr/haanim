"""Tests for the dashboard example: what is on its card, and what its buttons do."""

from __future__ import annotations

from pathlib import Path

from haanim.testing import AutomationHarness

DASHBOARD = Path(__file__).parents[1] / "dashboard"


async def test_card_is_built_at_startup() -> None:
    """The card has its seventeen elements in ten rows, with the logo from the automation's assets."""
    async with AutomationHarness(DASHBOARD) as automation:
        assert [(block["id"], block["type"]) for block in automation.card.blocks] == [
            ("intro", "text"),
            ("logo", "image"),
            ("count", "value"),
            ("uptime", "value"),
            ("goal", "gauge"),
            ("dial", "gauge"),
            ("level", "badge"),
            ("fan_state", "badge"),
            ("presses", "graph"),
            ("sun", "entity"),
            ("temperature", "graph"),
            ("fan", "icon"),
            ("sun_icon", "icon"),
            ("info", "icon"),
            ("add", "button"),
            ("reset", "button"),
            ("frame", "button"),
        ]
        assert automation.card.layout == [
            {"cells": 1, "elements": ["intro"]},
            {"cells": 1, "elements": ["logo"]},
            {"cells": 2, "elements": ["count", "uptime"]},
            {"cells": 2, "elements": ["goal", "dial"]},
            {"cells": 3, "elements": ["level", "fan_state"]},
            {"cells": 1, "elements": ["presses"]},
            {"cells": 1, "elements": ["sun"]},
            {"cells": 1, "elements": ["temperature"]},
            {"cells": 3, "elements": ["fan", "sun_icon", "info"]},
            {"cells": 3, "elements": ["add", "reset", "frame"]},
        ]
        assert automation.card.block("logo")["url"] == "/api/haanim/assets/dashboard/logo.svg"
        assert automation.card.block("count")["value"] == 0
        assert automation.card.title == "Dashboard demo"
        assert automation.message == "Card ready"


async def test_count_button_adds_one() -> None:
    """Pressing Count adds its step to the counter, on the card and in storage."""
    async with AutomationHarness(DASHBOARD) as automation:
        assert await automation.press("add") == 1
        assert await automation.press("add") == 2
        assert automation.card.block("count")["value"] == 2
        assert automation.card.block("goal")["value"] == 2
        assert automation.card.block("level")["text"] == "Counting"
        assert automation.card.title == "Dashboard demo: 2 pressed"
        assert automation.get_variable("count") == 2
        assert "Counted to 2" in automation.logs()


async def test_count_takes_a_step() -> None:
    """The action can be called with another step."""
    async with AutomationHarness(DASHBOARD) as automation:
        assert await automation.call("count", step=5) == 5


async def test_reset_button() -> None:
    """Pressing Reset sets the counter to zero; the button asks first."""
    async with AutomationHarness(DASHBOARD, variables={"count": 9}) as automation:
        assert automation.card.block("count")["value"] == 9
        assert automation.card.block("reset")["confirm"] == "Reset the counter to zero?"
        assert automation.card.title == "Dashboard demo: 9 pressed"
        assert await automation.press("reset") == 0
        assert automation.card.block("count")["value"] == 0
        assert automation.card.title == "Dashboard demo"
        assert automation.message == "Counter reset"


async def test_counter_is_kept_across_a_restart() -> None:
    """The card is rebuilt at startup from the stored count."""
    async with AutomationHarness(DASHBOARD) as automation:
        await automation.press("add")
        await automation.restart()
        assert automation.card.block("count")["value"] == 1


async def test_uptime_is_shown_every_minute() -> None:
    """The interval trigger replaces the uptime block in place."""
    async with AutomationHarness(DASHBOARD) as automation:
        await automation.advance_time(minutes=3)
        assert automation.card.block("uptime")["value"] == 3
        assert [block["id"] for block in automation.card.blocks][3] == "uptime"


async def test_card_is_empty_when_stopped() -> None:
    """Card content lives with the running automation."""
    async with AutomationHarness(DASHBOARD) as automation:
        await automation.stop()
        assert automation.card.blocks == []
        assert automation.card.title is None


async def test_event_counts() -> None:
    """A `dashboard_count` event adds its step, or one."""
    async with AutomationHarness(DASHBOARD) as automation:
        automation.fire_event("dashboard_count")
        automation.fire_event("dashboard_count", {"step": 4})
        await automation.wait_idle()
        assert automation.card.block("count")["value"] == 5


async def test_counter_starts_again_at_midnight() -> None:
    """The cron trigger sets the counter to zero at 00:00."""
    async with AutomationHarness(DASHBOARD, now="2025-01-06 23:59:00", variables={"count": 12}) as automation:
        await automation.advance_time(minutes=2)
        assert automation.card.block("count")["value"] == 0
        assert automation.get_variable("count") == 0
        assert automation.message == "New day: counter reset"


async def test_bare_card_and_back() -> None:
    """The frame button hides every fixed part of the card, and shows them again."""
    async with AutomationHarness(DASHBOARD) as automation:
        assert all(automation.card.options.values())
        assert await automation.press("frame") is False
        assert not any(automation.card.options.values())
        assert len(automation.card.blocks) == 17, "the content stays"
        assert await automation.press("frame") is True
        assert all(automation.card.options.values())


async def test_icons() -> None:
    """The fan icon follows its entity and turns; the last icon is driven by nothing."""
    async with AutomationHarness(DASHBOARD) as automation:
        fan = automation.card.block("fan")
        assert (fan["entity_id"], fan["icon"], fan["spin"], fan["follow_entity"]) == (
            "input_boolean.fan",
            "mdi:fan",
            True,
            True,
        )
        assert automation.card.block("sun_icon")["icon"] is None, "the entity's own icon"
        assert automation.card.block("info")["follow_entity"] is False


async def test_graphs() -> None:
    """One graph shows the temperature's history, the other the counts the automation kept."""
    async with AutomationHarness(DASHBOARD) as automation:
        temperature = automation.card.block("temperature")
        assert temperature["entities"] == ["sensor.temperature", "input_boolean.fan"]
        assert (temperature["hours"], temperature["kind"]) == (1.0, "area")
        assert automation.card.block("presses")["series"] == {"Count": []}

        await automation.press("add")
        await automation.call("count", step=4)
        await automation.press("reset")
        assert automation.card.block("presses")["series"] == {"Count": [[0.0, 1.0], [1.0, 5.0], [2.0, 0.0]]}
        assert automation.get_variable("history") == [1, 5, 0]


async def test_graph_keeps_the_last_twenty_counts() -> None:
    """The series the automation keeps does not grow without end."""
    async with AutomationHarness(DASHBOARD) as automation:
        for _ in range(25):
            await automation.press("add")
        points = automation.card.block("presses")["series"]["Count"]
        assert len(points) == 20
        assert points[-1][1] == 25.0
        assert points[0][1] == 6.0


async def test_goal_and_badge_follow_the_count() -> None:
    """The progress bar fills towards the goal, and the badge says how far the count is."""
    async with AutomationHarness(DASHBOARD) as automation:
        assert automation.card.block("goal")["max"] == 10
        assert automation.card.block("level") == {
            "id": "level",
            "type": "badge",
            "text": "Not started",
            "entity_id": None,
            "icon": None,
            "color": "disabled",
        }
        assert await automation.call("count", step=12) == 12
        assert automation.card.block("goal")["value"] == 12
        level = automation.card.block("level")
        assert (level["text"], level["icon"], level["color"]) == ("Goal reached", "mdi:trophy", "success")
        await automation.press("reset")
        assert automation.card.block("level")["text"] == "Not started"
