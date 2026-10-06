"""Tests for the log level of an automation and for clearing its log.

See "Logging" and "Home Assistant Services" in the design.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.haanim.automation_manager import AutomationManager
from custom_components.haanim.const import DOMAIN
from custom_components.haanim.ha.services import ServiceManager
from custom_components.haanim.log_buffer import LOGGER_PREFIX, AutomationLogBuffer, entry_item
from custom_components.haanim.log_levels import DEFAULT_LEVEL, LOG_LEVELS, AutomationLogLevels
from haanim.testing import FakeStorage
from tests.integration.test_log_buffer import CHATTY
from tests.integration.test_sensor import manager, root, write  # noqa: F401  pylint: disable=unused-import


@pytest.fixture
def root(tmp_path: Path) -> Path:  # noqa: F811
    """The automations folder: one automation that logs, one that does not."""
    write(tmp_path, "chatty", CHATTY)
    write(tmp_path, "plain", "x = 1\n")
    return tmp_path


def logger(automation_id: str) -> logging.Logger:
    """Return the logger of an automation."""
    return logging.getLogger(f"{LOGGER_PREFIX}.{automation_id}")


@pytest.fixture(autouse=True)
def clean_loggers() -> Generator[None, None, None]:
    """Leave the loggers the tests touch as they were."""
    names = ("chatty", "plain", "a", "b")
    before = {name: logger(name).level for name in names}
    parent = logging.getLogger(LOGGER_PREFIX).level
    yield
    for name, level in before.items():
        logger(name).setLevel(level)
    logging.getLogger(LOGGER_PREFIX).setLevel(parent)


async def call(hass: HomeAssistant, service: str, **data: Any) -> Any:
    """Call a HAAnim service and wait for it."""
    return await hass.services.async_call(DOMAIN, service, data, blocking=True)


class TestLevels:
    """The level set for an automation is on its logger and is kept."""

    def test_the_levels(self) -> None:
        """Test the levels are the five of Python's logging, and default stands for none."""
        assert LOG_LEVELS == ("debug", "info", "warning", "error", "critical")
        assert DEFAULT_LEVEL == "default"

    @pytest.mark.parametrize("level", LOG_LEVELS)
    async def test_set(self, level: str) -> None:
        """Test a level is put on the automation's logger and reported."""
        levels = AutomationLogLevels(FakeStorage())
        await levels.async_set("a", level)
        assert logger("a").level == getattr(logging, level.upper())
        assert (levels.level("a"), levels.effective("a")) == (level, level)
        assert levels.level("b") is None

    @pytest.mark.parametrize("nothing", [None, DEFAULT_LEVEL])
    async def test_default_takes_the_level_away(self, nothing: str | None) -> None:
        """Test without a level of its own the logger follows the one above it."""
        logging.getLogger(LOGGER_PREFIX).setLevel(logging.WARNING)
        levels = AutomationLogLevels(FakeStorage())
        await levels.async_set("a", "debug")
        await levels.async_set("a", nothing)
        assert logger("a").level == logging.NOTSET
        assert (levels.level("a"), levels.effective("a")) == (None, "warning")
        await levels.async_set("a", nothing)
        assert levels.level("a") is None

    @pytest.mark.parametrize("level", ["loud", "DEBUG", "", 10])
    async def test_invalid_level(self, level: Any) -> None:
        """Test a level that is none raises and changes nothing."""
        storage = FakeStorage()
        levels = AutomationLogLevels(storage)
        await levels.async_set("a", "error")
        with pytest.raises(ValueError, match="Invalid log level"):
            await levels.async_set("a", level)
        assert levels.level("a") == "error"
        assert storage.saves == ["log_levels"]

    async def test_kept_across_a_restart(self) -> None:
        """Test the levels are stored, and put on the loggers again when they are loaded."""
        storage = FakeStorage()
        levels = AutomationLogLevels(storage)
        await levels.async_set("a", "debug")
        await levels.async_set("b", "error")
        await levels.async_set("b", DEFAULT_LEVEL)
        levels.remove()
        assert logger("a").level == logging.NOTSET, "unloading takes HAAnim's levels off the loggers"

        again = AutomationLogLevels(storage)
        assert again.level("a") is None
        await again.async_load()
        assert (again.level("a"), again.level("b")) == ("debug", None)
        assert logger("a").level == logging.DEBUG

    @pytest.mark.parametrize("stored", [None, [], "debug", {"a": "loud", "b": 5}])
    async def test_stored_nonsense_is_ignored(self, stored: Any) -> None:
        """Test a stored document that is not levels by automation sets no level."""
        logger("a").setLevel(logging.NOTSET)
        storage = FakeStorage()
        if stored is not None:
            await storage.save("log_levels", stored)
        levels = AutomationLogLevels(storage)
        await levels.async_load()
        assert (levels.level("a"), levels.level("b")) == (None, None)
        assert logger("a").level == logging.NOTSET


