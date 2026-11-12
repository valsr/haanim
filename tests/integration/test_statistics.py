"""Tests for long-term statistics against Home Assistant's recorder."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.db_schema import StatisticsShortTerm
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import async_import_statistics, statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.recorder import get_instance
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.haanim.ha.host import build_host
from tests.integration.test_device_entities import Setup, setup  # noqa: F401  pylint: disable=unused-import

DAY = datetime(2026, 11, 1, tzinfo=UTC)
ENERGY = "sensor.haanim_heat_energy"

HEAT = """
from datetime import datetime, timedelta, timezone
from haanim import action, haa, sensor_entity

@sensor_entity(unit="kWh", device_class="energy", state_class="total_increasing")
class energy:
    pass

@sensor_entity(unit="°C", state_class="measurement")
class outside:
    pass

DAY = datetime(2026, 11, 1, tzinfo=timezone.utc)

@action
async def backfill(event):
    rows = [{"start": DAY + timedelta(hours=h), "usage": u} for h, u in event.data["usage"]]
    return await haa.device.entity("energy").import_statistics(rows)

@action
async def temperatures(event):
    return await haa.device.entity("outside").import_statistics([{"start": DAY, "mean": 2.5, "min": 1, "max": 4}])

@action
async def query(event):
    rows = await haa.statistics(event.data["entity_id"], DAY, DAY + timedelta(days=1), period=event.data["period"])
    return [{k: v for k, v in row.items() if k in ("sum", "change", "mean")} for row in rows]
"""


@pytest.fixture(autouse=True)
def mock_recorder_before_hass(async_test_recorder: Any) -> None:
    """Set up the recorder before Home Assistant, as the recorder tests of Home Assistant do."""


def energy_metadata(statistic_id: str = ENERGY, unit: str = "kWh") -> Any:
    """The metadata Home Assistant keeps for the energy sensor's statistics."""
    return {
        "mean_type": StatisticMeanType.NONE,
        "has_sum": True,
        "name": None,
        "source": "recorder",
        "statistic_id": statistic_id,
        "unit_class": "energy",
        "unit_of_measurement": unit,
    }


async def record_live(
    hass: HomeAssistant, recorder: Recorder, statistic_id: str = ENERGY, unit: str = "kWh", total: float = 0.0
) -> None:
    """Store a 5-minute row of now, as Home Assistant's compile does for an entity it records live."""
    now = dt_util.utcnow()
    start = now.replace(minute=now.minute - now.minute % 5, second=0, microsecond=0) - timedelta(minutes=5)
    recorder.async_import_statistics(
        energy_metadata(statistic_id, unit),
        [{"start": start, "state": total, "sum": total}],
        StatisticsShortTerm,
    )
    await async_wait_recording_done(hass)


async def stored(
    hass: HomeAssistant, statistic_id: str, units: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """The stored hourly rows of a statistic."""
    await async_wait_recording_done(hass)
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        DAY - timedelta(days=1),
        None,
        {statistic_id},
        "hour",
        units,
        {"sum", "mean", "min", "max"},
    )
    return result.get(statistic_id, [])


def seed_hours(hass: HomeAssistant, unit: str, sums: list[float]) -> None:
    """Store hourly sums of the energy sensor from DAY on."""
    async_import_statistics(
        hass,
        energy_metadata(unit=unit),
        [{"start": DAY + timedelta(hours=h), "state": total, "sum": total} for h, total in enumerate(sums)],
    )


async def test_import_and_query_sums(
    recorder_mock: Recorder, hass: HomeAssistant, setup: Setup
) -> None:  # noqa: F811
    manager = await setup({"heat": HEAT})
    await record_live(hass, recorder_mock)
    assert await manager.async_call_action("heat", "backfill", {"usage": [(0, 1), (1, 1), (2, 1)]}) == 3
    assert [row["sum"] for row in await stored(hass, ENERGY)] == [1.0, 2.0, 3.0]
    day = await manager.async_call_action("heat", "query", {"entity_id": ENERGY, "period": "day"})
    assert [row["change"] for row in day] == [3.0]


async def test_later_live_rows_are_shifted(
    recorder_mock: Recorder, hass: HomeAssistant, setup: Setup
) -> None:  # noqa: F811
    manager = await setup({"heat": HEAT})
    seed_hours(hass, "kWh", [10.0, 11.0, 12.0, 13.0])
    await record_live(hass, recorder_mock, total=13.0)
    await manager.async_call_action("heat", "backfill", {"usage": [(1, 5), (2, 5)]})
    assert [row["sum"] for row in await stored(hass, ENERGY)] == [10.0, 15.0, 20.0, 21.0]


async def test_measurement_import(
    recorder_mock: Recorder, hass: HomeAssistant, setup: Setup
) -> None:  # noqa: F811
    manager = await setup({"heat": HEAT})
    assert await manager.async_call_action("heat", "temperatures") == 1
    rows = await stored(hass, "sensor.haanim_heat_outside")
    assert [(row["mean"], row["min"], row["max"]) for row in rows] == [(2.5, 1.0, 4.0)]


async def test_renamed_entity_uses_its_new_id(
    recorder_mock: Recorder, hass: HomeAssistant, setup: Setup
) -> None:  # noqa: F811
    manager = await setup({"heat": HEAT})
    er.async_get(hass).async_update_entity(ENERGY, new_entity_id="sensor.my_energy")
    await record_live(hass, recorder_mock, "sensor.my_energy")
    await manager.async_call_action("heat", "backfill", {"usage": [(0, 2)]})
    assert [row["sum"] for row in await stored(hass, "sensor.my_energy")] == [2.0]


async def test_query_unknown_entity_is_empty(
    recorder_mock: Recorder, hass: HomeAssistant, setup: Setup
) -> None:  # noqa: F811
    manager = await setup({"heat": HEAT})
    assert (
        await manager.async_call_action("heat", "query", {"entity_id": "sensor.nothing", "period": "hour"})
        == []
    )


async def test_host_has_a_provider_with_the_recorder(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    assert build_host(hass, None, None).statistics is not None  # type: ignore[arg-type]


async def test_entity_not_recorded_live_is_refused(
    recorder_mock: Recorder, hass: HomeAssistant, setup: Setup  # noqa: F811
) -> None:
    """Before Home Assistant has recorded the entity, its live sum would restart at 0 after the import."""
    manager = await setup({"heat": HEAT})
    with pytest.raises(ValueError, match="recorded"):
        await manager.async_call_action("heat", "backfill", {"usage": [(0, 1)]})
    assert await stored(hass, ENERGY) == []


async def test_display_unit_differs_from_declared(
    recorder_mock: Recorder, hass: HomeAssistant, setup: Setup  # noqa: F811
) -> None:
    """Statistics kept in Wh (the display unit chosen in Home Assistant) take kWh usage, converted."""
    manager = await setup({"heat": HEAT})
    er.async_get(hass).async_update_entity_options(ENERGY, "sensor", {"unit_of_measurement": "Wh"})
    await hass.async_block_till_done()
    seed_hours(hass, "Wh", [10000.0, 11000.0, 12000.0, 13000.0])
    await record_live(hass, recorder_mock, unit="Wh", total=13000.0)
    await manager.async_call_action("heat", "backfill", {"usage": [(1, 5), (2, 5)]})
    rows = await stored(hass, ENERGY, {"energy": "Wh"})
    assert [row["sum"] for row in rows] == [10000.0, 15000.0, 20000.0, 21000.0]
