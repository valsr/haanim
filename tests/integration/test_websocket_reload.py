"""Tests for the panel's and the card's subscriptions across a reload of the integration."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant

from tests.integration.test_device_entities import (  # noqa: F401  pylint: disable=unused-import
    CONTROLS,
    Setup,
    setup,
)


async def subscribe(client: Any, message_id: int, kind: str, automation_id: str) -> None:
    """Subscribe, check the answer, and read the first event."""
    await client.send_json({"id": message_id, "type": f"haanim/{kind}/subscribe", "automation_id": automation_id})
    answer = await client.receive_json()
    assert answer["success"] is True, answer
    await client.receive_json()


@pytest.mark.parametrize("kind", ["entities", "card", "logs"])
async def test_a_reload_ends_subscriptions(
    hass: HomeAssistant, hass_ws_client: Any, setup: Setup, kind: str  # noqa: F811
) -> None:
    """When the integration unloads, each subscription gets an "ended" event, so the frontend subscribes again."""
    manager = await setup({"heat": CONTROLS})
    client = await hass_ws_client()
    await subscribe(client, 1, kind, "heat")

    assert await hass.config_entries.async_reload(manager.entry.entry_id)
    await hass.async_block_till_done()
    seen = []
    while True:
        message = await client.receive_json()
        seen.append(message)
        if message.get("event") == {"ended": True}:
            break
    assert seen[-1] == {"id": 1, "type": "event", "event": {"ended": True}}

    await subscribe(client, 2, kind, "heat")


async def test_an_ended_subscription_is_forgotten(
    hass: HomeAssistant, hass_ws_client: Any, setup: Setup  # noqa: F811
) -> None:
    """Unsubscribing after the end does not fail, and nothing more comes for it."""
    manager = await setup({"heat": CONTROLS})
    client = await hass_ws_client()
    await subscribe(client, 1, "entities", "heat")
    assert await hass.config_entries.async_reload(manager.entry.entry_id)
    await hass.async_block_till_done()
    while (await client.receive_json()).get("event") != {"ended": True}:
        pass
    await client.send_json({"id": 2, "type": "unsubscribe_events", "subscription": 1})
    answer = await client.receive_json()
    assert answer["id"] == 2
