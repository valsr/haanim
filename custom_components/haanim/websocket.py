"""Websocket commands for the HAAnim panel and card.

- ``haanim/automations/list``: every automation with its state.
- ``haanim/automations/get``: the details of one automation.
- ``haanim/card/subscribe``: the card content of one automation, now and whenever it changes.
- ``haanim/logs/subscribe``: the recent log records of one automation, then each new one.
- ``haanim/config/get``: the integration's version and options.
- ``haanim/entities/list``: the entities of one automation's device.
- ``haanim/entities/subscribe``: the same, now and whenever an entity changes.
- ``haanim/entities/remove``: remove a leftover entity.
- ``haanim/entities/purge``: reset a declared entity's stored state and attributes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import probatio as vol
from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import async_response, websocket_command
from homeassistant.components.websocket_api.messages import event_message
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from haanim.const import OPTION_NAME
from custom_components.haanim.automation_manager import AutomationManager, async_get_manager
from custom_components.haanim.const import DOMAIN, VERSION
from custom_components.haanim.ha.host import HACardSink
from custom_components.haanim.log_buffer import AutomationLogBuffer, entry_item
from custom_components.haanim.log_levels import AutomationLogLevels
from custom_components.haanim.options import option_values

SUBSCRIPTIONS = f"{DOMAIN}_subscriptions"
"""Key in ``hass.data``: the live subscriptions, ended when the integration unloads."""

ERR_NOT_FOUND = "not_found"
ERR_NOT_READY = "not_ready"
ERR_DECLARED = "declared"
ERR_LEFTOVER = "leftover"


def _track(
    hass: HomeAssistant, connection: ActiveConnection, msg_id: int, unsubscribe: Callable[[], None]
) -> None:
    """Keep a subscription, so the integration can end it when it unloads."""
    tracked: dict[tuple[int, int], tuple[ActiveConnection, Callable[[], None]]] = hass.data.setdefault(
        SUBSCRIPTIONS, {}
    )
    key = (id(connection), msg_id)
    tracked[key] = (connection, unsubscribe)

    @callback
    def end() -> None:
        tracked.pop(key, None)
        unsubscribe()

    connection.subscriptions[msg_id] = end


@callback
def async_end_subscriptions(hass: HomeAssistant) -> None:
    """End every subscription with an ``{"ended": true}`` event: what it follows is going away.

    The panel and the card subscribe again, and get what the reloaded integration has.
    """
    tracked: dict[tuple[int, int], tuple[ActiveConnection, Callable[[], None]]] = hass.data.pop(
        SUBSCRIPTIONS, {}
    )
    for (_, msg_id), (connection, unsubscribe) in tracked.items():
        unsubscribe()
        connection.subscriptions.pop(msg_id, None)
        connection.send_message(event_message(msg_id, {"ended": True}))


def _entities(hass: HomeAssistant, manager: AutomationManager, automation_id: str) -> dict[str, Any]:
    """Return what the entities tab shows of an automation's device."""
    registry = er.async_get(hass)
    sink = manager.entity_sink
    items = []
    store = manager.devices.get(automation_id)
    for stored in store.entities() if store is not None else []:
        entity_id = registry.async_get_entity_id(stored.platform, DOMAIN, stored.unique_id(automation_id))
        items.append(
            {
                "key": stored.key,
                "object_id": stored.object_id,
                "entity_id": entity_id or stored.entity_id(automation_id),
                "platform": stored.platform,
                "name": stored.options.get(OPTION_NAME) or stored.object_id,
                "state": stored.state,
                "declared": stored.declared,
            }
        )
    return {"device_id": sink.device_id(automation_id) if sink else None, "entities": items}


def _summary(manager: AutomationManager, automation_id: str) -> dict[str, Any]:
    """Return what the list shows of an automation."""
    state = manager.automation_state(automation_id)
    message = (
        manager.automation_message(automation_id)
        if state == "error"
        else manager.automation_status_message(automation_id)
    )
    context = manager.get_context_by_name(automation_id)
    metadata = context.get_metadata() if context else None
    return {
        "id": automation_id,
        "name": manager.automation_name(automation_id),
        "version": metadata.version if metadata else "",
        "state": state,
        "enabled": manager.is_automation_enabled(automation_id),
        "message": message,
        "running_actions": list(manager.get_automation_status(automation_id).running_actions.values()),
    }


