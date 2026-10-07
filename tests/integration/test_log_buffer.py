"""Tests for the recent log records of automations and their websocket subscription.

See "GUI" (Log) in the design.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from custom_components.haanim.automation_manager import AutomationManager
from custom_components.haanim.log_buffer import LOGGER_PREFIX, MAX_RECORDS, AutomationLogBuffer
from tests.integration.test_sensor import manager, root, write  # noqa: F401  pylint: disable=unused-import

CHATTY = """
import logging
from haanim import action

@action
def talk(event):
    logging.debug("quiet")
    logging.info("hello %s", "there")
    logging.warning("careful")
    print("printed")

@action
def fail(event):
    raise ValueError("bad value")
"""


@pytest.fixture
def root(tmp_path: Path) -> Path:  # noqa: F811
    """The automations folder: one automation that logs, one that does not."""
    write(tmp_path, "chatty", CHATTY)
    write(tmp_path, "plain", "x = 1\n")
    return tmp_path


@pytest.fixture
def buffer() -> Generator[AutomationLogBuffer, None, None]:
    """A buffer of three records per automation, installed on the automations' logger."""
    buffer = AutomationLogBuffer(max_records=3)
    buffer.install()
    yield buffer
    buffer.remove()


def log(automation_id: str) -> logging.Logger:
    """Return the logger of an automation, set to record everything."""
    logger = logging.getLogger(f"{LOGGER_PREFIX}.{automation_id}")
    logger.setLevel(logging.DEBUG)
    return logger


class TestBuffer:
    """The buffer keeps the latest records of each automation."""

    def test_record(self, buffer: AutomationLogBuffer) -> None:
        """Test a record is kept with its time, level and formatted message."""
        log("a").warning("careful %s", "now")
        (record,) = buffer.records("a")
        assert record["level"] == "WARNING"
        assert record["message"] == "careful now"
        assert record["time"].endswith("+00:00")
        assert "traceback" not in record

    @pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    def test_levels(self, buffer: AutomationLogBuffer, level: str) -> None:
        """Test each level is kept by its name."""
        log("a").log(getattr(logging, level), "x")
        assert buffer.records("a")[-1]["level"] == level

    def test_bound(self, buffer: AutomationLogBuffer) -> None:
        """Test only the latest records are kept, oldest first."""
        for index in range(5):
            log("a").info("record %d", index)
        assert [record["message"] for record in buffer.records("a")] == ["record 2", "record 3", "record 4"]
        assert MAX_RECORDS == 200

    def test_per_automation(self, buffer: AutomationLogBuffer) -> None:
        """Test each automation has its own records; other loggers are ignored."""
        log("a").info("from a")
        log("b").info("from b")
        logging.getLogger(LOGGER_PREFIX).warning("not an automation")
        buffer.emit(logging.LogRecord("elsewhere", logging.INFO, "", 0, "no", None, None))
        assert [record["message"] for record in buffer.records("a")] == ["from a"]
        assert [record["message"] for record in buffer.records("b")] == ["from b"]
        assert buffer.records("nobody") == []

    def test_traceback(self, buffer: AutomationLogBuffer) -> None:
        """Test a record logged with an exception carries its traceback."""
        try:
            raise ValueError("bad value")
        except ValueError:
            log("a").exception("failed")
        record = buffer.records("a")[0]
        assert record["level"] == "ERROR"
        assert "ValueError: bad value" in record["traceback"]

    def test_subscribe(self, buffer: AutomationLogBuffer) -> None:
        """Test a subscriber gets each new record of its automation until it unsubscribes."""
        seen: list[dict[str, Any]] = []
        unsubscribe = buffer.subscribe("a", seen.append)
        log("a").info("one")
        log("b").info("other")
        unsubscribe()
        unsubscribe()
        log("a").info("two")
        assert [change["record"]["message"] for change in seen] == ["one"]

    def test_clear_one(self, buffer: AutomationLogBuffer) -> None:
        """Test clearing an automation's log forgets its records, tells its subscribers, and leaves the others."""
        seen: list[dict[str, Any]] = []
        other: list[dict[str, Any]] = []
        buffer.subscribe("a", seen.append)
        buffer.subscribe("b", other.append)
        log("a").info("one")
        log("b").info("other")
        buffer.clear("a")
        assert buffer.records("a") == []
        assert [record["message"] for record in buffer.records("b")] == ["other"]
        assert seen[-1] == {"records": []}
        assert other == [{"record": buffer.records("b")[0]}]

        log("a").info("two")
        assert [record["message"] for record in buffer.records("a")] == ["two"], "the log goes on"
        assert seen[-1]["record"]["message"] == "two"

    def test_clear_all(self, buffer: AutomationLogBuffer) -> None:
        """Test clearing without an ID forgets every record and tells every subscriber, also of an empty log."""
        seen: dict[str, list[dict[str, Any]]] = {"a": [], "b": [], "quiet": []}
        for name, changes in seen.items():
            buffer.subscribe(name, changes.append)
        log("a").info("one")
        log("b").info("other")
        buffer.clear()
        assert (buffer.records("a"), buffer.records("b")) == ([], [])
        assert [changes[-1] for changes in seen.values()] == [{"records": []}] * 3

    def test_clear_of_an_automation_without_records(self, buffer: AutomationLogBuffer) -> None:
        """Test clearing a log that has nothing does nothing."""
        buffer.clear("nobody")
        assert buffer.records("nobody") == []

    def test_removed_buffer_gets_nothing(self) -> None:
        """Test a removed buffer no longer receives records."""
        buffer = AutomationLogBuffer()
        buffer.install()
        buffer.remove()
        log("a").info("late")
        assert buffer.records("a") == []


