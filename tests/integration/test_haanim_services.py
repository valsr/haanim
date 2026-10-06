"""Tests for the HAAnim services.

See "Home Assistant Services" in the design.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import voluptuous as vol
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.haanim.automation_manager import AutomationManager
from custom_components.haanim.const import DOMAIN
from custom_components.haanim.ha.services import SERVICES, ServiceManager
from tests.integration.test_sensor import manager, root, write  # noqa: F401  pylint: disable=unused-import

COMPONENT = Path(__file__).parents[2] / "custom_components" / "haanim"

DESIGN_TABLE: dict[str, list[str]] = {
    "run_action": ["automation_id", "action", "data"],
    "enable": ["automation_id"],
    "disable": ["automation_id"],
    "start": ["automation_id"],
    "stop": ["automation_id"],
    "restart": ["automation_id"],
    "reload": ["automation_id"],
    "list_automations": [],
    "list_actions": ["automation_id"],
    "clear_log": ["automation_id"],
    "set_log_level": ["automation_id", "level"],
}

ECHO = """
from haanim import action

@action(aliases=["repeat"], description="Give back what it was called with.")
def echo(event):
    return {"source": event.source, "data": event.data}

@action
def fail(event):
    raise ValueError("bad value")
"""


@pytest.fixture
def root(tmp_path: Path) -> Path:  # noqa: F811
    """The automations folder: one automation with actions, one plain, one broken."""
    write(tmp_path, "echo", ECHO, '{"name": "Echo"}')
    write(tmp_path, "plain", "x = 1\n")
    write(tmp_path, "broken", "def broken(:\n")
    return tmp_path


async def call(hass: HomeAssistant, service: str, response: bool = False, **data: Any) -> Any:
    """Call a HAAnim service and wait for it."""
    return await hass.services.async_call(DOMAIN, service, data, blocking=True, return_response=response)


def state(hass: HomeAssistant, automation_id: str) -> str:
    """Return the state of an automation's entity."""
    return hass.states.get(f"sensor.haanim_{automation_id}").state


class TestTable:
    """The services, their fields and their texts match the design's table."""

    def test_the_services(self) -> None:
        """Test the registered services are exactly the table's."""
        assert sorted(SERVICES) == sorted(DESIGN_TABLE)

    async def test_registered(self, hass: HomeAssistant, manager: AutomationManager) -> None:  # noqa: F811
        """Test every service of the table is registered, and none of the old ones."""
        assert sorted(hass.services.async_services()[DOMAIN]) == sorted(DESIGN_TABLE)

    def test_services_yaml(self) -> None:
        """Test services.yaml lists the same services with the same fields."""
        described = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))
        assert {
            name: list((body or {}).get("fields", {})) for name, body in described.items()
        } == DESIGN_TABLE
        assert described["reload"]["fields"]["automation_id"]["required"] is False
        assert described["clear_log"]["fields"]["automation_id"]["required"] is False
        assert described["set_log_level"]["fields"]["level"]["required"] is True
        assert described["run_action"]["fields"]["data"]["required"] is False
        assert described["run_action"]["fields"]["action"]["required"] is True

    @pytest.mark.parametrize("filename", ["strings.json", "translations/en.json"])
    def test_strings(self, filename: str) -> None:
        """Test every service and field has a name and a description."""
        services = json.loads((COMPONENT / filename).read_text(encoding="utf-8"))["services"]
        assert {name: list(body.get("fields", {})) for name, body in services.items()} == DESIGN_TABLE
        for body in services.values():
            assert body["name"] and body["description"]
            for field in body.get("fields", {}).values():
                assert field["name"] and field["description"]

    async def test_teardown_removes_them(self, hass: HomeAssistant) -> None:
        """Test the services are gone after teardown."""
        services = ServiceManager(hass)
        await services.async_setup()
        assert hass.services.has_service(DOMAIN, "run_action")
        await services.async_teardown()
        assert DOMAIN not in hass.services.async_services()


