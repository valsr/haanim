"""The devices of automations: their declared entities, the entities' state, and its storage.

See "Automation devices and declared entities" in
``docs/superpowers/specs/2026-11-09-automation-devices-design.md``. Each
automation's entities are kept in a ``DeviceStore``; one ``DeviceRegistry``
holds the stores of all automations, saves them, and tells the host's
``EntitySink`` about every change. The stores outlive the automations' code:
entities keep their state while an automation is stopped or reloaded.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from haanim.engine.device_entities import PLATFORMS, EntityDeclaration, validate_state
from haanim.interfaces import Clock, EntitySink, StorageBackend, TimerHandle
from haanim.engine.variables import SAVE_DELAY_SECONDS

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
INDEX_KEY = "devices"

# What entity IDs and unique IDs start with: the integration's domain
ID_PREFIX = "haanim"


def device_key(automation_id: str) -> str:
    """Return the storage key of an automation's entities."""
    return f"device.{automation_id}"


def _copy(value: Any) -> Any:
    """Return a copy of a JSON value, exactly as it reads back from storage."""
    return json.loads(json.dumps(value))


@dataclass
class StoredEntity:  # pylint: disable=too-many-instance-attributes
    """One entity of an automation's device, as stored.

    Args:
        key: The entity's key in its store: the object ID, or
            ``<object_id>@<platform>`` for a leftover whose object ID is now
            declared on another platform.
        object_id: The object ID the entity was declared with.
        platform: The Home Assistant platform.
        options: The declaration: ``name``, ``icon``, ``initial``,
            ``initial_attributes`` and the platform options.
        state: The state; None for unknown.
        attributes: The attributes.
        declared: Whether the automation's code declares the entity; False for a leftover.
        last_changed: When the state last changed.
    """

    key: str
    object_id: str
    platform: str
    options: dict[str, Any]
    state: Any = None
    attributes: dict[str, Any] = field(default_factory=dict)
    declared: bool = True
    last_changed: datetime | None = None

    def entity_id(self, automation_id: str) -> str:
        """Return the entity ID Home Assistant gives the entity unless the owner renames it."""
        return f"{self.platform}.{ID_PREFIX}_{automation_id}_{self.object_id}"

    def unique_id(self, automation_id: str) -> str:
        """Return the entity's unique ID; unique within its platform.

        The dot cannot be part of an automation ID or an object ID, so the IDs of
        two automations never collide, nor with a status sensor's ``haanim_<id>``.
        """
        return f"{ID_PREFIX}_{automation_id}.{self.object_id}"

    @property
    def platform_options(self) -> dict[str, Any]:
        """The platform options: the declaration without name, icon and initial values."""
        common = ("name", "icon", "initial", "initial_attributes")
        return {key: value for key, value in self.options.items() if key not in common}

    def as_dict(self) -> dict[str, Any]:
        """Return the entity as it is saved."""
        return {
            "object_id": self.object_id,
            "platform": self.platform,
            "options": self.options,
            "state": self.state,
            "attributes": self.attributes,
            "declared": self.declared,
            "last_changed": self.last_changed.isoformat() if self.last_changed else None,
        }

    @classmethod
    def from_dict(cls, key: str, data: dict[str, Any]) -> StoredEntity:
        """Build an entity from what was saved."""
        changed = data.get("last_changed")
        return cls(
            key=key,
            object_id=data.get("object_id") or key.split("@", 1)[0],
            platform=data["platform"],
            options=dict(data.get("options") or {}),
            state=data.get("state"),
            attributes=dict(data.get("attributes") or {}),
            declared=bool(data.get("declared", True)),
            last_changed=datetime.fromisoformat(changed) if changed else None,
        )


