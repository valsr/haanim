"""What automations reach their device's entities through: ``haa.device`` and its entity proxies.

See "The automation API" in
``docs/superpowers/specs/2026-11-09-automation-devices-design.md``. A proxy
reads and writes the automation's ``DeviceStore`` each time it is used, so it
always shows the stored state.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from haanim.engine.device_entities import get_declaration
from haanim.engine.devices import DeviceStore, StoredEntity
from haanim.engine.errors import NonExistingEntityError


class DeviceEntity:
    """One entity of the automation's device."""

    __slots__ = ("_store", "_key")

    def __init__(self, store: DeviceStore, key: str) -> None:
        """Initialize the proxy of the entity with a key in a store."""
        self._store = store
        self._key = key

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


class HAAnimDevice:
    """The automation's device in Home Assistant, and its entities."""

    def __init__(self, store: DeviceStore, name: Callable[[], str]) -> None:
        """Initialize the device of a store.

        Args:
            store: The automation's entities.
            name: Returns the automation's name.
        """
        self._store = store
        self._name = name

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
        return [DeviceEntity(self._store, entity.key) for entity in self._store.entities()]

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
        return DeviceEntity(self._store, str(key))