@pytest.mark.usefixtures("manager")
class TestRunAction:
    """haanim.run_action runs an action as a manual call and returns its result."""

    async def test_result_as_response(self, hass: HomeAssistant) -> None:
        """Test the action's result is the response data; the call is manual and gets the data."""
        response = await call(
            hass, "run_action", True, automation_id="echo", action="echo", data={"room": "hall"}
        )
        assert response == {"result": {"source": "manual", "data": {"room": "hall"}}}

    async def test_without_data_and_by_alias(self, hass: HomeAssistant) -> None:
        """Test data is optional and an alias names the action."""
        response = await call(hass, "run_action", True, automation_id="echo", action="repeat")
        assert response == {"result": {"source": "manual", "data": {}}}

    async def test_without_response(self, hass: HomeAssistant) -> None:
        """Test the service can be called without asking for the response."""
        assert await call(hass, "run_action", automation_id="echo", action="echo") is None

    @pytest.mark.parametrize(
        ("data", "message"),
        [
            ({"automation_id": "echo", "action": "missing"}, "ActionNotFoundError"),
            ({"automation_id": "nobody", "action": "echo"}, "NonExistingAutomationError"),
        ],
    )
    async def test_haanim_error(self, hass: HomeAssistant, data: dict[str, Any], message: str) -> None:
        """Test a HAAnim error becomes a service error carrying its type and message."""
        with pytest.raises(HomeAssistantError, match=message):
            await call(hass, "run_action", True, **data)

    async def test_error_raised_by_the_action(self, hass: HomeAssistant) -> None:
        """Test what the action raises reaches the caller of the service."""
        with pytest.raises(ValueError, match="bad value"):
            await call(hass, "run_action", True, automation_id="echo", action="fail")

    @pytest.mark.parametrize(
        "data",
        [
            {},
            {"automation_id": "echo"},
            {"action": "echo"},
            {"automation_id": "echo", "action": "echo", "data": 5},
        ],
    )
    async def test_schema(self, hass: HomeAssistant, data: dict[str, Any]) -> None:
        """Test automation_id and action are required and data is a mapping."""
        with pytest.raises(vol.Invalid):
            await call(hass, "run_action", **data)


@pytest.mark.usefixtures("manager")
class TestControl:
    """enable, disable, start, stop and restart."""

    async def test_stop_and_start(self, hass: HomeAssistant) -> None:
        """Test stop turns the automation off and start turns it on."""
        await call(hass, "stop", automation_id="echo")
        await hass.async_block_till_done()
        assert state(hass, "echo") == "off"
        await call(hass, "start", automation_id="echo")
        await hass.async_block_till_done()
        assert state(hass, "echo") == "on"

    async def test_disable_and_enable(
        self, hass: HomeAssistant, manager: AutomationManager
    ) -> None:  # noqa: F811
        """Test disable stops and disables; enable enables and starts."""
        await call(hass, "disable", automation_id="echo")
        await hass.async_block_till_done()
        assert state(hass, "echo") == "off"
        assert manager.is_automation_enabled("echo") is False
        await call(hass, "enable", automation_id="echo")
        await hass.async_block_till_done()
        assert state(hass, "echo") == "on"
        assert manager.is_automation_enabled("echo") is True

    async def test_restart(self, hass: HomeAssistant, manager: AutomationManager) -> None:  # noqa: F811
        """Test restart starts the automation again."""
        before = manager._automation("echo").context  # pylint: disable=protected-access
        calls: list[str] = []
        original = manager.async_restart_automation

        async def restart(automation_id: str) -> None:
            calls.append(automation_id)
            await original(automation_id)

        manager.async_restart_automation = restart  # type: ignore[method-assign]
        await call(hass, "restart", automation_id="echo")
        assert calls == ["echo"]
        assert state(hass, "echo") == "on"
        assert manager._automation("echo").context is before  # pylint: disable=protected-access

    @pytest.mark.parametrize(
        ("service", "automation_id", "message"),
        [
            ("start", "echo", "AutomationAlreadyRunningError"),
            ("stop", "nobody", "NonExistingAutomationError"),
            ("enable", "nobody", "NonExistingAutomationError"),
            ("disable", "nobody", "NonExistingAutomationError"),
            ("restart", "nobody", "NonExistingAutomationError"),
        ],
    )
    async def test_failure(self, hass: HomeAssistant, service: str, automation_id: str, message: str) -> None:
        """Test a failing operation raises a service error with the HAAnim error type."""
        with pytest.raises(HomeAssistantError, match=message):
            await call(hass, service, automation_id=automation_id)

    async def test_start_of_a_disabled_automation(self, hass: HomeAssistant) -> None:
        """Test start does not start a disabled automation."""
        await call(hass, "disable", automation_id="echo")
        with pytest.raises(HomeAssistantError, match="AutomationDisabledError"):
            await call(hass, "start", automation_id="echo")

    @pytest.mark.parametrize("service", ["enable", "disable", "start", "stop", "restart", "list_actions"])
    async def test_automation_id_is_required(self, hass: HomeAssistant, service: str) -> None:
        """Test the services that act on one automation need its ID."""
        with pytest.raises(vol.Invalid):
            await call(hass, service, service == "list_actions")


