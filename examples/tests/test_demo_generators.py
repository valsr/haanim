"""Tests for the generators demo: what its generators compute, and watching with an async generator."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from haanim import ActionDroppedError
from haanim.testing import AutomationHarness

DEMO = Path(__file__).parents[1] / "demo_generators"


async def test_the_day_comes_from_generators() -> None:
    """The table has a row an hour; the average is over the last three readings."""
    async with AutomationHarness(DEMO) as automation:
        rows = automation.card.block("day")["rows"]
        assert len(rows) == 24
        assert rows[0] == ["00:00", 15.2, 15.2]
        assert rows[15] == ["15:00", 22.0, 21.8]
        assert automation.card.block("summary")["markdown"] == (
            "Peak **22 °C**, warm for **7** hours, mean over a week **18.0 °C**."
        )


async def test_watch_reads_every_second() -> None:
    """Each second gives a reading on the card; when done, the generator's finally says how long it ran."""
    async with AutomationHarness(DEMO, states={"sensor.temperature": "21.5"}) as automation:
        watching = asyncio.create_task(automation.call("watch", seconds=3))
        await automation.advance_time(seconds=1)
        assert automation.card.block("live")["value"] == 21.5
        automation.set_state("sensor.temperature", "22")
        await automation.advance_time(seconds=2)
        assert await watching == [21.5, 22.0, 22.0]
        assert automation.message == "Watched for 3 s"


async def test_stop_breaks_the_loop_and_closes_the_generator() -> None:
    """Stop ends the loop after the next reading; aclose() runs the generator's finally at once."""
    async with AutomationHarness(DEMO, states={"sensor.temperature": "21.5"}) as automation:
        watching = asyncio.create_task(automation.call("watch", seconds=10))
        await automation.advance_time(seconds=1)
        await automation.call("stop")
        await automation.advance_time(seconds=1)
        assert await watching == [21.5, 21.5]
        assert automation.message == "Watched for 2 s"


async def test_without_the_sensor() -> None:
    async with AutomationHarness(DEMO) as automation:
        watching = asyncio.create_task(automation.call("watch", seconds=1))
        await automation.advance_time(seconds=1)
        assert await watching == [None]


async def test_a_second_watch_is_dropped() -> None:
    """While watching, another Watch is refused (DROP), so only one loop reads at a time."""
    async with AutomationHarness(DEMO, states={"sensor.temperature": "21.5"}) as automation:
        first = asyncio.create_task(automation.call("watch", seconds=2))
        await automation.clock.settle()
        with pytest.raises(ActionDroppedError):
            await automation.call("watch", seconds=2)
        await automation.advance_time(seconds=2)
        assert await first == [21.5, 21.5]
