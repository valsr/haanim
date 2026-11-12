"""Tests for long-term statistics in the engine: row checks, usage to sums, queries, and the fake provider."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from haanim.engine.errors import StatisticsError, StatisticsUnavailableError
from haanim.engine.statistics import StatisticsMetadata, import_statistics, query_statistics
from haanim.testing import FakeStatistics

NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)
SUM = StatisticsMetadata("sensor.energy", "energy", "kWh", has_sum=True)
MEAN = StatisticsMetadata("sensor.outside", "outside", "°C", has_sum=False)


def H(hour: int, day: int = 1) -> datetime:  # pylint: disable=invalid-name
    """An hour of November 2026, in UTC."""
    return datetime(2026, 11, day, hour, tzinfo=UTC)


def row(start: datetime, total: float) -> dict[str, Any]:
    """A stored sum row."""
    return {"start": start, "state": float(total), "sum": float(total)}


@pytest.fixture
def fake() -> FakeStatistics:
    return FakeStatistics()


def sums(fake: FakeStatistics) -> list[float]:
    return [stored["sum"] for stored in fake.rows["sensor.energy"]]


async def test_sums_start_from_zero_without_history(fake: FakeStatistics) -> None:
    rows = [{"start": H(0), "usage": 1.5}, {"start": H(1), "usage": 2}]
    assert await import_statistics(fake, SUM, rows, total_increasing=True, now=NOW) == 2
    assert [(r["sum"], r["state"]) for r in fake.rows["sensor.energy"]] == [(1.5, 1.5), (3.5, 3.5)]
    assert fake.metadata["sensor.energy"] == SUM


async def test_sums_continue_from_far_older_history(fake: FakeStatistics) -> None:
    fake.rows["sensor.energy"] = [row(H(5) - timedelta(days=30), 100)]
    await import_statistics(fake, SUM, [{"start": H(0), "usage": 1}], total_increasing=True, now=NOW)
    assert sums(fake) == [100.0, 101.0]


async def test_sums_read_only_recent_history(fake: FakeStatistics) -> None:
    """With a stored sum shortly before the import, years of history are not read to find it."""
    fake.rows["sensor.energy"] = [row(H(0) - timedelta(days=400), 1)] + [
        row(H(0) - timedelta(hours=back), 100 - back) for back in range(48, 0, -1)
    ]
    await import_statistics(fake, SUM, [{"start": H(0), "usage": 1}], total_increasing=True, now=NOW)
    assert sums(fake)[-1] == 100.0
    assert [start for _, start, _ in fake.queries] == [H(0) - timedelta(days=1)]


async def test_sums_continue_from_year_old_history(fake: FakeStatistics) -> None:
    fake.rows["sensor.energy"] = [row(H(0) - timedelta(days=400), 50)]
    await import_statistics(fake, SUM, [{"start": H(0), "usage": 1}], total_increasing=True, now=NOW)
    assert sums(fake) == [50.0, 51.0]


async def test_later_rows_are_shifted(fake: FakeStatistics) -> None:
    fake.rows["sensor.energy"] = [row(H(0), 10), row(H(1), 11), row(H(2), 12), row(H(3), 13)]
    rows = [{"start": H(1), "usage": 5}, {"start": H(2), "usage": 5}]
    await import_statistics(fake, SUM, rows, total_increasing=True, now=NOW)
    assert sums(fake) == [10, 15, 20, 21]


async def test_gap_counts_as_no_usage(fake: FakeStatistics) -> None:
    rows = [{"start": H(3), "usage": 1}, {"start": H(0), "usage": 1}]
    assert await import_statistics(fake, SUM, rows, total_increasing=True, now=NOW) == 4
    assert sums(fake) == [1, 1, 1, 2]


async def test_last_row_wins(fake: FakeStatistics) -> None:
    rows = [{"start": H(0), "usage": 1}, {"start": H(0), "usage": 4}]
    assert await import_statistics(fake, SUM, rows, total_increasing=True, now=NOW) == 1
    assert sums(fake) == [4]


async def test_total_may_go_down(fake: FakeStatistics) -> None:
    await import_statistics(fake, SUM, [{"start": H(0), "usage": -2}], total_increasing=False, now=NOW)
    assert sums(fake) == [-2]


async def test_measurement_rows_default_min_max(fake: FakeStatistics) -> None:
    await import_statistics(fake, MEAN, [{"start": H(0), "mean": 3}], total_increasing=False, now=NOW)
    assert fake.rows["sensor.outside"] == [{"start": H(0), "mean": 3.0, "min": 3.0, "max": 3.0}]


@pytest.mark.parametrize(
    "rows, message",
    [
        ([], "no rows"),
        ([{"start": H(0).replace(minute=30), "usage": 1}], "start of an hour"),
        ([{"start": NOW, "usage": 1}], "ended"),
        ([{"start": H(0), "mean": 1}], "usage"),
        ([{"usage": 1}], "start"),
        ([{"start": "yesterday", "usage": 1}], "start"),
        ([{"start": H(0), "usage": float("nan")}], "finite"),
        ([{"start": H(0), "usage": "lots"}], "number"),
        ([{"start": H(0), "usage": -1}], "negative"),
    ],
)
async def test_invalid_sum_rows(fake: FakeStatistics, rows: list[dict[str, Any]], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        await import_statistics(fake, SUM, rows, total_increasing=True, now=NOW)
    assert "sensor.energy" not in fake.rows


@pytest.mark.parametrize(
    "rows, message",
    [
        ([{"start": H(0), "usage": 1}], "mean"),
        ([{"start": H(0), "mean": 3, "min": 4}], "min"),
        ([{"start": H(0), "mean": 3, "max": 2}], "max"),
    ],
)
async def test_invalid_measurement_rows(
    fake: FakeStatistics, rows: list[dict[str, Any]], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        await import_statistics(fake, MEAN, rows, total_increasing=False, now=NOW)


async def test_naive_start_is_in_clock_time_zone(fake: FakeStatistics) -> None:
    now = datetime(2026, 11, 10, 12, tzinfo=ZoneInfo("America/Toronto"))
    await import_statistics(
        fake, SUM, [{"start": "2026-11-01T00:00:00", "usage": 1}], total_increasing=True, now=now
    )
    assert fake.rows["sensor.energy"][0]["start"] == datetime(2026, 11, 1, 4, tzinfo=UTC)


async def test_half_hour_time_zone(fake: FakeStatistics) -> None:
    kolkata = ZoneInfo("Asia/Kolkata")
    with pytest.raises(ValueError, match="start of an hour"):
        await import_statistics(
            fake,
            SUM,
            [{"start": datetime(2026, 11, 1, 0, tzinfo=kolkata), "usage": 1}],
            total_increasing=True,
            now=NOW,
        )
    await import_statistics(
        fake,
        SUM,
        [{"start": datetime(2026, 11, 1, 0, 30, tzinfo=kolkata), "usage": 1}],
        total_increasing=True,
        now=NOW,
    )
    assert fake.rows["sensor.energy"][0]["start"] == datetime(2026, 10, 31, 19, tzinfo=UTC)


async def test_no_provider() -> None:
    with pytest.raises(StatisticsUnavailableError):
        await import_statistics(None, SUM, [{"start": H(0), "usage": 1}], total_increasing=True, now=NOW)
    with pytest.raises(StatisticsUnavailableError):
        await query_statistics(None, "sensor.energy", H(0), None, "hour", NOW)


class Failing(FakeStatistics):
    """A provider whose recorder fails."""

    async def import_rows(self, metadata: StatisticsMetadata, rows: list[dict[str, Any]]) -> None:
        raise RuntimeError("database is locked")


async def test_provider_failure_is_statistics_error() -> None:
    with pytest.raises(StatisticsError, match="database is locked"):
        await import_statistics(Failing(), SUM, [{"start": H(0), "usage": 1}], total_increasing=True, now=NOW)


async def test_query_hours(fake: FakeStatistics) -> None:
    fake.rows["sensor.energy"] = [row(H(0), 1), row(H(1), 3)]
    rows = await query_statistics(fake, "sensor.energy", H(0), H(2), "hour", NOW)
    assert rows == [
        {"start": H(0), "end": H(1), "state": 1.0, "sum": 1.0, "change": 1.0},
        {"start": H(1), "end": H(2), "state": 3.0, "sum": 3.0, "change": 2.0},
    ]


async def test_query_day_period_and_change(fake: FakeStatistics) -> None:
    fake.rows["sensor.energy"] = [row(H(0, day=1) + timedelta(hours=h), h + 1) for h in range(48)]
    rows = await query_statistics(fake, "sensor.energy", H(0, day=1), H(0, day=3), "day", NOW)
    assert [(r["start"], r["sum"], r["change"]) for r in rows] == [
        (H(0, 1), 24.0, 24.0),
        (H(0, 2), 48.0, 24.0),
    ]


async def test_query_day_of_measurements(fake: FakeStatistics) -> None:
    fake.rows["sensor.outside"] = [
        {"start": H(0), "mean": 1.0, "min": 0.0, "max": 2.0},
        {"start": H(1), "mean": 3.0, "min": 2.0, "max": 6.0},
    ]
    rows = await query_statistics(fake, "sensor.outside", H(0), H(0, day=2), "day", NOW)
    assert rows == [{"start": H(0), "end": H(0, day=2), "mean": 2.0, "min": 0.0, "max": 6.0}]


async def test_query_end_defaults_to_now(fake: FakeStatistics) -> None:
    fake.rows["sensor.energy"] = [row(H(0), 1), row(H(13, day=10), 2)]
    rows = await query_statistics(fake, "sensor.energy", H(0), None, "hour", NOW)
    assert [r["start"] for r in rows] == [H(0)]


@pytest.mark.parametrize("start, end, period", [(H(0), H(1), "year"), (H(2), H(1), "hour")])
async def test_query_bad_arguments(fake: FakeStatistics, start: datetime, end: datetime, period: str) -> None:
    with pytest.raises(ValueError):
        await query_statistics(fake, "sensor.energy", start, end, period, NOW)


async def test_query_without_statistics_is_empty(fake: FakeStatistics) -> None:
    assert await query_statistics(fake, "sensor.nothing", H(0), H(5), "day", NOW) == []


# --- Final review fixes -----------------------------------------------------------


async def test_hour_not_yet_compiled_by_home_assistant_refused(fake: FakeStatistics) -> None:
    """An hour that ended less than 15 minutes ago may still be compiled by Home Assistant: refused."""
    now = datetime(2026, 11, 10, 12, 10, tzinfo=UTC)
    with pytest.raises(ValueError, match="15 minutes"):
        await import_statistics(
            fake, SUM, [{"start": H(11, day=10), "usage": 1}], total_increasing=True, now=now
        )
    assert (
        await import_statistics(
            fake, SUM, [{"start": H(10, day=10), "usage": 1}], total_increasing=True, now=now
        )
        == 1
    )


async def test_sums_need_the_entity_recorded_live(fake: FakeStatistics) -> None:
    """Without 5-minute statistics after the import, Home Assistant's live sum would restart at 0: refused."""
    fake.not_recorded.add("sensor.energy")
    with pytest.raises(ValueError, match="recorded"):
        await import_statistics(fake, SUM, [{"start": H(0), "usage": 1}], total_increasing=True, now=NOW)
    assert "sensor.energy" not in fake.rows
    fake.not_recorded.add("sensor.outside")
    assert (
        await import_statistics(fake, MEAN, [{"start": H(0), "mean": 1}], total_increasing=False, now=NOW)
        == 1
    )


async def test_stored_rows_in_a_gap_get_the_running_sum(fake: FakeStatistics) -> None:
    """A stored hour inside the imported range but not imported keeps no old sum: no negative hour."""
    fake.rows["sensor.energy"] = [row(H(h), 10 + h) for h in range(6)]
    rows = [{"start": H(1), "usage": 5}, {"start": H(4), "usage": 1}]
    assert await import_statistics(fake, SUM, rows, total_increasing=True, now=NOW) == 4
    assert sums(fake) == [10, 15, 15, 15, 16, 17]


async def test_base_is_read_in_the_declared_unit(fake: FakeStatistics) -> None:
    """The stored sums are asked for in the entity's declared unit."""
    await import_statistics(fake, SUM, [{"start": H(0), "usage": 1}], total_increasing=True, now=NOW)
    assert fake.query_units and set(fake.query_units) == {"kWh"}