class DeviceStore:
    """The entities of one automation's device."""

    def __init__(self, automation_id: str, registry: DeviceRegistry) -> None:
        """Initialize an empty store; the registry fills it from storage."""
        self.automation_id = automation_id
        self._registry = registry
        self._entities: dict[str, StoredEntity] = {}
        self._seeds: dict[str, Any] = {}

    def seed(self, states: dict[str, Any]) -> None:
        """Give entities that do not exist yet the state they are created with instead of their initial one.

        The test harness's way to start an automation with stored entity states.
        """
        self._seeds.update(states)

    @property
    def registry(self) -> DeviceRegistry:
        """The registry that holds and saves this store."""
        return self._registry

    async def flush(self) -> None:
        """Write this store's pending changes now."""
        await self._registry.flush(self.automation_id)

    # --- Reading ------------------------------------------------------------------

    def entities(self) -> list[StoredEntity]:
        """Return every entity, leftovers included, sorted by key."""
        return [self._entities[key] for key in sorted(self._entities)]

    def get(self, key: str) -> StoredEntity | None:
        """Return the entity with a key, or None."""
        return self._entities.get(key)

    def find(self, platform: str, object_id: str) -> StoredEntity | None:
        """Return the entity of a platform with an object ID, or None; how Home Assistant's entities look."""
        for entity in self._entities.values():
            if entity.platform == platform and entity.object_id == object_id:
                return entity
        return None

    def _require(self, key: str) -> StoredEntity:
        entity = self._entities.get(key)
        if entity is None:
            raise KeyError(f"'{self.automation_id}' has no entity '{key}'")
        return entity

    # --- Declarations -------------------------------------------------------------

    def reconcile(self, declarations: list[EntityDeclaration]) -> list[str]:
        """Bring the stored entities in line with what the automation's code declares.

        A new declaration creates its entity with the declaration's initial
        state. A declared entity that is stored keeps its state and attributes
        and takes the new declaration; a stored state the declaration no longer
        allows is reset to the initial state. A stored entity that is not
        declared becomes a leftover.

        Args:
            declarations: The automation's declarations; their object IDs are distinct.

        Returns:
            One warning for each stored state that was reset.
        """
        warnings: list[str] = []
        touched: list[str] = []
        declared_keys: set[str] = set()
        for declaration in declarations:
            key = self._place(declaration, touched)
            entity = self._entities.get(key)
            if entity is None:
                entity = self._create(declaration)
            else:
                entity.options = _copy(declaration.as_stored())
                entity.declared = True
                if not PLATFORMS[entity.platform].stateful:
                    self._entities[key] = entity
                    declared_keys.add(key)
                    touched.append(key)
                    continue
                try:
                    entity.state = validate_state(entity.platform, entity.platform_options, entity.state)
                except ValueError as err:
                    warnings.append(
                        f"Entity '{key}': the stored state {entity.state!r} no longer fits ({err}); "
                        f"it is reset to {declaration.initial!r}"
                    )
                    entity.state = _copy(declaration.initial)
                    entity.last_changed = self._registry.clock.now()
            self._entities[key] = entity
            declared_keys.add(key)
            touched.append(key)

        for key, entity in self._entities.items():
            if key not in declared_keys and entity.declared:
                entity.declared = False
                touched.append(key)

        for key in dict.fromkeys(touched):
            self._registry.entity_changed(self.automation_id, key)
        return warnings

    def _place(self, declaration: EntityDeclaration, touched: list[str]) -> str:
        """Return the key a declaration's entity is kept under, moving entities of another platform aside."""
        key = declaration.object_id
        current = self._entities.get(key)
        if current is not None and current.platform != declaration.platform:
            # The object ID moved to another platform: the old entity stays as a leftover
            aside = f"{key}@{current.platform}"
            current.key, current.declared = aside, False
            self._entities[aside] = current
            del self._entities[key]
            touched.append(aside)
        returning = self._entities.pop(f"{key}@{declaration.platform}", None)
        if returning is not None:
            # A leftover of this platform with this object ID is declared again
            returning.key = key
            self._entities[key] = returning
        return key

    def _create(self, declaration: EntityDeclaration) -> StoredEntity:
        """Create the entity of a new declaration."""
        stateful = PLATFORMS[declaration.platform].stateful
        initial = declaration.initial
        if stateful and declaration.object_id in self._seeds:
            initial = validate_state(
                declaration.platform, declaration.options, self._seeds.pop(declaration.object_id)
            )
        return StoredEntity(
            key=declaration.object_id,
            object_id=declaration.object_id,
            platform=declaration.platform,
            options=_copy(declaration.as_stored()),
            state=_copy(initial) if stateful else None,
            attributes=_copy(declaration.attributes),
            declared=True,
            last_changed=self._registry.clock.now(),
        )

    # --- Changes ------------------------------------------------------------------

    def _writable(self, key: str) -> StoredEntity:
        entity = self._require(key)
        if not entity.declared:
            raise ValueError(f"Entity '{key}' is no longer declared; it cannot be changed")
        return entity

    def set_state(self, key: str, value: Any) -> None:
        """Validate and store a new state.

        Raises:
            KeyError: If there is no such entity.
            ValueError: If the entity is a leftover or a button, or the declaration does not allow the value.
        """
        entity = self._writable(key)
        state = _copy(validate_state(entity.platform, entity.platform_options, value))
        if state != entity.state:
            entity.state = state
            entity.last_changed = self._registry.clock.now()
        self._registry.entity_changed(self.automation_id, key)

    def set_attributes(self, key: str, **attributes: Any) -> None:
        """Merge attributes into the entity's; an attribute given as None is removed.

        Raises:
            KeyError: If there is no such entity.
            ValueError: If the entity is a leftover.
            TypeError: If a value is not JSON.
        """
        entity = self._writable(key)
        merged = dict(entity.attributes)
        for name, value in attributes.items():
            if value is None:
                merged.pop(name, None)
            else:
                merged[name] = value
        entity.attributes = _copy(merged)
        self._registry.entity_changed(self.automation_id, key)

    def purge(self, key: str) -> None:
        """Reset a declared entity's state and attributes to its declaration's initial ones.

        Raises:
            KeyError: If there is no such entity.
            ValueError: If the entity is a leftover.
        """
        entity = self._require(key)
        if not entity.declared:
            raise ValueError(f"Entity '{key}' is a leftover; remove it instead")
        entity.state = _copy(entity.options.get("initial"))
        entity.attributes = _copy(entity.options.get("initial_attributes") or {})
        entity.last_changed = self._registry.clock.now()
        self._registry.entity_changed(self.automation_id, key)

    def remove(self, key: str) -> None:
        """Remove a leftover.

        Raises:
            KeyError: If there is no such entity.
            ValueError: If the entity is declared: it would come back at the next start.
        """
        entity = self._require(key)
        if entity.declared:
            raise ValueError(f"Entity '{key}' is declared by the automation's code; delete the class first")
        del self._entities[key]
        self._registry.entity_removed(self.automation_id, entity)

    # --- Storage ------------------------------------------------------------------

    def as_document(self) -> dict[str, Any]:
        """Return what is saved."""
        return {
            "version": STORAGE_VERSION,
            "entities": {key: entity.as_dict() for key, entity in self._entities.items()},
        }

    def load_document(self, document: Any) -> None:
        """Replace the entities with what was saved."""
        entities = document.get("entities") if isinstance(document, dict) else None
        self._entities = {}
        for key, data in (entities or {}).items():
            try:
                self._entities[key] = StoredEntity.from_dict(key, data)
            except (KeyError, TypeError, ValueError) as err:
                _LOGGER.error("Ignoring stored entity '%s' of '%s': %s", key, self.automation_id, err)