@pytest.mark.usefixtures("manager")
class TestSetLogLevelService:
    """haanim.set_log_level."""

    async def test_level_decides_what_is_logged(
        self, hass: HomeAssistant, manager: AutomationManager  # noqa: F811
    ) -> None:
        """Test debug records are kept once the level is debug, and only errors once it is error."""
        buffer = entry_item(hass, "log_buffer", AutomationLogBuffer)
        assert buffer is not None

        await call(hass, "set_log_level", automation_id="chatty", level="debug")
        await manager.async_call_action("chatty", "talk")
        assert [record["message"] for record in buffer.records("chatty")][-4:] == [
            "quiet",
            "hello there",
            "careful",
            "printed",
        ]

        buffer.clear("chatty")
        await call(hass, "set_log_level", automation_id="chatty", level="error")
        await manager.async_call_action("chatty", "talk")
        assert buffer.records("chatty") == []
        with pytest.raises(ValueError):
            await manager.async_call_action("chatty", "fail")
        assert [record["level"] for record in buffer.records("chatty")] == ["ERROR"]

    async def test_the_detail_has_the_level(self, hass: HomeAssistant, hass_ws_client: Any) -> None:
        """Test the page of the automation is told the level set and the level in effect."""
        client = await hass_ws_client()

        async def detail(message_id: int) -> dict[str, Any]:
            await client.send_json(
                {"id": message_id, "type": "haanim/automations/get", "automation_id": "chatty"}
            )
            result: dict[str, Any] = (await client.receive_json())["result"]
            return result

        logging.getLogger(LOGGER_PREFIX).setLevel(logging.INFO)
        before = await detail(1)
        assert (before["log_level"], before["effective_log_level"]) == (None, "info")
        await call(hass, "set_log_level", automation_id="chatty", level="warning")
        after = await detail(2)
        assert (after["log_level"], after["effective_log_level"]) == ("warning", "warning")
        await call(hass, "set_log_level", automation_id="chatty", level="default")
        assert (await detail(3))["log_level"] is None

    async def test_level_is_stored(
        self, hass: HomeAssistant, manager: AutomationManager
    ) -> None:  # noqa: F811
        """Test the level is kept in HAAnim's storage, by automation."""
        await call(hass, "set_log_level", automation_id="chatty", level="debug")
        assert await manager.host.storage.load("log_levels") == {"chatty": "debug"}

    async def test_unknown_automation(self, hass: HomeAssistant) -> None:
        """Test an automation that does not exist is refused."""
        with pytest.raises(HomeAssistantError, match="Automation 'nobody' does not exist"):
            await call(hass, "set_log_level", automation_id="nobody", level="debug")

    @pytest.mark.parametrize(
        "data", [{"automation_id": "chatty"}, {"automation_id": "chatty", "level": "loud"}]
    )
    async def test_invalid_call(self, hass: HomeAssistant, data: dict[str, Any]) -> None:
        """Test a call without a level, or with one that is none, is refused."""
        with pytest.raises(vol.Invalid):
            await call(hass, "set_log_level", **data)


@pytest.mark.usefixtures("manager")
class TestClearLogService:
    """haanim.clear_log."""

    async def test_clear_one(
        self, hass: HomeAssistant, hass_ws_client: Any, manager: AutomationManager  # noqa: F811
    ) -> None:
        """Test the log of an automation is emptied, and whoever follows it is sent the empty log."""
        logger("chatty").setLevel(logging.INFO)
        await manager.async_call_action("chatty", "talk")
        client = await hass_ws_client()
        await client.send_json({"id": 1, "type": "haanim/logs/subscribe", "automation_id": "chatty"})
        assert (await client.receive_json())["success"] is True
        assert len((await client.receive_json())["event"]["records"]) == 3

        await call(hass, "clear_log", automation_id="chatty")
        assert (await client.receive_json())["event"] == {"records": []}

        await manager.async_call_action("chatty", "talk")
        assert (await client.receive_json())["event"]["record"]["message"] == "hello there"

    async def test_clear_all(self, hass: HomeAssistant, manager: AutomationManager) -> None:  # noqa: F811
        """Test without an ID the logs of all automations are emptied."""
        buffer = entry_item(hass, "log_buffer", AutomationLogBuffer)
        assert buffer is not None
        logger("chatty").setLevel(logging.INFO)
        await manager.async_call_action("chatty", "talk")
        assert buffer.records("chatty")
        await call(hass, "clear_log")
        assert buffer.records("chatty") == []

    async def test_unknown_automation(self, hass: HomeAssistant) -> None:
        """Test an automation that does not exist is refused."""
        with pytest.raises(HomeAssistantError, match="Automation 'nobody' does not exist"):
            await call(hass, "clear_log", automation_id="nobody")


class TestWithoutIntegration:
    """The services while HAAnim's data is not there."""

    async def test_not_set_up(self, hass: HomeAssistant) -> None:
        """Test the services say that HAAnim is not set up."""
        services = ServiceManager(hass)
        await services.async_setup()
        with pytest.raises(HomeAssistantError, match="HAAnim is not set up"):
            await call(hass, "clear_log")
        with pytest.raises(HomeAssistantError, match="HAAnim is not set up"):
            await call(hass, "set_log_level", automation_id="chatty", level="debug")
        await services.async_teardown()
        assert entry_item(hass, "log_buffer", AutomationLogBuffer) is None
