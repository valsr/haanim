"""The engine's ``StatisticsProvider`` in Home Assistant: long-term statistics in the recorder."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from homeassistant.components.recorder.models import StatisticData, StatisticMeanType, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    STATISTIC_UNIT_TO_UNIT_CONVERTER,
    async_import_statistics,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.recorder import get_instance

from custom_components.haanim.const import DOMAIN
from haanim.engine.statistics import StatisticsMetadata

# What a query row of the recorder has besides its times; last_reset is left out
FIELDS = ("mean", "min", "max", "state", "sum", "change")


def _time(value: Any) -> datetime:
    """Return a time of the recorder (a timestamp or a datetime) as an aware UTC datetime."""
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    return datetime.fromtimestamp(float(value), tz=UTC)


class HAStatistics:
    """Reads and writes long-term statistics through Home Assistant's recorder."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize with the Home Assistant instance whose recorder keeps the statistics."""
        self._hass = hass

    def entity_statistic_id(self, platform: str, unique_id: str, default: str) -> str:
        """Return an entity's current entity ID, which is its statistic ID; default if it is not registered."""
        return er.async_get(self._hass).async_get_entity_id(platform, DOMAIN, unique_id) or default

    async def query(
        self, statistic_id: str, start: datetime, end: datetime, period: str, types: set[str]
    ) -> list[dict[str, Any]]:
        """Return the rows of a period, oldest first."""
        result = await get_instance(self._hass).async_add_executor_job(
            statistics_during_period,
            self._hass,
            start,
            end,
            {statistic_id},
            period,
            None,
            types,
        )
        rows = []
        for row in result.get(statistic_id, []):
            item: dict[str, Any] = {"start": _time(row["start"]), "end": _time(row["end"])}
            item.update({key: row[key] for key in FIELDS if row.get(key) is not None})  # type: ignore[literal-required]
            rows.append(item)
        return rows

    async def import_rows(self, metadata: StatisticsMetadata, rows: list[dict[str, Any]]) -> None:
        """Write hourly rows through the recorder's queue, and wait until they are written."""
        converter = STATISTIC_UNIT_TO_UNIT_CONVERTER.get(metadata.unit)
        meta = StatisticMetaData(
            mean_type=StatisticMeanType.NONE if metadata.has_sum else StatisticMeanType.ARITHMETIC,
            has_sum=metadata.has_sum,
            name=metadata.name,
            source="recorder",
            statistic_id=metadata.statistic_id,
            unit_class=converter.UNIT_CLASS if converter else None,
            unit_of_measurement=metadata.unit,
        )
        async_import_statistics(self._hass, meta, [cast(StatisticData, dict(row)) for row in rows])
        await get_instance(self._hass).async_block_till_done()

    async def adjust_sums(self, statistic_id: str, start: datetime, delta: float, unit: str | None) -> None:
        """Add delta to every stored sum from start on, and wait until it is written."""
        recorder = get_instance(self._hass)
        recorder.async_adjust_statistics(statistic_id, start, delta, unit or "")
        await recorder.async_block_till_done()
