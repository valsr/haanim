"""Tests for statistics in running automations: entity imports and queries, and haa.statistics."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from haanim.engine.errors import StatisticsUnavailableError
from haanim.testing import AutomationHarness

MAIN = """
from datetime import datetime, timedelta, timezone
from haanim import action, haa, sensor_entity

@sensor_entity(unit="kWh", state_class="total_increasing")
class energy:
    pass

@sensor_entity(unit="°C", state_class="measurement")
class outside:
    pass

@sensor_entity
class plain:
    pass

DAY = datetime(2025, 1, 5, tzinfo=timezone.utc)

@action
async def backfill(event):
    rows = [{"start": DAY + timedelta(hours=h), "usage": 1} for h in range(3)]
    return await haa.device.entity("energy").import_statistics(rows)

@action
async def daily(event):
    rows = await haa.device.entity(energy).statistics(DAY, DAY + timedelta(days=1), period="day")
    return [(row["start"].isoformat(), row["change"]) for row in rows]

@action
async def temperatures(event):
    return await haa.device.entity("outside").import_statistics([{"start": DAY, "mean": 2.5}])

@action
async def plain_import(event):
    await haa.device.entity("plain").import_statistics([{"start": DAY, "mean": 1}])

@action
async def grid(event):
    rows = await haa.statistics(event.data["entity_id"], DAY, DAY + timedelta(hours=2))
    return [row.get("sum") for row in rows]
"""


def write(folder: Path, source: str = MAIN) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "main.py").write_text(source)
    return folder


DAY = datetime(2025, 1, 5, tzinfo=UTC)


async def test_backfill_and_read_back(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "demo")) as h:
        assert await h.call("backfill") == 3
        assert [row["sum"] for row in h.statistics("sensor.haanim_demo_energy")] == [1.0, 2.0, 3.0]
        assert await h.call("daily") == [(DAY.isoformat(), 3.0)]


async def test_measurement_import(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "demo")) as h:
        assert await h.call("temperatures") == 1
        assert h.statistics("sensor.haanim_demo_outside") == [
            {"start": DAY, "mean": 2.5, "min": 2.5, "max": 2.5}
        ]


async def test_entity_without_state_class_refused(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "demo")) as h:
        with pytest.raises(ValueError, match="state_class"):
            await h.call("plain_import")


async def test_leftover_refused(tmp_path: Path) -> None:
    folder = write(tmp_path / "demo")
    async with AutomationHarness(folder) as h:
        write(
            folder,
            MAIN.replace('@sensor_entity(unit="kWh"', '# @sensor_entity(unit="kWh"')
            .replace("class energy:\n    pass", "class energy_gone:\n    pass")
            .replace('entity("energy")', 'entity("energy")'),
        )
        await h.reload()
        with pytest.raises(ValueError, match="leftover|no longer declared"):
            await h.call("backfill")


async def test_query_any_entity(tmp_path: Path) -> None:
    seeded = {"sensor.grid": [{"start": DAY, "state": 5.0, "sum": 5.0}]}
    async with AutomationHarness(write(tmp_path / "demo"), statistics=seeded) as h:
        assert await h.call("grid", entity_id="sensor.grid") == [5.0]


async def test_query_unknown_entity_is_empty(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "demo")) as h:
        assert await h.call("grid", entity_id="sensor.nothing") == []


async def test_without_provider(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "demo"), statistics=False) as h:
        with pytest.raises(StatisticsUnavailableError):
            await h.call("backfill")
