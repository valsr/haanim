"""Tests for the dashboard example: what is on its card, and what its buttons do."""

from __future__ import annotations

from pathlib import Path

from haanim.testing import AutomationHarness

DASHBOARD = Path(__file__).parents[1] / "dashboard"


async def test_card_is_built_at_startup() -> None:
    """The card has its seven blocks in order, with the logo from the automation's assets."""
    async with AutomationHarness(DASHBOARD) as automation:
        assert [(block["id"], block["type"]) for block in automation.card.blocks] == [
            ("intro", "text"),
            ("logo", "image"),
            ("count", "value"),
            ("uptime", "value"),
            ("sun", "entity"),
            ("add", "button"),
            ("reset", "button"),
        ]
        assert automation.card.block("logo")["url"] == "/api/haanim/assets/dashboard/logo.svg"
        assert automation.card.block("count")["value"] == 0
        assert automation.message == "Card ready"


async def test_count_button_adds_one() -> None:
    """Pressing Count adds its step to the counter, on the card and in storage."""
    async with AutomationHarness(DASHBOARD) as automation:
        assert await automation.press("add") == 1
        assert await automation.press("add") == 2
        assert automation.card.block("count")["value"] == 2
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
        assert await automation.press("reset") == 0
        assert automation.card.block("count")["value"] == 0
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
