"""Long-term statistics held in memory, for tests: the testing kit's ``StatisticsProvider``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    Period,
)
from haanim.engine.statistics import HOUR, StatisticsMetadata

__all__ = ["FakeStatistics"]


class FakeStatistics:
    """Long-term statistics held in memory: hourly rows by statistic ID.

    Queries derive days, weeks (from Monday) and months from the hourly rows, in
    the time zone of the query's start; ``5minute`` gives no rows.
    """

    def __init__(self, rows: dict[str, list[dict[str, Any]]] | None = None) -> None:
        """Initialize with the given hourly rows, by statistic ID."""
        self.rows: dict[str, list[dict[str, Any]]] = {key: list(value) for key, value in (rows or {}).items()}
        """The stored hourly rows, by statistic ID, oldest first."""
        self.metadata: dict[str, StatisticsMetadata] = {}
        """The metadata of the last import, by statistic ID."""
        self.not_recorded: set[str] = set()
        """Statistic IDs Home Assistant has not recorded live yet: sums cannot be imported into them."""
        self.query_units: list[str] = []
        """The units queries asked for, oldest first."""
        self.queries: list[tuple[str, datetime, datetime]] = []
        """The statistic ID, start and end of every query, oldest first."""

    async def has_short_term(self, statistic_id: str, start: datetime) -> bool:  # noqa: ARG002
        """Return whether the statistic is recorded live: unless it is in not_recorded."""
        return statistic_id not in self.not_recorded

    def entity_statistic_id(self, platform: str, unique_id: str, default: str) -> str:  # noqa: ARG002
        """Return the default: there is no entity registry here."""
        return default

    async def import_rows(self, metadata: StatisticsMetadata, rows: list[dict[str, Any]]) -> None:
        """Store rows, replacing stored rows of the same hours."""
        self.metadata[metadata.statistic_id] = metadata
        stored = {row[STAT_START]: row for row in self.rows.get(metadata.statistic_id, [])}
        stored.update({row[STAT_START]: dict(row) for row in rows})
        self.rows[metadata.statistic_id] = [stored[start] for start in sorted(stored)]

    async def adjust_sums(self, statistic_id: str, start: datetime, delta: float, unit: str | None) -> None:
        """Add delta to every stored sum from start on."""
        for row in self.rows.get(statistic_id, []):
            if row[STAT_START] >= start and STAT_SUM in row:
                row[STAT_SUM] += delta
                row[STAT_STATE] = row.get(STAT_STATE, 0.0) + delta

    async def query(  # pylint: disable=too-many-positional-arguments,too-many-locals
        self,
        statistic_id: str,
        start: datetime,
        end: datetime,
        period: str,
        types: set[str],
        unit: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the rows of a period, oldest first; values are in the one unit they were stored in."""
        if unit is not None:
            self.query_units.append(unit)
        self.queries.append((statistic_id, start, end))
        if period == Period.FIVE_MINUTES:
            return []
        stored = self.rows.get(statistic_id, [])
        zone = start.tzinfo
        groups: dict[datetime, list[dict[str, Any]]] = {}
        for row in stored:
            if start <= row[STAT_START] < end:
                groups.setdefault(self._period_start(row[STAT_START], period, zone), []).append(row)
        result = []
        for begin in sorted(groups):
            hours = groups[begin]
            item: dict[str, Any] = {
                STAT_START: begin.astimezone(timezone.utc),
                STAT_END: self._period_end(begin, period),
            }
            if STAT_SUM in hours[-1]:
                earlier = [
                    row[STAT_SUM]
                    for row in stored
                    if row[STAT_START] < hours[0][STAT_START] and STAT_SUM in row
                ]
                item.update({STAT_STATE: hours[-1][STAT_STATE], STAT_SUM: hours[-1][STAT_SUM]})
                item[STAT_CHANGE] = hours[-1][STAT_SUM] - (earlier[-1] if earlier else 0.0)
            else:
                item.update(
                    {
                        STAT_MEAN: sum(row[STAT_MEAN] for row in hours) / len(hours),
                        STAT_MIN: min(row[STAT_MIN] for row in hours),
                        STAT_MAX: max(row[STAT_MAX] for row in hours),
                    }
                )
            result.append(
                {key: value for key, value in item.items() if key in (STAT_START, STAT_END) or key in types}
            )
        return result

    @staticmethod
    def _period_start(moment: datetime, period: str, zone: Any) -> datetime:
        local = moment.astimezone(zone)
        if period == Period.HOUR:
            return local.replace(minute=0, second=0, microsecond=0)
        day = local.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == Period.DAY:
            return day
        if period == Period.WEEK:
            return day - timedelta(days=day.weekday())
        return day.replace(day=1)

    @staticmethod
    def _period_end(begin: datetime, period: str) -> datetime:
        if period == Period.HOUR:
            return (begin + HOUR).astimezone(timezone.utc)
        if period == Period.DAY:
            following = begin + timedelta(days=1)
        elif period == Period.WEEK:
            following = begin + timedelta(days=7)
        else:
            following = (begin.replace(day=28) + timedelta(days=4)).replace(day=1)
        # Through naive local time, so a day across a change of the clocks still ends at midnight
        return following.replace(tzinfo=None).replace(tzinfo=begin.tzinfo).astimezone(timezone.utc)
