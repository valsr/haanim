"""Long-term statistics held in memory, for tests: the testing kit's ``StatisticsProvider``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from haanim.engine.statistics import StatisticsMetadata

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

    def entity_statistic_id(self, platform: str, unique_id: str, default: str) -> str:  # noqa: ARG002
        """Return the default: there is no entity registry here."""
        return default

    async def import_rows(self, metadata: StatisticsMetadata, rows: list[dict[str, Any]]) -> None:
        """Store rows, replacing stored rows of the same hours."""
        self.metadata[metadata.statistic_id] = metadata
        stored = {row["start"]: row for row in self.rows.get(metadata.statistic_id, [])}
        stored.update({row["start"]: dict(row) for row in rows})
        self.rows[metadata.statistic_id] = [stored[start] for start in sorted(stored)]

    async def adjust_sums(self, statistic_id: str, start: datetime, delta: float, unit: str | None) -> None:
        """Add delta to every stored sum from start on."""
        for row in self.rows.get(statistic_id, []):
            if row["start"] >= start and "sum" in row:
                row["sum"] += delta
                row["state"] = row.get("state", 0.0) + delta

    async def query(
        self, statistic_id: str, start: datetime, end: datetime, period: str, types: set[str]
    ) -> list[dict[str, Any]]:
        """Return the rows of a period, oldest first."""
        if period == "5minute":
            return []
        stored = self.rows.get(statistic_id, [])
        zone = start.tzinfo
        groups: dict[datetime, list[dict[str, Any]]] = {}
        for row in stored:
            if start <= row["start"] < end:
                groups.setdefault(self._period_start(row["start"], period, zone), []).append(row)
        result = []
        for begin in sorted(groups):
            hours = groups[begin]
            item: dict[str, Any] = {
                "start": begin.astimezone(timezone.utc),
                "end": self._period_end(begin, period),
            }
            if "sum" in hours[-1]:
                earlier = [row["sum"] for row in stored if row["start"] < hours[0]["start"] and "sum" in row]
                item.update(state=hours[-1]["state"], sum=hours[-1]["sum"])
                item["change"] = hours[-1]["sum"] - (earlier[-1] if earlier else 0.0)
            else:
                item.update(
                    mean=sum(row["mean"] for row in hours) / len(hours),
                    min=min(row["min"] for row in hours),
                    max=max(row["max"] for row in hours),
                )
            result.append(
                {key: value for key, value in item.items() if key in ("start", "end") or key in types}
            )
        return result

    @staticmethod
    def _period_start(moment: datetime, period: str, zone: Any) -> datetime:
        local = moment.astimezone(zone)
        if period == "hour":
            return local.replace(minute=0, second=0, microsecond=0)
        day = local.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "day":
            return day
        if period == "week":
            return day - timedelta(days=day.weekday())
        return day.replace(day=1)

    @staticmethod
    def _period_end(begin: datetime, period: str) -> datetime:
        if period == "hour":
            return (begin + timedelta(hours=1)).astimezone(timezone.utc)
        if period == "day":
            following = begin + timedelta(days=1)
        elif period == "week":
            following = begin + timedelta(days=7)
        else:
            following = (begin.replace(day=28) + timedelta(days=4)).replace(day=1)
        # Through naive local time, so a day across a change of the clocks still ends at midnight
        return following.replace(tzinfo=None).replace(tzinfo=begin.tzinfo).astimezone(timezone.utc)
