"""Tests for the statistics demo: the last week by day and this year by month, in the local time zone."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from haanim.testing import AutomationHarness

DEMO = Path(__file__).parents[1] / "demo_statistics"
ZONE = "Europe/Berlin"
NOW = "2025-03-15 12:00:00"
MEAN_BY_MONTH = {1: 2.0, 2: 4.0, 3: 8.0}


def hourly_rows() -> list[dict[str, Any]]:
    """Hourly statistics from New Year to now, with a mean that depends on the local month."""
    rows = []
    hour = datetime(2025, 1, 1, tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
    end = datetime(2025, 3, 15, 11, tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
    while hour < end:
        mean = MEAN_BY_MONTH[hour.astimezone(ZoneInfo(ZONE)).month]
        rows.append({"start": hour, "mean": mean, "min": mean - 3, "max": mean + 3})
        hour += timedelta(hours=1)
    return rows


def harness(**options: Any) -> AutomationHarness:
    options.setdefault("statistics", {"sensor.temperature": hourly_rows()})
    return AutomationHarness(DEMO, now=NOW, time_zone=ZONE, **options)


async def test_the_card_shows_the_last_week() -> None:
    """At start the table has a row for each of the last seven days, today included."""
    async with harness() as automation:
        table = automation.card.block("statistics")
        assert table["title"] == "Last 7 days"
        assert table["rows"][0] == ["Sun 09 Mar", 5.0, 8.0, 11.0]
        assert [row[0] for row in table["rows"]][-1] == "Sat 15 Mar"
        assert len(table["rows"]) == 7
        assert automation.message == "7 periods of sensor.temperature"
        assert len(automation.card.block("trend")["series"]["Mean"]) == 7


async def test_this_year_by_month() -> None:
    """Months are counted in the local time zone: the hour after midnight on 1 February is February's."""
    async with harness() as automation:
        assert await automation.press("year") == 3
        assert automation.card.block("statistics")["rows"] == [
            ["January", -1.0, 2.0, 5.0],
            ["February", 1.0, 4.0, 7.0],
            ["March", 5.0, 8.0, 11.0],
        ]


async def test_the_view_is_kept() -> None:
    """The view chosen last is the one shown after a restart."""
    async with harness() as automation:
        await automation.press("year")
        await automation.restart()
        assert automation.card.block("statistics")["title"] == "This year, by month"


async def test_a_sensor_without_statistics() -> None:
    async with harness(statistics={}) as automation:
        assert automation.card.block("statistics")["rows"] == []
        assert (automation.message or "").startswith("No statistics of sensor.temperature yet")


async def test_without_the_recorder() -> None:
    async with harness(statistics=False) as automation:
        assert automation.message == "Home Assistant keeps no statistics here: is the recorder on?"
