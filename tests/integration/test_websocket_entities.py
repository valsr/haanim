"""Tests for the websocket commands of the panel's entities tab."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.integration.test_device_entities import (  # noqa: F401  pylint: disable=unused-import
    CONTROLS,
    Setup,
    device_of,
    setup,
    write,
)

LEFTOVER = CONTROLS.replace("@button_entity", "# @button_entity")


async def command(client: Any, message_id: int, kind: str, **data: Any) -> dict[str, Any]:
    """Send a command and return its answer."""
    await client.send_json({"id": message_id, "type": kind, **data})
    return await client.receive_json()


async def with_leftover(hass: HomeAssistant, setup: Setup, tmp_path: Path) -> Any:  # noqa: F811
    """Set up the controls automation, then reload it without its button."""
    manager = await setup({"heat": CONTROLS})
    write(tmp_path, "heat", LEFTOVER)
    await manager.async_reload("heat")
    await hass.async_block_till_done()
    return manager


async def test_list(
    hass: HomeAssistant, hass_ws_client: Any, setup: Setup, tmp_path: Path
) -> None:  # noqa: F811
    await with_leftover(hass, setup, tmp_path)
    er.async_get(hass).async_update_entity("switch.haanim_heat_boost", new_entity_id="switch.my_boost")
    client = await hass_ws_client()
    answer = await command(client, 1, "haanim/entities/list", automation_id="heat")
    assert answer["success"] is True
    result = answer["result"]
    assert result["device_id"] == device_of(hass, "heat").id  # type: ignore[union-attr]
    by_key = {item["key"]: item for item in result["entities"]}
    assert by_key["boost"] == {
        "key": "boost",
        "object_id": "boost",
        "entity_id": "switch.my_boost",
        "platform": "switch",
        "name": "boost",
        "state": False,
        "declared": True,
    }
    assert by_key["ring"]["declared"] is False
    assert [item["key"] for item in result["entities"]] == ["boost", "lazy", "mode", "note", "ring", "target"]


async def test_entity_count(hass: HomeAssistant, hass_ws_client: Any, setup: Setup) -> None:  # noqa: F811
    await setup({"heat": CONTROLS})
    client = await hass_ws_client()
    answer = await command(client, 1, "haanim/automations/get", automation_id="heat")
    assert answer["result"]["entity_count"] == 6


async def test_remove_leftover(
    hass: HomeAssistant, hass_ws_client: Any, setup: Setup, tmp_path: Path
) -> None:  # noqa: F811
    manager = await with_leftover(hass, setup, tmp_path)
    client = await hass_ws_client()
    answer = await command(client, 1, "haanim/entities/remove", automation_id="heat", key="ring")
    assert answer["success"] is True
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get("button.haanim_heat_ring") is None
    assert manager.devices.store("heat").get("ring") is None


async def test_remove_declared_is_refused(
    hass: HomeAssistant, hass_ws_client: Any, setup: Setup
) -> None:  # noqa: F811
    await setup({"heat": CONTROLS})
    client = await hass_ws_client()
    answer = await command(client, 1, "haanim/entities/remove", automation_id="heat", key="boost")
    assert answer["success"] is False
    assert answer["error"] == {"code": "declared", "message": "delete the class first"}


async def test_lookups_leave_no_store(hass: HomeAssistant, setup: Setup) -> None:  # noqa: F811
    """What a stale entity reads of a device that is gone is nothing, and keeps nothing in memory for it."""
    manager = await setup({"heat": CONTROLS})
    sink = manager.entity_sink
    assert sink is not None
    assert sink.stored("ghost", "switch", "boost") is None
    assert manager.devices.get("ghost") is None
    assert sink.stored("heat", "switch", "boost") is not None


async def test_remove_unknown(hass: HomeAssistant, hass_ws_client: Any, setup: Setup) -> None:  # noqa: F811
    await setup({"heat": CONTROLS})
    client = await hass_ws_client()
    answer = await command(client, 1, "haanim/entities/remove", automation_id="heat", key="nope")
    assert answer["error"]["code"] == "not_found"


async def test_purge_resets_state(
    hass: HomeAssistant, hass_ws_client: Any, setup: Setup
) -> None:  # noqa: F811
    await setup({"heat": CONTROLS})
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.haanim_heat_target", "value": 25}, blocking=True
    )
    client = await hass_ws_client()
    answer = await command(client, 1, "haanim/entities/purge", automation_id="heat", key="target")
    assert answer["success"] is True
    await hass.async_block_till_done()
    assert hass.states.get("number.haanim_heat_target").state == "20.0"  # type: ignore[union-attr]


async def test_purge_leftover_and_unknown(
    hass: HomeAssistant, hass_ws_client: Any, setup: Setup, tmp_path: Path  # noqa: F811
) -> None:
    await with_leftover(hass, setup, tmp_path)
    client = await hass_ws_client()
    answer = await command(client, 1, "haanim/entities/purge", automation_id="heat", key="ring")
    assert answer["error"]["code"] == "leftover"
    answer = await command(client, 2, "haanim/entities/purge", automation_id="heat", key="nope")
    assert answer["error"]["code"] == "not_found"


async def test_unknown_automation(
    hass: HomeAssistant, hass_ws_client: Any, setup: Setup
) -> None:  # noqa: F811
    await setup({"heat": CONTROLS})
    client = await hass_ws_client()
    answer = await command(client, 1, "haanim/entities/list", automation_id="nope")
    assert answer["error"]["code"] == "not_found"


async def test_subscribe(hass: HomeAssistant, hass_ws_client: Any, setup: Setup) -> None:  # noqa: F811
    await setup({"heat": CONTROLS})
    client = await hass_ws_client()
    answer = await command(client, 1, "haanim/entities/subscribe", automation_id="heat")
    assert answer["success"] is True
    first = await client.receive_json()
    assert first["type"] == "event"
    assert len(first["event"]["entities"]) == 6
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.haanim_heat_boost"}, blocking=True
    )
    update = await client.receive_json()
    boost = next(item for item in update["event"]["entities"] if item["key"] == "boost")
    assert boost["state"] is True
