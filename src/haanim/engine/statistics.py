"""Long-term statistics: importing hourly rows into an automation's entities, and querying any entity's.

See ``docs/superpowers/specs/2026-11-10-entity-statistics-design.md``. The rows
are checked and sums computed here, so the logic is the same whatever host runs
the engine; the host's ``StatisticsProvider`` only reads and writes rows.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from haanim.const import (
    STAT_CHANGE,
    STAT_END,
    STAT_MAX,
    STAT_MEAN,
    STAT_MIN,
    STAT_START,
    STAT_STATE,
    STAT_SUM,
    STAT_USAGE,
    Period,
)
from haanim.engine.errors import StatisticsError, StatisticsUnavailableError
from haanim.interfaces import StatisticsProvider

PERIODS = tuple(Period)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
# Home Assistant compiles an hour's statistics just after it ends; importing an hour before that conflicts
COMPILE_MARGIN = timedelta(minutes=15)
QUERY_TYPES = {STAT_MEAN, STAT_MIN, STAT_MAX, STAT_STATE, STAT_SUM, STAT_CHANGE}

SUM_FIELDS = frozenset({STAT_START, STAT_USAGE})
MEAN_FIELDS = frozenset({STAT_START, STAT_MEAN, STAT_MIN, STAT_MAX})


@dataclass(frozen=True)
class StatisticsMetadata:
    """What a statistic is.

    Args:
        statistic_id: The statistic's ID: the entity ID for an entity's statistics.
        name: The name shown for it.
        unit: The unit of the values.
        has_sum: True for sums (``total``, ``total_increasing``), False for a mean (``measurement``).
    """

    statistic_id: str
    name: str | None
    unit: str | None
    has_sum: bool


def parse_time(value: Any, now: datetime, what: str = STAT_START) -> datetime:
    """Return a time as an aware UTC datetime; a naive time is in the time zone of ``now``.

    Raises:
        ValueError: If the value is not a datetime or ISO text.
    """
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{what} {value!r} is not a time") from None
    if not isinstance(value, datetime):
        raise ValueError(f"{what} must be a datetime or ISO text, not {value!r}")
    moment: datetime = value if value.tzinfo is not None else value.replace(tzinfo=now.tzinfo)
    return moment.astimezone(UTC)


def _number(row: Mapping[str, Any], field: str) -> float:
    value = row[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number, not {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number, not {value!r}")
    return float(value)


def parse_rows(  # pylint: disable=too-many-branches
    rows: list[dict[str, Any]], *, has_sum: bool, now: datetime, allow_negative: bool = True
) -> list[dict[str, Any]]:
    """Check rows to import and return them sorted by hour, one per hour (the last row for an hour wins).

    Sum rows come back as ``{"start", "usage"}``, measurement rows as
    ``{"start", "mean", "min", "max"}`` with ``min`` and ``max`` defaulting to
    ``mean``; ``start`` is an aware UTC datetime.

    Raises:
        ValueError: If a row is not valid; the message says which and why.
    """
    if not rows:
        raise ValueError("no rows to import")
    by_hour: dict[datetime, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError(f"a row must be a dictionary, not {row!r}")
        if STAT_START not in row:
            raise ValueError("a row needs a start")
        start = parse_time(row[STAT_START], now)
        if (start.minute, start.second, start.microsecond) != (0, 0, 0):
            raise ValueError(f"start {start.isoformat()} is not the start of an hour")
        if start + HOUR + COMPILE_MARGIN > now:
            raise ValueError(
                f"the hour starting {start.isoformat()} has not ended at least 15 minutes ago: "
                "Home Assistant may still be compiling its statistics"
            )
        if has_sum:
            unknown = set(row) - SUM_FIELDS
            if unknown or STAT_USAGE not in row:
                raise ValueError(f"a row of sum statistics has start and usage, not {sorted(row)}")
            usage = _number(row, STAT_USAGE)
            if usage < 0 and not allow_negative:
                raise ValueError(f"usage {usage:g} is negative, and the entity's total only increases")
            by_hour[start] = {STAT_START: start, STAT_USAGE: usage}
        else:
            unknown = set(row) - MEAN_FIELDS
            if unknown or STAT_MEAN not in row:
                raise ValueError(f"a row of a measurement has start, mean, min and max, not {sorted(row)}")
            mean = _number(row, STAT_MEAN)
            low = _number(row, STAT_MIN) if STAT_MIN in row else mean
            high = _number(row, STAT_MAX) if STAT_MAX in row else mean
            if low > mean:
                raise ValueError(f"min {low:g} is above mean {mean:g}")
            if mean > high:
                raise ValueError(f"max {high:g} is below mean {mean:g}")
            by_hour[start] = {STAT_START: start, STAT_MEAN: mean, STAT_MIN: low, STAT_MAX: high}
    return [by_hour[start] for start in sorted(by_hour)]


async def import_statistics(  # pylint: disable=too-many-locals
    provider: StatisticsProvider | None,
    metadata: StatisticsMetadata,
    rows: list[dict[str, Any]],
    *,
    total_increasing: bool,
    now: datetime,
) -> int:
    """Import hourly rows; for sum statistics, turn usage into running sums that join up with stored ones.

    The sums start from the last stored sum before the first imported hour.
    Every stored sum after the last imported hour is shifted by how much the
    import changed the sum at that hour.

    Returns:
        How many hours were written: for sums, every hour from the first to
        the last imported one.

    Raises:
        ValueError: If the rows are not valid; nothing is imported then.
        StatisticsUnavailableError: If the host keeps no statistics.
        StatisticsError: If the host fails to read or write them.
    """
    parsed = parse_rows(rows, has_sum=metadata.has_sum, now=now, allow_negative=not total_increasing)
    if provider is None:
        raise StatisticsUnavailableError()
    try:
        if not metadata.has_sum:
            await provider.import_rows(metadata, parsed)
            return len(parsed)

        first, last = parsed[0][STAT_START], parsed[-1][STAT_START]
        # Home Assistant continues its live sum from its latest 5-minute row: without one it starts from 0
        if not await provider.has_short_term(metadata.statistic_id, last + HOUR):
            raise ValueError(
                f"Home Assistant has not recorded {metadata.statistic_id} yet, so its live sum would not "
                "continue from the imported one: import once it has been recorded for a few minutes"
            )
        history = await provider.query(
            metadata.statistic_id, EPOCH, last + HOUR, Period.HOUR, {STAT_SUM}, unit=metadata.unit
        )
        stored = [(row[STAT_START], row[STAT_SUM]) for row in history if row.get(STAT_SUM) is not None]
        before = [total for start, total in stored if start < first]
        base = before[-1] if before else 0.0
        up_to_end = [total for start, total in stored if start <= last]
        old_end = up_to_end[-1] if up_to_end else base

        # Every hour of the range gets a row, so a stored row in a gap keeps no old sum
        usage = {row[STAT_START]: row[STAT_USAGE] for row in parsed}
        running = base
        sums: list[dict[str, Any]] = []
        hour = first
        while hour <= last:
            running += usage.get(hour, 0.0)
            sums.append({STAT_START: hour, STAT_STATE: running, STAT_SUM: running})
            hour += HOUR
        await provider.import_rows(metadata, sums)
        if running != old_end:
            await provider.adjust_sums(metadata.statistic_id, last + HOUR, running - old_end, metadata.unit)
        return len(sums)
    except StatisticsError, ValueError:
        raise
    except Exception as err:
        raise StatisticsError(str(err) or type(err).__name__) from err


async def query_statistics(  # pylint: disable=too-many-positional-arguments
    provider: StatisticsProvider | None,
    statistic_id: str,
    start: Any,
    end: Any,
    period: str,
    now: datetime,
) -> list[dict[str, Any]]:
    """Return the statistics of a period, oldest first; an empty list if there are none.

    Raises:
        ValueError: If the period is unknown, or start is after end.
        StatisticsUnavailableError: If the host keeps no statistics.
        StatisticsError: If the host fails to read them.
    """
    if period not in PERIODS:
        raise ValueError(f"period must be one of {', '.join(PERIODS)}, not {period!r}")
    # In the clock's time zone: days, weeks and months are the local ones
    local = now.tzinfo
    begin = parse_time(start, now).astimezone(local)
    finish = (parse_time(end, now, STAT_END) if end is not None else now).astimezone(local)
    if begin > finish:
        raise ValueError(f"start {begin.isoformat()} is after end {finish.isoformat()}")
    if provider is None:
        raise StatisticsUnavailableError()
    try:
        return await provider.query(statistic_id, begin, finish, period, set(QUERY_TYPES))
    except Exception as err:
        raise StatisticsError(str(err) or type(err).__name__) from err
