"""Websocket commands for the HAAnim panel and card.

- ``haanim/automations/list``: every automation with its state.
- ``haanim/automations/get``: the details of one automation.
- ``haanim/card/subscribe``: the card content of one automation, now and whenever it changes.
- ``haanim/logs/subscribe``: the recent log records of one automation, then each new one.
- ``haanim/config/get``: the integration's version and options.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import async_response, websocket_command
from homeassistant.components.websocket_api.messages import event_message
from homeassistant.core import HomeAssistant, callback

from custom_components.haanim.automation_manager import AutomationManager, async_get_manager
from custom_components.haanim.const import DOMAIN, VERSION
from custom_components.haanim.ha.host import HACardSink
from custom_components.haanim.log_buffer import AutomationLogBuffer
from custom_components.haanim.options import option_values

ERR_NOT_FOUND = "not_found"
ERR_NOT_READY = "not_ready"


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
    }


def _detail(manager: AutomationManager, automation_id: str) -> dict[str, Any]:
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
        "running_actions": list(status.running_actions.values()),
        "last_action": status.last_action,
        "last_action_time": times.last_action_time.isoformat() if times.last_action_time else None,
        "last_error": failure.as_dict() if failure else None,
        "actions": [
            {"name": action.name, "aliases": list(action.aliases), "description": action.description or ""}
            for action in manager.automation_actions(automation_id)
        ],
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
        connection.send_result(msg["id"], _detail(manager, msg["automation_id"]))


@websocket_command({vol.Required("type"): f"{DOMAIN}/card/subscribe", vol.Required("automation_id"): str})
@async_response
async def ws_subscribe_card(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Send the card content of an automation now and whenever it changes."""
    manager = await _manager_for(hass, connection, msg)
    if manager is None:
        return
    sink = manager.host.cards
    if not isinstance(sink, HACardSink):
        connection.send_error(msg["id"], ERR_NOT_READY, "Card content is not available")
        return

    @callback
    def forward(blocks: list[dict[str, Any]]) -> None:
        connection.send_message(event_message(msg["id"], {"blocks": blocks}))

    connection.subscriptions[msg["id"]] = sink.subscribe(msg["automation_id"], forward)
    connection.send_result(msg["id"])
    forward(sink.blocks(msg["automation_id"]))


@websocket_command({vol.Required("type"): f"{DOMAIN}/logs/subscribe", vol.Required("automation_id"): str})
@async_response
async def ws_subscribe_logs(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Send the recent log records of an automation as one event, then each new one."""
    if await _manager_for(hass, connection, msg) is None:
        return
    buffer = next(
        (
            data["log_buffer"]
            for data in hass.data.get(DOMAIN, {}).values()
            if isinstance(data, dict) and isinstance(data.get("log_buffer"), AutomationLogBuffer)
        ),
        None,
    )
    if buffer is None:
        connection.send_error(msg["id"], ERR_NOT_READY, "Log records are not available")
        return

    @callback
    def forward(record: dict[str, Any]) -> None:
        connection.send_message(event_message(msg["id"], {"record": record}))

    connection.subscriptions[msg["id"]] = buffer.subscribe(msg["automation_id"], forward)
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


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register the websocket commands."""
    async_register_command(hass, ws_list_automations)
    async_register_command(hass, ws_get_automation)
    async_register_command(hass, ws_subscribe_card)
    async_register_command(hass, ws_subscribe_logs)
    async_register_command(hass, ws_get_config)