def _detail(
    manager: AutomationManager, automation_id: str, levels: AutomationLogLevels | None = None
) -> dict[str, Any]:
    """Return what the detail page shows of an automation."""
    context = manager.get_context_by_name(automation_id)
    metadata = context.get_metadata() if context else None
    times = manager.automation_times(automation_id)
    status = manager.get_automation_status(automation_id)
    failure = manager.automation_last_error(automation_id)
    return {
        **_summary(manager, automation_id),
        "description": metadata.description if metadata else "",
        "author": metadata.author if metadata else "",
        "last_run": times.run_time.isoformat() if times.run_time else None,
        "last_action": status.last_action,
        "last_action_time": times.last_action_time.isoformat() if times.last_action_time else None,
        "last_error": failure.as_dict() if failure else None,
        # The level set for the automation in HAAnim, if any, and the level its logger lets through
        "log_level": levels.level(automation_id) if levels else None,
        "effective_log_level": levels.effective(automation_id) if levels else None,
        "actions": [
            {"name": action.name, "aliases": list(action.aliases), "description": action.description or ""}
            for action in manager.automation_actions(automation_id)
        ],
        "entity_count": len(store.entities()) if (store := manager.devices.get(automation_id)) else 0,
    }


async def _manager_for(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> AutomationManager | None:
    """Return the manager, or answer with an error and return None.

    A message that names an automation is also answered with an error if there is no such automation.
    """
    manager = await async_get_manager(hass)
    if manager is None:
        connection.send_error(msg["id"], ERR_NOT_READY, "HAAnim is not set up")
        return None
    automation_id = msg.get("automation_id")
    if automation_id is not None and automation_id not in manager.automation_ids():
        connection.send_error(msg["id"], ERR_NOT_FOUND, f"No automation '{automation_id}'")
        return None
    return manager


@websocket_command({vol.Required("type"): f"{DOMAIN}/automations/list"})
@async_response
async def ws_list_automations(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Answer with every automation, sorted by ID."""
    manager = await _manager_for(hass, connection, msg)
    if manager is not None:
        connection.send_result(
            msg["id"], {"automations": [_summary(manager, item) for item in manager.automation_ids()]}
        )


@websocket_command({vol.Required("type"): f"{DOMAIN}/automations/get", vol.Required("automation_id"): str})
@async_response
async def ws_get_automation(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Answer with the details of one automation."""
    manager = await _manager_for(hass, connection, msg)
    if manager is not None:
        levels = entry_item(hass, "log_levels", AutomationLogLevels)
        connection.send_result(msg["id"], _detail(manager, msg["automation_id"], levels))


@websocket_command({vol.Required("type"): f"{DOMAIN}/card/subscribe", vol.Required("automation_id"): str})
@async_response
async def ws_subscribe_card(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Send the content, title and options of an automation's card now and whenever they change."""
    manager = await _manager_for(hass, connection, msg)
    if manager is None:
        return
    sink = manager.host.cards
    if not isinstance(sink, HACardSink):
        connection.send_error(msg["id"], ERR_NOT_READY, "Card content is not available")
        return

    @callback
    def forward(content: dict[str, Any]) -> None:
        connection.send_message(event_message(msg["id"], content))

    _track(hass, connection, msg["id"], sink.subscribe(msg["automation_id"], forward))
    connection.send_result(msg["id"])
    forward(sink.content(msg["automation_id"]))


@websocket_command({vol.Required("type"): f"{DOMAIN}/logs/subscribe", vol.Required("automation_id"): str})
@async_response
async def ws_subscribe_logs(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Send the recent log records of an automation as one event, then each new one."""
    if await _manager_for(hass, connection, msg) is None:
        return
    buffer = entry_item(hass, "log_buffer", AutomationLogBuffer)
    if buffer is None:
        connection.send_error(msg["id"], ERR_NOT_READY, "Log records are not available")
        return

    @callback
    def forward(change: dict[str, Any]) -> None:
        connection.send_message(event_message(msg["id"], change))

    _track(hass, connection, msg["id"], buffer.subscribe(msg["automation_id"], forward))
    connection.send_result(msg["id"])
    # The frontend's subscription helper only passes events on, so the kept records go as the first event
    connection.send_message(event_message(msg["id"], {"records": buffer.records(msg["automation_id"])}))


@websocket_command({vol.Required("type"): f"{DOMAIN}/config/get"})
@async_response
async def ws_get_config(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Answer with the integration's version and its options as they are in effect."""
    manager = await _manager_for(hass, connection, msg)
    if manager is not None:
        connection.send_result(msg["id"], {"version": VERSION, "options": option_values(manager.entry)})


@websocket_command({vol.Required("type"): f"{DOMAIN}/entities/list", vol.Required("automation_id"): str})
@async_response
async def ws_list_entities(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Answer with the entities of an automation's device, leftovers included."""
    manager = await _manager_for(hass, connection, msg)
    if manager is not None:
        connection.send_result(msg["id"], _entities(hass, manager, msg["automation_id"]))


@websocket_command({vol.Required("type"): f"{DOMAIN}/entities/subscribe", vol.Required("automation_id"): str})
@async_response
async def ws_subscribe_entities(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Send the entities of an automation's device now and whenever one changes or goes away."""
    manager = await _manager_for(hass, connection, msg)
    if manager is None:
        return
    sink = manager.entity_sink
    if sink is None:
        connection.send_error(msg["id"], ERR_NOT_READY, "Entities are not available")
        return
    automation_id = msg["automation_id"]

    @callback
    def forward() -> None:
        connection.send_message(event_message(msg["id"], _entities(hass, manager, automation_id)))

    _track(hass, connection, msg["id"], sink.subscribe(automation_id, forward))
    connection.send_result(msg["id"])
    forward()


@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/entities/remove",
        vol.Required("automation_id"): str,
        vol.Required("key"): str,
    }
)
@async_response
async def ws_remove_entity(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Remove a leftover entity from Home Assistant and from storage."""
    manager = await _manager_for(hass, connection, msg)
    if manager is None:
        return
    store = manager.devices.get(msg["automation_id"])
    stored = store.get(msg["key"]) if store is not None else None
    if store is None or stored is None:
        connection.send_error(msg["id"], ERR_NOT_FOUND, f"No entity '{msg['key']}'")
    elif stored.declared:
        connection.send_error(msg["id"], ERR_DECLARED, "delete the class first")
    else:
        store.remove(msg["key"])
        connection.send_result(msg["id"])


@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/entities/purge",
        vol.Required("automation_id"): str,
        vol.Required("key"): str,
    }
)
@async_response
async def ws_purge_entity(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Reset a declared entity's stored state and attributes to its declaration's initial ones."""
    manager = await _manager_for(hass, connection, msg)
    if manager is None:
        return
    store = manager.devices.get(msg["automation_id"])
    stored = store.get(msg["key"]) if store is not None else None
    if store is None or stored is None:
        connection.send_error(msg["id"], ERR_NOT_FOUND, f"No entity '{msg['key']}'")
    elif not stored.declared:
        connection.send_error(msg["id"], ERR_LEFTOVER, "A leftover cannot be purged; remove it instead")
    else:
        store.purge(msg["key"])
        connection.send_result(msg["id"])


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register the websocket commands."""
    async_register_command(hass, ws_list_automations)
    async_register_command(hass, ws_get_automation)
    async_register_command(hass, ws_subscribe_card)
    async_register_command(hass, ws_subscribe_logs)
    async_register_command(hass, ws_get_config)
    async_register_command(hass, ws_list_entities)
    async_register_command(hass, ws_subscribe_entities)
    async_register_command(hass, ws_remove_entity)
    async_register_command(hass, ws_purge_entity)