class DeviceRegistry:
    """The device stores of all automations, their storage, and the host's entity sink."""

    def __init__(self, storage: StorageBackend, clock: Clock, sink: EntitySink | None) -> None:
        """Initialize with no stores; ``load_all()`` reads what was saved.

        Args:
            storage: Where the stores are saved.
            clock: The clock of timestamps and of the delayed write.
            sink: Told about every change; None if the host shows no entities.
        """
        self._storage = storage
        self.clock = clock
        self.sink = sink
        self._stores: dict[str, DeviceStore] = {}
        self._dirty: set[str] = set()
        self._saved_index: list[str] = []
        self._timer: TimerHandle | None = None
        self._writes: set[asyncio.Future[None]] = set()

    async def load_all(self) -> None:
        """Read every saved store, and tell the sink about each entity."""
        index = await self._storage.load(INDEX_KEY)
        self._saved_index = sorted(i for i in index if isinstance(i, str)) if isinstance(index, list) else []
        for automation_id in self._saved_index:
            store = DeviceStore(automation_id, self)
            store.load_document(await self._storage.load(device_key(automation_id)))
            self._stores[automation_id] = store
        if self.sink is not None:
            for automation_id in self._saved_index:
                for entity in self._stores[automation_id].entities():
                    self.sink.entity_changed(automation_id, entity.key)

    async def load(self, automation_id: str) -> DeviceStore:
        """Read one automation's saved store, replacing the store in memory, and return it."""
        store = self.store(automation_id)
        store.load_document(await self._storage.load(device_key(automation_id)))
        if store.entities() and automation_id not in self._saved_index:
            index = await self._storage.load(INDEX_KEY)
            self._saved_index = sorted(index) if isinstance(index, list) else []
        return store

    def store(self, automation_id: str) -> DeviceStore:
        """Return an automation's store, creating an empty one on first use."""
        store = self._stores.get(automation_id)
        if store is None:
            store = self._stores[automation_id] = DeviceStore(automation_id, self)
        return store

    def automation_ids(self) -> list[str]:
        """Return the IDs of the automations that have entities, sorted."""
        return sorted(automation_id for automation_id, store in self._stores.items() if store.entities())

    async def remove_device(self, automation_id: str) -> None:
        """Forget an automation's entities and tell the sink its device is gone."""
        if self._stores.pop(automation_id, None) is None and automation_id not in self._saved_index:
            return
        self._dirty.discard(automation_id)
        await self._storage.save(device_key(automation_id), None)
        await self._save_index()
        if self.sink is not None:
            self.sink.device_removed(automation_id)

    # --- Called by the stores -----------------------------------------------------

    def entity_changed(self, automation_id: str, key: str) -> None:
        """Note a change of an entity: schedule a save and tell the sink."""
        self._schedule(automation_id)
        if self.sink is not None:
            try:
                self.sink.entity_changed(automation_id, key)
            except Exception:  # pylint: disable=broad-exception-caught
                # What the host fails to show is its problem: the change is stored
                _LOGGER.exception("Failed to show entity '%s' of '%s'", key, automation_id)

    def entity_removed(self, automation_id: str, entity: StoredEntity) -> None:
        """Note that a leftover was removed: schedule a save and tell the sink."""
        self._schedule(automation_id)
        if self.sink is not None:
            try:
                self.sink.entity_removed(automation_id, entity)
            except Exception:  # pylint: disable=broad-exception-caught
                _LOGGER.exception("Failed to remove entity '%s' of '%s'", entity.key, automation_id)

    # --- Writing ------------------------------------------------------------------

    def _schedule(self, automation_id: str) -> None:
        self._dirty.add(automation_id)
        if self._timer is None:
            self._timer = self.clock.call_later(SAVE_DELAY_SECONDS, self._write_later)

    def _write_later(self) -> None:
        self._timer = None
        write = asyncio.ensure_future(self._write(None))
        self._writes.add(write)
        write.add_done_callback(self._writes.discard)

    async def _write(self, only: str | None) -> None:
        """Write the changed stores (or only one), then the index if it changed.

        The document is built now, not when the change was made, so later
        changes, purges and removals are what is saved.
        """
        targets = sorted(self._dirty) if only is None else [only] if only in self._dirty else []
        for automation_id in targets:
            self._dirty.discard(automation_id)
            store = self._stores.get(automation_id)
            if store is None:
                continue
            try:
                await self._storage.save(device_key(automation_id), store.as_document())
            except Exception as err:  # pylint: disable=broad-exception-caught
                self._dirty.add(automation_id)
                _LOGGER.error("Failed to save the entities of '%s': %s", automation_id, err)
        await self._save_index()

    async def _save_index(self) -> None:
        index = self.automation_ids()
        if index != self._saved_index:
            await self._storage.save(INDEX_KEY, copy.copy(index))
            self._saved_index = index

    async def flush(self, automation_id: str | None = None) -> None:
        """Write pending changes now: of every automation, or of one when it stops."""
        if automation_id is None and self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._writes:
            await asyncio.gather(*self._writes, return_exceptions=True)
        await self._write(automation_id)
