"""Tests for the websocket commands of the panel and the card.

See "GUI" in the design.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant

from custom_components.haanim.automation_manager import AutomationManager
from custom_components.haanim.const import VERSION
from custom_components.haanim.ha.host import HACardSink
from custom_components.haanim.websocket import async_register_websocket
from tests.integration.test_sensor import manager, root, write  # noqa: F401  pylint: disable=unused-import

CLIMATE = """
from haanim import haa, action, startup

@startup
def build_card(event):
    haa.card.text("intro", "## Climate")
    haa.card.value("alerts", label="Alerts today", value=0)

@action(aliases=["bump"], description="Count one alert.")
def alert(event):
    haa.card.value("alerts", label="Alerts today", value=1)
    haa.set_message("alerted")
"""

BLOCKS = [
    {"id": "intro", "type": "text", "markdown": "## Climate"},
    {"id": "alerts", "type": "value", "label": "Alerts today", "value": 0, "unit": ""},
]


@pytest.fixture
def root(tmp_path: Path) -> Path:  # noqa: F811
    """The automations folder: one automation with a card, one plain, one broken."""
    write(
        tmp_path,
        "climate",
        CLIMATE,
        '{"name": "Climate", "description": "Keeps it cool", "author": "Ada", "version": "1.2.0"}',
    )
    write(tmp_path, "plain", "x = 1\n")
    write(tmp_path, "broken", "def broken(:\n")
    return tmp_path


async def command(client: Any, message_id: int, kind: str, **data: Any) -> dict[str, Any]:
    """Send a command and return its answer."""
    await client.send_json({"id": message_id, "type": kind, **data})
    return await client.receive_json()


@pytest.mark.usefixtures("manager")
class TestList:
    """haanim/automations/list."""

    async def test_list(self, hass_ws_client: Any) -> None:
        """Test every automation is listed with ID, name, state, enabled flag and message, sorted by ID."""
        client = await hass_ws_client()
        answer = await command(client, 1, "haanim/automations/list")
        assert answer["success"] is True
        automations = answer["result"]["automations"]
        assert [item["id"] for item in automations] == ["broken", "climate", "plain"]
        assert automations[1] == {
            "id": "climate",
            "name": "Climate",
            "version": "1.2.0",
            "state": "on",
            "enabled": True,
            "message": None,
        }
        assert automations[0]["state"] == "error"
        assert "main.py:1" in automations[0]["message"]


@pytest.mark.usefixtures("manager")
class TestDetail:
    """haanim/automations/get."""

    async def test_detail(self, hass_ws_client: Any, manager: AutomationManager) -> None:  # noqa: F811
        """Test the detail has the metadata, the state, the times and the actions."""
        client = await hass_ws_client()
        answer = await command(client, 1, "haanim/automations/get", automation_id="climate")
        assert answer["result"] == {
            "id": "climate",
            "name": "Climate",
            "version": "1.2.0",
            "state": "on",
            "enabled": True,
            "message": None,
            "description": "Keeps it cool",
            "author": "Ada",
            "last_run": manager.automation_times("climate").run_time.isoformat(),
            "running_actions": [],
            "last_action": None,
            "last_action_time": None,
            "last_error": None,
            "actions": [{"name": "alert", "aliases": ["bump"], "description": "Count one alert."}],
        }

    async def test_detail_after_an_action(
        self, hass_ws_client: Any, manager: AutomationManager
    ) -> None:  # noqa: F811
        """Test the message and the last action follow what the automation does."""
        await manager.async_call_action("climate", "alert")
        client = await hass_ws_client()
        result = (await command(client, 1, "haanim/automations/get", automation_id="climate"))["result"]
        assert result["message"] == "alerted"
        assert result["last_action"] == "alert"
        assert result["last_action_time"] is not None

    async def test_detail_of_a_broken_automation(self, hass_ws_client: Any) -> None:
        """Test an automation that failed to load has its reason and no actions."""
        client = await hass_ws_client()
        result = (await command(client, 1, "haanim/automations/get", automation_id="broken"))["result"]
        assert result["state"] == "error"
        assert "main.py:1" in result["message"]
        assert result["actions"] == []
        assert result["description"] == ""

    @pytest.mark.parametrize("kind", ["haanim/automations/get", "haanim/card/subscribe"])
    async def test_unknown_automation(self, hass_ws_client: Any, kind: str) -> None:
        """Test an unknown automation is answered with not_found."""
        client = await hass_ws_client()
        answer = await command(client, 1, kind, automation_id="nobody")
        assert answer["success"] is False
        assert answer["error"]["code"] == "not_found"

    async def test_automation_id_is_required(self, hass_ws_client: Any) -> None:
        """Test a command without the automation ID is refused."""
        client = await hass_ws_client()
        answer = await command(client, 1, "haanim/automations/get")
        assert answer["success"] is False
        assert answer["error"]["code"] == "invalid_format"


@pytest.mark.usefixtures("manager")
class TestCardSubscription:
    """haanim/card/subscribe."""

    async def test_current_content_first(self, hass_ws_client: Any) -> None:
        """Test a subscriber gets the card as it is now."""
        client = await hass_ws_client()
        assert (await command(client, 1, "haanim/card/subscribe", automation_id="climate"))["success"] is True
        event = await client.receive_json()
        assert event == {"id": 1, "type": "event", "event": {"blocks": BLOCKS}}

    async def test_update_on_change(
        self, hass_ws_client: Any, manager: AutomationManager
    ) -> None:  # noqa: F811
        """Test a change made by the automation is sent to the subscriber."""
        client = await hass_ws_client()
        await command(client, 1, "haanim/card/subscribe", automation_id="climate")
        await client.receive_json()

        await manager.async_call_action("climate", "alert")
        event = await client.receive_json()
        assert event["event"]["blocks"][1]["value"] == 1
        assert event["event"]["blocks"][0] == BLOCKS[0]

    async def test_empty_when_stopped(
        self, hass_ws_client: Any, manager: AutomationManager
    ) -> None:  # noqa: F811
        """Test stopping the automation sends an empty card; starting it sends the card again."""
        client = await hass_ws_client()
        await command(client, 1, "haanim/card/subscribe", automation_id="climate")
        await client.receive_json()

        await manager.async_stop_automation("climate")
        assert (await client.receive_json())["event"] == {"blocks": []}
        await manager.async_start_automation("climate")
        assert (await client.receive_json())["event"] == {"blocks": BLOCKS}

    async def test_automation_without_a_card(self, hass_ws_client: Any) -> None:
        """Test an automation that puts nothing on its card has an empty one."""
        client = await hass_ws_client()
        await command(client, 1, "haanim/card/subscribe", automation_id="plain")
        assert (await client.receive_json())["event"] == {"blocks": []}

    async def test_only_the_subscribed_automation(
        self, hass_ws_client: Any, manager: AutomationManager
    ) -> None:  # noqa: F811
        """Test a subscriber of one automation gets nothing about another; unsubscribing ends it."""
        client = await hass_ws_client()
        await command(client, 1, "haanim/card/subscribe", automation_id="plain")
        await client.receive_json()
        await manager.async_call_action("climate", "alert")

        answer = await command(client, 2, "unsubscribe_events", subscription=1)
        assert answer == {"id": 2, "type": "result", "success": True, "result": None}
        assert manager.host.cards._listeners["plain"] == []  # pylint: disable=protected-access


class TestWithoutIntegration:
    """The commands while HAAnim is not set up."""

    @pytest.mark.parametrize(
        ("kind", "data"),
        [
            ("haanim/automations/list", {}),
            ("haanim/automations/get", {"automation_id": "climate"}),
            ("haanim/card/subscribe", {"automation_id": "climate"}),
            ("haanim/logs/subscribe", {"automation_id": "climate"}),
            ("haanim/config/get", {}),
        ],
    )
    async def test_not_ready(
        self, hass: HomeAssistant, hass_ws_client: Any, kind: str, data: dict[str, Any]
    ) -> None:
        """Test every command is answered with not_ready."""
        client = await hass_ws_client()
        async_register_websocket(hass)
        answer = await command(client, 1, kind, **data)
        assert answer["success"] is False
        assert answer["error"]["code"] == "not_ready"


class TestCardSink:
    """The sink the engine hands the card content to."""

    def test_keeps_and_forwards(self) -> None:
        """Test the sink keeps the latest content and tells subscribers until they unsubscribe."""
        sink = HACardSink()
        seen: list[list[dict[str, Any]]] = []
        assert sink.blocks("a") == []
        unsubscribe = sink.subscribe("a", seen.append)

        sink.card_changed("a", [{"id": "x"}])
        sink.card_changed("b", [{"id": "y"}])
        unsubscribe()
        unsubscribe()
        sink.card_changed("a", [])

        assert seen == [[{"id": "x"}]]
        assert sink.blocks("a") == []
        assert sink.blocks("b") == [{"id": "y"}]


@pytest.mark.usefixtures("manager")
class TestConfig:
    """haanim/config/get."""

    async def test_config(self, hass_ws_client: Any, root: Path) -> None:  # noqa: F811
        """Test the answer has the version and the ten options, defaults filled in."""
        client = await hass_ws_client()
        result = (await command(client, 1, "haanim/config/get"))["result"]
        assert result["version"] == VERSION
        assert list(result["options"]) == [
            "automation_path",
            "automation_refresh_interval",
            "max_concurrent_actions",
            "action_queue_size",
            "default_action_timeout",
            "startup_timeout",
            "shutdown_timeout",
            "stop_grace_period",
            "import_allowlist",
            "allow_all_imports",
        ]
        assert result["options"]["max_concurrent_actions"] == 20
        assert result["options"]["import_allowlist"] == []
        assert result["options"]["allow_all_imports"] is False
