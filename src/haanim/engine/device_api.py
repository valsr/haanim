"""What automations reach their device's entities through: ``haa.device`` and its entity proxies.

See "The automation API" in
``docs/superpowers/specs/2026-11-09-automation-devices-design.md``. A proxy
reads and writes the automation's ``DeviceStore`` each time it is used, so it
always shows the stored state.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import datetime
from typing import Any

from haanim.const import (
    OPTION_NAME,
    OPTION_STATE_CLASS,
    OPTION_UNIT,
    EntityPlatform,
    Period,
    StateClass,
)
from haanim.engine.device_entities import get_declaration
from haanim.engine.devices import DeviceStore, StoredEntity
from haanim.engine.errors import NonExistingEntityError, StatisticsUnavailableError
from haanim.engine.statistics import StatisticsMetadata, import_statistics, query_statistics
from haanim.interfaces import Clock, StatisticsProvider


class DeviceEntity:
    """One entity of the automation's device."""

    __slots__ = ("_store", "_key", "_statistics", "_clock")

    def __init__(
        self,
        store: DeviceStore,
        key: str,
        statistics: StatisticsProvider | None = None,
        clock: Clock | None = None,
    ) -> None:
        """Initialize the proxy of the entity with a key in a store.

        Args:
            store: The automation's entities.
            key: The entity's key in the store.
            statistics: Where long-term statistics are kept; None if the host keeps none.
            clock: The clock that says which hours have ended; needed for statistics.
        """
        self._store = store
        self._key = key
        self._statistics = statistics
        self._clock = clock

    def __repr__(self) -> str:
        return f"<DeviceEntity {self.entity_id}>"

    def _entity(self) -> StoredEntity:
        entity = self._store.get(self._key)
        if entity is None:
            raise NonExistingEntityError(self._key)
        return entity

    @property
    def key(self) -> str:
        """The entity's key in the device: the object ID, or ``<object_id>@<platform>`` for some leftovers."""
        return self._key

    @property
    def entity_id(self) -> str:
        """The entity's ID in Home Assistant, such as ``switch.haanim_climate_boost``."""
        return self._entity().entity_id(self._store.automation_id)

    @property
    def object_id(self) -> str:
        """The object ID the entity was declared with."""
        return self._entity().object_id

    @property
    def platform(self) -> str:
        """The Home Assistant platform: ``sensor``, ``switch``, ..."""
        return self._entity().platform

    @property
    def state(self) -> Any:
        """The stored state; None while unknown."""
        return copy.deepcopy(self._entity().state)

    @property
    def attributes(self) -> dict[str, Any]:
        """A copy of the attributes."""
        return copy.deepcopy(self._entity().attributes)

    @property
    def declared(self) -> bool:
        """Whether the automation's code declares the entity; False for a leftover."""
        return self._entity().declared

    @property
    def options(self) -> dict[str, Any]:
        """A copy of the platform options of the declaration: ``unit``, ``min``, ``options``, ..."""
        return copy.deepcopy(self._entity().platform_options)

    def set_state(self, value: Any) -> None:
        """Validate and store a new state.

        Raises:
            ValueError: If the entity is a leftover or a button, or the declaration does not allow the value.
        """
        self._entity()
        self._store.set_state(self._key, value)

    def set_attributes(self, **attributes: Any) -> None:
        """Merge attributes into the entity's; an attribute given as None is removed.

        Raises:
            ValueError: If the entity is a leftover.
            TypeError: If a value is not JSON.
        """
        self._entity()
        self._store.set_attributes(self._key, **attributes)

    # --- Long-term statistics -------------------------------------------------------

    def _statistic_id(self, entity: StoredEntity) -> str:
        automation_id = self._store.automation_id
        default = entity.entity_id(automation_id)
        if self._statistics is None:
            return default
        return self._statistics.entity_statistic_id(entity.platform, entity.unique_id(automation_id), default)

    def _now(self) -> datetime:
        if self._clock is None:
            raise StatisticsUnavailableError()
        return self._clock.now()

    async def import_statistics(self, rows: list[dict[str, Any]]) -> int:
        """Import hourly long-term statistics into this entity.

        For a ``total`` or ``total_increasing`` sensor each row has ``start``
        and ``usage``, and the running sums continue from the stored ones; for a
        ``measurement`` sensor each row has ``start``, ``mean`` and optionally
        ``min`` and ``max``. A later row for an hour replaces an earlier one.

        Returns:
            How many hours were imported.

        Raises:
            ValueError: If the entity cannot have statistics or a row is not valid.
            StatisticsUnavailableError: If Home Assistant's recorder is not running.
            StatisticsError: If the recorder fails.
        """
        entity = self._entity()
        state_class = entity.options.get(OPTION_STATE_CLASS)
        if entity.platform != EntityPlatform.SENSOR or not entity.declared or state_class is None:
            raise ValueError(
                f"Entity '{self._key}' cannot have statistics: only a declared sensor with a state_class can"
                + ("" if entity.declared else " (it is a leftover)")
            )
        metadata = StatisticsMetadata(
            statistic_id=self._statistic_id(entity),
            name=entity.options.get(OPTION_NAME),
            unit=entity.options.get(OPTION_UNIT),
            has_sum=state_class != StateClass.MEASUREMENT,
        )
        return await import_statistics(
            self._statistics,
            metadata,
            rows,
            total_increasing=state_class == StateClass.TOTAL_INCREASING,
            now=self._now(),
        )

    async def statistics(
        self, start: Any, end: Any = None, period: str = Period.HOUR
    ) -> list[dict[str, Any]]:
        """Return this entity's long-term statistics of a period, oldest first.

        Args:
            start: The start, as a datetime or ISO text.
            end: The end; now if omitted.
            period: ``5minute``, ``hour``, ``day``, ``week`` or ``month``.
        """
        entity = self._entity()
        return await query_statistics(
            self._statistics, self._statistic_id(entity), start, end, period, self._now()
        )


class HAAnimDevice:
    """The automation's device in Home Assistant, and its entities."""

    def __init__(
        self,
        store: DeviceStore,
        name: Callable[[], str],
        statistics: StatisticsProvider | None = None,
        clock: Clock | None = None,
    ) -> None:
        """Initialize the device of a store.

        Args:
            store: The automation's entities.
            name: Returns the automation's name.
            statistics: Where long-term statistics are kept; None if the host keeps none.
            clock: The clock that says which hours have ended.
        """
        self._store = store
        self._name = name
        self._statistics = statistics
        self._clock = clock

    def __repr__(self) -> str:
        return f"<HAAnimDevice {self.id}>"

    @property
    def id(self) -> str:
        """The automation's ID, which identifies the device."""
        return self._store.automation_id

    @property
    def name(self) -> str:
        """The device's name: the automation's name."""
        return self._name()

    @property
    def entities(self) -> list[DeviceEntity]:
        """Every entity of the device, leftovers included."""
        return [
            DeviceEntity(self._store, entity.key, self._statistics, self._clock)
            for entity in self._store.entities()
        ]

    def entity(self, key: str | type) -> DeviceEntity:
        """Return the proxy of an entity.

        Args:
            key: The entity's object ID (or key), or the class that declares it.

        Raises:
            NonExistingEntityError: If the device has no such entity.
        """
        if isinstance(key, type):
            declaration = get_declaration(key)
            if declaration is None:
                raise NonExistingEntityError(key.__name__)
            key = declaration.object_id
        if self._store.get(str(key)) is None:
            raise NonExistingEntityError(str(key))
        return DeviceEntity(self._store, str(key), self._statistics, self._clock)
