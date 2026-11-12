"""The engine's ``StatisticsProvider`` in Home Assistant: long-term statistics in the recorder."""

from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from typing import Any, cast

from homeassistant.components.recorder.models import StatisticData, StatisticMeanType, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    STATISTIC_UNIT_TO_UNIT_CONVERTER,
    async_import_statistics,
    get_metadata,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.recorder import get_instance

from custom_components.haanim.const import DOMAIN
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
from haanim.engine.statistics import StatisticsMetadata

# What a query row of the recorder has besides its times; last_reset is left out
FIELDS = (STAT_MEAN, STAT_MIN, STAT_MAX, STAT_STATE, STAT_SUM, STAT_CHANGE)


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
        """Return an entity's current entity ID, its statistic ID; default if it is not registered."""
        return er.async_get(self._hass).async_get_entity_id(platform, DOMAIN, unique_id) or default

    async def query(  # pylint: disable=too-many-positional-arguments
        self,
        statistic_id: str,
        start: datetime,
        end: datetime,
        period: str,
        types: set[str],
        unit: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the rows of a period, oldest first; with a unit, converted to it."""
        converter = STATISTIC_UNIT_TO_UNIT_CONVERTER.get(unit)
        units = {converter.UNIT_CLASS: unit} if converter and unit else None
        result = await get_instance(self._hass).async_add_executor_job(
            statistics_during_period,
            self._hass,
            start,
            end,
            {statistic_id},
            period,
            units,
            types,
        )
        rows = []
        for found in result.get(statistic_id, []):
            row: dict[str, Any] = dict(found)
            item: dict[str, Any] = {STAT_START: _time(row[STAT_START]), STAT_END: _time(row[STAT_END])}
            item.update({key: row[key] for key in FIELDS if row.get(key) is not None})
            rows.append(item)
        return rows

    async def has_short_term(self, statistic_id: str, start: datetime) -> bool:
        """Return whether the recorder has 5-minute rows of a statistic from start on."""
        result = await get_instance(self._hass).async_add_executor_job(
            statistics_during_period,
            self._hass,
            start,
            None,
            {statistic_id},
            Period.FIVE_MINUTES,
            None,
            {STAT_SUM},
        )
        return bool(result.get(statistic_id))

    async def import_rows(self, metadata: StatisticsMetadata, rows: list[dict[str, Any]]) -> None:
        """Write hourly rows through the recorder's queue, and wait until they are written.

        Statistics Home Assistant keeps in another unit than the declared one
        (the owner chose another display unit) stay in that unit: the values
        are converted to it.
        """
        unit = metadata.unit
        converter = STATISTIC_UNIT_TO_UNIT_CONVERTER.get(unit)
        found = await get_instance(self._hass).async_add_executor_job(
            partial(get_metadata, self._hass, statistic_ids={metadata.statistic_id})
        )
        stored_unit = (
            found[metadata.statistic_id][1]["unit_of_measurement"] if metadata.statistic_id in found else unit
        )
        if converter and stored_unit != unit and stored_unit in converter.VALID_UNITS:
            convert = converter.converter_factory(unit, stored_unit)
            rows = [
                {key: convert(value) if key != STAT_START else value for key, value in row.items()}
                for row in rows
            ]
            unit = stored_unit
        meta = StatisticMetaData(
            mean_type=StatisticMeanType.NONE if metadata.has_sum else StatisticMeanType.ARITHMETIC,
            has_sum=metadata.has_sum,
            name=metadata.name,
            source="recorder",
            statistic_id=metadata.statistic_id,
            unit_class=converter.UNIT_CLASS if converter else None,
            unit_of_measurement=unit,
        )
        async_import_statistics(self._hass, meta, [cast(StatisticData, dict(row)) for row in rows])
        await get_instance(self._hass).async_block_till_done()

    async def adjust_sums(self, statistic_id: str, start: datetime, delta: float, unit: str | None) -> None:
        """Add delta to every stored sum from start on, and wait until it is written."""
        recorder = get_instance(self._hass)
        recorder.async_adjust_statistics(statistic_id, start, delta, unit or "")
        await recorder.async_block_till_done()