@pytest.mark.usefixtures("manager")
class TestReload:
    """haanim.reload rescans now and reloads one automation, or all."""

    async def test_reload_one(self, hass: HomeAssistant, root: Path) -> None:  # noqa: F811
        """Test a fixed automation is loaded again by its ID."""
        write(root, "broken", "x = 1\n")
        await call(hass, "reload", automation_id="broken")
        await hass.async_block_till_done()
        assert state(hass, "broken") == "on"

    async def test_reload_one_that_fails(self, hass: HomeAssistant, root: Path) -> None:  # noqa: F811
        """Test reloading an automation that cannot be loaded raises and leaves it in error."""
        write(root, "plain", "def broken(:\n")
        with pytest.raises(HomeAssistantError, match="main.py:1"):
            await call(hass, "reload", automation_id="plain")
        await hass.async_block_till_done()
        assert state(hass, "plain") == "error"

    async def test_reload_unknown(self, hass: HomeAssistant) -> None:
        """Test reloading an unknown ID raises."""
        with pytest.raises(HomeAssistantError, match="NonExistingAutomationError"):
            await call(hass, "reload", automation_id="nobody")

    async def test_reload_all_rescans(self, hass: HomeAssistant, root: Path) -> None:  # noqa: F811
        """Test without an ID new folders are found, removed ones go, the rest is reloaded."""
        write(root, "added", "x = 1\n")
        write(root, "broken", "x = 1\n")
        shutil.rmtree(root / "plain")

        await call(hass, "reload")
        await hass.async_block_till_done()

        assert state(hass, "added") == "on"
        assert state(hass, "broken") == "on"
        assert state(hass, "echo") == "on"
        assert hass.states.get("sensor.haanim_plain") is None


@pytest.mark.usefixtures("manager")
class TestLists:
    """list_automations and list_actions return response data."""

    async def test_list_automations(self, hass: HomeAssistant) -> None:
        """Test ID, name, state and enabled flag of every automation, sorted by ID."""
        await call(hass, "disable", automation_id="plain")
        response = await call(hass, "list_automations", True)
        assert response == {
            "automations": [
                {"id": "broken", "name": "broken", "state": "error", "enabled": True},
                {"id": "echo", "name": "Echo", "state": "on", "enabled": True},
                {"id": "plain", "name": "plain", "state": "off", "enabled": False},
            ]
        }

    async def test_list_actions(self, hass: HomeAssistant) -> None:
        """Test name, aliases and description of each action."""
        response = await call(hass, "list_actions", True, automation_id="echo")
        assert response == {
            "actions": [
                {"name": "echo", "aliases": ["repeat"], "description": "Give back what it was called with."},
                {"name": "fail", "aliases": [], "description": ""},
            ]
        }

    async def test_list_actions_of_an_automation_without_any(self, hass: HomeAssistant) -> None:
        """Test an automation without actions, or one that is not running, lists none."""
        assert await call(hass, "list_actions", True, automation_id="plain") == {"actions": []}
        assert await call(hass, "list_actions", True, automation_id="broken") == {"actions": []}

    async def test_list_actions_unknown(self, hass: HomeAssistant) -> None:
        """Test an unknown automation raises."""
        with pytest.raises(HomeAssistantError, match="NonExistingAutomationError"):
            await call(hass, "list_actions", True, automation_id="nobody")

    @pytest.mark.parametrize("service", ["list_automations", "list_actions"])
    async def test_response_is_required(self, hass: HomeAssistant, service: str) -> None:
        """Test the list services only work when the response is asked for."""
        with pytest.raises(ServiceValidationError):
            (
                await call(hass, service, automation_id="echo")
                if service == "list_actions"
                else await call(hass, service)
            )


class TestNotSetUp:
    """The services without a set up integration."""

    async def test_no_manager(self, hass: HomeAssistant) -> None:
        """Test a service raises when HAAnim is not set up."""
        services = ServiceManager(hass)
        await services.async_setup()
        with pytest.raises(HomeAssistantError, match="HAAnim is not set up"):
            await call(hass, "list_automations", True)
        await services.async_teardown()
