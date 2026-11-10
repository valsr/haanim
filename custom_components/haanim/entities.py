"""The entities automations declare, in Home Assistant: the sink, the device, and the shared entity class.

See "Integration side" in
``docs/superpowers/specs/2026-11-09-automation-devices-design.md``. The
engine's ``DeviceRegistry`` holds every entity's declaration and state; the
Home Assistant entities hold none of their own and read it from there. The
sink creates the entities as the platforms come up and as automations declare
them, writes their state when it changes, and removes leftovers and devices.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.haanim.const import DOMAIN
from haanim.const import OPTION_ICON, OPTION_NAME
from haanim.engine.devices import DeviceRegistry, StoredEntity

if TYPE_CHECKING:
    from custom_components.haanim.automation_manager import AutomationManager

_LOGGER = logging.getLogger(__name__)

MANUFACTURER = "HAAnim"

# (automation ID, platform, object ID): what identifies an entity in Home Assistant
EntityKey = tuple[str, str, str]
EntityListener = Callable[[], None]


def device_info(automation_id: str, name: str) -> DeviceInfo:
    """Return the device of an automation, as its entities announce it."""
    return DeviceInfo(identifiers={(DOMAIN, automation_id)}, name=name, manufacturer=MANUFACTURER)


class DeclaredEntity(Entity):
    """An entity an automation declares; its state is in the engine's device registry."""

    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, sink: HAEntitySink, automation_id: str, stored: StoredEntity) -> None:
        """Initialize the entity of a stored entity."""
        self._sink = sink
        self._automation_id = automation_id
        self._platform_name = stored.platform
        self._object_id = stored.object_id
        self._attr_unique_id = stored.unique_id(automation_id)
        self.entity_id = stored.entity_id(automation_id)
        self._attr_device_info = device_info(automation_id, sink.automation_name(automation_id))
        self.added = False

    async def async_added_to_hass(self) -> None:
        """Note that the entity can write its state from now on."""
        self.added = True

    async def async_will_remove_from_hass(self) -> None:
        """Note that the entity is gone."""
        self.added = False

    @property
    def stored(self) -> StoredEntity | None:
        """What the engine holds of the entity; None once it is removed."""
        return self._sink.stored(self._automation_id, self._platform_name, self._object_id)

    @property
    def declaration(self) -> dict[str, Any]:
        """The declaration's options; empty once the entity is removed."""
        stored = self.stored
        return stored.options if stored else {}

    @property
    def state_value(self) -> Any:
        """The stored state; None while unknown."""
        stored = self.stored
        return stored.state if stored else None

    @property
    def available(self) -> bool:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Whether the automation's code declares the entity: a leftover is unavailable."""
        stored = self.stored
        return stored is not None and stored.declared

    @property
    def name(self) -> str | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared name."""
        return self.declaration.get(OPTION_NAME) or self._object_id

    @property
    def icon(self) -> str | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared icon."""
        return self.declaration.get(OPTION_ICON)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The attributes the automation set."""
        stored = self.stored
        return dict(stored.attributes) if stored else {}

    async def async_command(self, command: str, value: Any = None) -> None:
        """Hand a command from Home Assistant to the automation's hook."""
        await self._sink.command(self._automation_id, self._object_id, command, value, self._context)


def state_text(value: Any) -> Any:
    """Return a state Home Assistant can show: lists and dictionaries as JSON."""
    return json.dumps(value) if isinstance(value, (list, dict)) else value


