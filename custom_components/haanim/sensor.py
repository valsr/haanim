"""The automation entity: one enum sensor per automation.

The sensor's state is the automation's lifecycle state (``on``, ``off`` or
``error``); it is unavailable while the automation is not loaded. It is
read-only: automations are controlled through the panel, the services and the
``haa`` API.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.haanim.automation_manager import AutomationManager
from custom_components.haanim.const import DOMAIN

STATE_OPTIONS = ["on", "off", "error"]

ATTR_ENABLED = "enabled"
ATTR_MESSAGE = "message"
ATTR_LAST_RUN = "last_run"
ATTR_RUNNING_ACTIONS = "running_actions"
ATTR_LAST_ACTION = "last_action"
ATTR_LAST_ACTION_TIME = "last_action_time"
ATTR_LAST_ERROR = "last_error"

UNIQUE_ID_PREFIX = f"{DOMAIN}_"


def unique_id_of(automation_id: str) -> str:
    """Return the unique ID of an automation's entity."""
    return f"{UNIQUE_ID_PREFIX}{automation_id}"


class AutomationSensor(SensorEntity):
    """The state of one automation."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATE_OPTIONS
    _attr_icon = "mdi:animation"
    # These change often and would fill the database
    _unrecorded_attributes = frozenset(
        {ATTR_RUNNING_ACTIONS, ATTR_LAST_ACTION, ATTR_LAST_ACTION_TIME, ATTR_MESSAGE}
    )

    def __init__(self, manager: AutomationManager, automation_id: str) -> None:
        """Initialize the sensor.

        Args:
            manager: The automation manager.
            automation_id: ID of the automation the sensor stands for.
        """
        self._manager = manager
        self._automation_id = automation_id
        self._attr_unique_id = unique_id_of(automation_id)
        self.entity_id = f"sensor.{DOMAIN}_{automation_id}"
        self.added = False

    async def async_added_to_hass(self) -> None:
        """Note that the entity can write its state from now on."""
        self.added = True

    async def async_will_remove_from_hass(self) -> None:
        """Note that the entity is gone."""
        self.added = False

    @property
    def name(self) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The automation's name from its metadata."""
        return self._manager.automation_name(self._automation_id)

    @property
    def available(self) -> bool:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Whether the automation is loaded."""
        return self._manager.automation_state(self._automation_id) in STATE_OPTIONS

    @property
    def native_value(self) -> str | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The automation's lifecycle state."""
        state = self._manager.automation_state(self._automation_id)
        return state if state in STATE_OPTIONS else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The attributes of the design's table."""
        manager = self._manager
        automation_id = self._automation_id
        times = manager.automation_times(automation_id)
        status = manager.get_automation_status(automation_id)
        failure = manager.automation_last_error(automation_id)
        if manager.automation_state(automation_id) == "error":
            message = manager.automation_message(automation_id)
        else:
            message = manager.automation_status_message(automation_id)
        return {
            ATTR_ENABLED: manager.is_automation_enabled(automation_id),
            ATTR_MESSAGE: message,
            ATTR_LAST_RUN: times.run_time.isoformat() if times.run_time else None,
            ATTR_RUNNING_ACTIONS: list(status.running_actions.values()),
            ATTR_LAST_ACTION: status.last_action,
            ATTR_LAST_ACTION_TIME: times.last_action_time.isoformat() if times.last_action_time else None,
            ATTR_LAST_ERROR: failure.as_dict() if failure else None,
        }


class AutomationEntities:
    """Keeps one sensor per automation in step with the automation manager."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: AutomationManager,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        """Initialize with no entities."""
        self._hass = hass
        self._entry = entry
        self._manager = manager
        self._async_add_entities = async_add_entities
        self._entities: dict[str, AutomationSensor] = {}

    @callback
    def automation_changed(self, automation_id: str) -> None:
        """Create the automation's entity if it has none, or write its new state."""
        entity = self._entities.get(automation_id)
        if entity is None:
            if automation_id in self._manager.automation_ids():
                self._entities[automation_id] = AutomationSensor(self._manager, automation_id)
                self._async_add_entities([self._entities[automation_id]])
        elif entity.added:
            entity.async_write_ha_state()

    @callback
    def automation_removed(self, automation_id: str) -> None:
        """Remove the entity of an automation whose folder is gone."""
        entity = self._entities.pop(automation_id, None)
        registry = er.async_get(self._hass)
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id_of(automation_id))
        if entity_id is not None:
            registry.async_remove(entity_id)
        elif entity is not None and entity.added:
            self._hass.async_create_task(entity.async_remove())

    @callback
    def automations_loaded(self) -> None:
        """Remove the entities of automations whose folders went away while HAAnim was not running."""
        ids = set(self._manager.automation_ids())
        known = {unique_id_of(automation_id) for automation_id in ids}
        self._entities = {key: entity for key, entity in self._entities.items() if key in ids}
        registry = er.async_get(self._hass)
        for registered in er.async_entries_for_config_entry(registry, self._entry.entry_id):
            if registered.domain == "sensor" and registered.unique_id not in known:
                registry.async_remove(registered.entity_id)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensors of the automations, now and as automations come and go."""
    manager: AutomationManager = hass.data[DOMAIN][entry.entry_id]["manager"]
    entities = AutomationEntities(hass, entry, manager, async_add_entities)
    entry.async_on_unload(manager.add_listener(entities))
    for automation_id in manager.automation_ids():
        entities.automation_changed(automation_id)
    if manager.started:
        # Loaded before this platform was set up: a reload of the integration
        entities.automations_loaded()