@pytest.mark.usefixtures("manager")
class TestSubscription:
    """haanim/logs/subscribe."""

    async def test_recent_records_then_new_ones(
        self, hass_ws_client: Any, manager: AutomationManager  # noqa: F811
    ) -> None:
        """Test the first event has what the automation logged so far, and new records follow one by one."""
        log("chatty").setLevel(logging.INFO)
        await manager.async_call_action("chatty", "talk")
        client = await hass_ws_client()
        await client.send_json({"id": 1, "type": "haanim/logs/subscribe", "automation_id": "chatty"})
        assert (await client.receive_json())["success"] is True
        first = await client.receive_json()
        assert first["type"] == "event"
        assert [(record["level"], record["message"]) for record in first["event"]["records"]] == [
            ("INFO", "hello there"),
            ("WARNING", "careful"),
            ("INFO", "printed"),
        ]

        await manager.async_call_action("chatty", "talk")
        event = await client.receive_json()
        assert event["type"] == "event"
        assert event["event"]["record"]["message"] == "hello there"

    async def test_failure_with_traceback(
        self, hass_ws_client: Any, manager: AutomationManager
    ) -> None:  # noqa: F811
        """Test an action that raises leaves an error record with its traceback."""
        with pytest.raises(ValueError):
            await manager.async_call_action("chatty", "fail")
        client = await hass_ws_client()
        await client.send_json({"id": 1, "type": "haanim/logs/subscribe", "automation_id": "chatty"})
        assert (await client.receive_json())["success"] is True
        records = (await client.receive_json())["event"]["records"]
        assert records[-1]["level"] == "ERROR"
        assert "ValueError" in records[-1]["traceback"]

    async def test_other_automation_has_its_own(
        self, hass_ws_client: Any, manager: AutomationManager
    ) -> None:  # noqa: F811
        """Test the records of one automation are not shown for another."""
        await manager.async_call_action("chatty", "talk")
        client = await hass_ws_client()
        await client.send_json({"id": 1, "type": "haanim/logs/subscribe", "automation_id": "plain"})
        assert (await client.receive_json())["result"] is None
        assert (await client.receive_json())["event"] == {"records": []}

    async def test_unknown_automation(self, hass_ws_client: Any) -> None:
        """Test an unknown automation is answered with not_found."""
        client = await hass_ws_client()
        await client.send_json({"id": 1, "type": "haanim/logs/subscribe", "automation_id": "nobody"})
        assert (await client.receive_json())["error"]["code"] == "not_found"