class HAEntitySink:
    """The engine's ``EntitySink`` in Home Assistant."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize with no platforms set up and no registry attached."""
        self._hass = hass
        self._registry: DeviceRegistry | None = None
        self._manager: AutomationManager | None = None
        self._entry: ConfigEntry | None = None
        self._platforms: dict[str, tuple[type[DeclaredEntity], AddEntitiesCallback]] = {}
        self._entities: dict[EntityKey, DeclaredEntity] = {}
        self._listeners: dict[str, list[EntityListener]] = {}

    def attach(self, registry: DeviceRegistry, manager: AutomationManager, entry: ConfigEntry) -> None:
        """Read the entities from a registry, and send commands through a manager."""
        self._registry, self._manager, self._entry = registry, manager, entry

    def detach(self) -> None:
        """Forget the platforms and entities: the integration is being unloaded."""
        self._platforms.clear()
        self._entities.clear()

    # --- What the entities read ---------------------------------------------------

    def stored(self, automation_id: str, platform: str, object_id: str) -> StoredEntity | None:
        """Return what the engine holds of an entity, or None."""
        if self._registry is None:
            return None
        return self._registry.store(automation_id).find(platform, object_id)

    def automation_name(self, automation_id: str) -> str:
        """Return an automation's name: the name of its device."""
        return self._manager.automation_name(automation_id) if self._manager else automation_id

    async def command(
        self, automation_id: str, object_id: str, command: str, value: Any, context: Any
    ) -> None:
        """Send a command to an automation's entity."""
        if self._manager is not None:
            await self._manager.async_entity_command(automation_id, object_id, command, value, context)

    # --- Platforms ----------------------------------------------------------------

    @callback
    def platform_ready(
        self, platform: str, entity_class: type[DeclaredEntity], add_entities: AddEntitiesCallback
    ) -> None:
        """Take a platform that is set up, and create the entities of that platform that are stored."""
        self._platforms[platform] = (entity_class, add_entities)
        if self._registry is None:
            return
        for automation_id in self._registry.automation_ids():
            for stored in self._registry.store(automation_id).entities():
                if stored.platform == platform:
                    self._create(automation_id, stored)

    def _create(self, automation_id: str, stored: StoredEntity) -> None:
        key = (automation_id, stored.platform, stored.object_id)
        ready = self._platforms.get(stored.platform)
        if key in self._entities or ready is None:
            return
        entity_class, add_entities = ready
        entity = self._entities[key] = entity_class(self, automation_id, stored)
        add_entities([entity])

    # --- EntitySink ---------------------------------------------------------------

    @callback
    def entity_changed(self, automation_id: str, key: str) -> None:
        """Create the entity if it is new, else write its state."""
        if self._registry is not None:
            stored = self._registry.store(automation_id).get(key)
            if stored is not None:
                entity = self._entities.get((automation_id, stored.platform, stored.object_id))
                if entity is None:
                    self._create(automation_id, stored)
                elif entity.added:
                    entity.async_write_ha_state()
        self._notify(automation_id)

    @callback
    def entity_removed(self, automation_id: str, entity: StoredEntity) -> None:
        """Remove a leftover from Home Assistant."""
        self._entities.pop((automation_id, entity.platform, entity.object_id), None)
        registry = er.async_get(self._hass)
        entity_id = registry.async_get_entity_id(entity.platform, DOMAIN, entity.unique_id(automation_id))
        if entity_id is not None:
            registry.async_remove(entity_id)
        self._notify(automation_id)

    @callback
    def device_removed(self, automation_id: str) -> None:
        """Remove an automation's device and every entity of it."""
        for key in [key for key in self._entities if key[0] == automation_id]:
            del self._entities[key]
        device = self._device(automation_id)
        if device is not None:
            # The entities of this device and of no other; removing only the device would keep them
            registry = er.async_get(self._hass)
            for entry in er.async_entries_for_device(registry, device.id, include_disabled_entities=True):
                registry.async_remove(entry.entity_id)
            dr.async_get(self._hass).async_remove_device(device.id)
        self._notify(automation_id)

    # --- The device ---------------------------------------------------------------

    @callback
    def sync_device_name(self, automation_id: str) -> None:
        """Give an automation's device the automation's current name."""
        device = self._device(automation_id)
        name = self.automation_name(automation_id)
        if device is not None and device.name != name:
            dr.async_get(self._hass).async_update_device(device.id, name=name)

    def _device(self, automation_id: str) -> dr.DeviceEntry | None:
        """Return an automation's device, or None."""
        if self._entry is None:
            return None
        return dr.async_get(self._hass).async_get_device_by_identifier(
            (DOMAIN, automation_id), self._entry.entry_id
        )

    def device_id(self, automation_id: str) -> str | None:
        """Return the ID of an automation's device in Home Assistant, or None."""
        device = self._device(automation_id)
        return device.id if device else None

    # --- Listeners (the panel) ----------------------------------------------------

    def subscribe(self, automation_id: str, listener: EntityListener) -> Callable[[], None]:
        """Call ``listener()`` whenever an entity of an automation changes or goes away."""
        self._listeners.setdefault(automation_id, []).append(listener)

        def unsubscribe() -> None:
            listeners = self._listeners.get(automation_id, [])
            if listener in listeners:
                listeners.remove(listener)

        return unsubscribe

    def _notify(self, automation_id: str) -> None:
        for listener in list(self._listeners.get(automation_id, [])):
            listener()


async def async_setup_declared_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    platform: str,
    entity_class: type[DeclaredEntity],
) -> None:
    """Set up one platform of declared entities: create the stored ones, and the ones declared later."""
    manager: AutomationManager = hass.data[DOMAIN][entry.entry_id]["manager"]
    sink = manager.entity_sink
    if sink is not None:
        sink.platform_ready(platform, entity_class, async_add_entities)
