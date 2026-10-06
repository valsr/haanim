"""Tests for logging from automations.

See "Logging" in the design: the logger wrapper, ``print``, and the traceback
of an exception that escapes an action.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.logging_wrapper import AUTOMATION_LOGGER, LoggerWrapper, automation_logger
from tests.engine.test_action_failures import TriggerWorld
from tests.engine.test_lifecycle import World, world  # noqa: F401  pylint: disable=unused-import

LIGHTS = "custom_components.haanim.automation.lights"

SOURCE = """
from haanim import action, haa, logging
import logging as imported

@action
def each_level(event):
    logging.debug("debug %s", 1)
    logging.info("info %s and %s", "a", "b")
    logging.warning("warning %d%%", 50)
    logging.error("error %r", {"k": 1})
    logging.critical("critical")
    logging.fatal("fatal %s", "alias")

@action
def same_object(event):
    return logging is imported

@action
def printing(event):
    print("Task started")
    print("Temperature:", 21.5, "C")
    print("a", "b", "c", sep="-")
    print()
    print("no newline", end="")

@action
def unavailable(event):
    return getattr(logging, event.data["name"])

@action
def task(event):
    logging.info("Task started")
    try:
        raise RuntimeError("no work")
    except Exception as e:
        logging.error("Task failed: %s", e)

@action
def fails(event):
    values = [1, 2, 3]
    return values[10]
"""


def records_of(caplog: pytest.LogCaptureFixture, name: str = LIGHTS) -> list[logging.LogRecord]:
    """Return the records logged under a logger name."""
    return [record for record in caplog.records if record.name == name]


class TestLoggerWrapper:
    """Bullet 1: the wrapper with its level methods and msg, *args formatting."""

    async def test_each_method_and_level(self, world: World, caplog: pytest.LogCaptureFixture) -> None:
        """debug, info, warning, error, critical and fatal log at their level, formatted."""
        automation = await world.started("lights", SOURCE)
        with caplog.at_level(logging.DEBUG, logger=LIGHTS):
            await automation.call_action("each_level")

        assert [(record.levelname, record.getMessage()) for record in records_of(caplog)] == [
            ("DEBUG", "debug 1"),
            ("INFO", "info a and b"),
            ("WARNING", "warning 50%"),
            ("ERROR", "error {'k': 1}"),
            ("CRITICAL", "critical"),
            ("CRITICAL", "fatal alias"),
        ]

    async def test_both_imports_give_the_wrapper(self, world: World) -> None:
        """from haanim import logging and import logging are the same wrapper, not the module."""
        automation = await world.started("lights", SOURCE)
        assert await automation.call_action("same_object") is True
        wrapper = automation.context.get_symbol("logging")
        assert type(wrapper) is LoggerWrapper
        assert wrapper is not logging

    @pytest.mark.parametrize(
        "name",
        [
            "getLogger",
            "basicConfig",
            "Handler",
            "StreamHandler",
            "FileHandler",
            "Formatter",
            "root",
            "disable",
        ],
    )
    async def test_unavailable_members_raise(self, world: World, name: str) -> None:
        """Handlers, formatters and getLogger are not available."""
        automation = await world.started("lights", SOURCE)
        with pytest.raises(AttributeError, match=f"logging.{name} is not available in an automation"):
            await automation.call_action("unavailable", {"name": name})

    async def test_design_example(self, world: World, caplog: pytest.LogCaptureFixture) -> None:
        """The design's example: info, and error with an argument."""
        automation = await world.started("lights", SOURCE)
        with caplog.at_level(logging.INFO, logger=LIGHTS):
            await automation.call_action("task")
        assert [(record.levelname, record.getMessage()) for record in records_of(caplog)] == [
            ("INFO", "Task started"),
            ("ERROR", "Task failed: no work"),
        ]

    def test_methods_take_no_keyword_arguments(self) -> None:
        """The wrapper offers msg, *args and nothing of the logging machinery."""
        wrapper = LoggerWrapper(logging.getLogger("test"))
        with pytest.raises(TypeError):
            wrapper.info("x", exc_info=True)  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            wrapper.error("x", extra={})  # type: ignore[call-arg]


class TestLoggerHierarchy:
    """Each automation has its own logger under the integration's."""

    def test_logger_name(self) -> None:
        """custom_components.haanim.automation.<automation_id>."""
        assert AUTOMATION_LOGGER == "custom_components.haanim.automation"
        assert automation_logger("notifications").name == "custom_components.haanim.automation.notifications"

    async def test_each_automation_has_its_own_logger(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Records carry the ID of the automation that logged them."""
        lights = await world.started("lights", SOURCE)
        heating = await world.started("heating", SOURCE)
        with caplog.at_level(logging.INFO):
            await lights.call_action("task")
            await heating.call_action("task")

        assert len(records_of(caplog, LIGHTS)) == 2
        assert len(records_of(caplog, "custom_components.haanim.automation.heating")) == 2
        assert lights.context.logger.name == LIGHTS

    async def test_child_of_the_integration_logger(self, world: World) -> None:
        """Configuring custom_components.haanim applies to every automation."""
        automation = await world.started("lights", SOURCE)
        parent = logging.getLogger("custom_components.haanim")
        assert automation.context.logger.parent in (parent, logging.getLogger(AUTOMATION_LOGGER))
        chain = []
        logger: Any = automation.context.logger
        while logger is not None:
            chain.append(logger.name)
            logger = logger.parent
        assert "custom_components.haanim" in chain

    async def test_level_of_one_automation(self, world: World, caplog: pytest.LogCaptureFixture) -> None:
        """The design's configuration: one automation at debug, the others not."""
        lights = await world.started("lights", SOURCE)
        heating = await world.started("heating", SOURCE)
        heating_name = "custom_components.haanim.automation.heating"
        logging.getLogger(LIGHTS).setLevel(logging.DEBUG)
        logging.getLogger(heating_name).setLevel(logging.WARNING)
        try:
            with caplog.at_level(logging.DEBUG, logger="custom_components.haanim"):
                await lights.call_action("each_level")
                await heating.call_action("each_level")
        finally:
            logging.getLogger(LIGHTS).setLevel(logging.NOTSET)
            logging.getLogger(heating_name).setLevel(logging.NOTSET)

        assert [record.levelname for record in records_of(caplog)][:2] == ["DEBUG", "INFO"]
        assert [record.levelname for record in records_of(caplog, heating_name)] == [
            "WARNING",
            "ERROR",
            "CRITICAL",
            "CRITICAL",
        ]


class TestPrint:
    """Bullet 2: print writes to the automation's logger at INFO level."""

    async def test_print(
        self, world: World, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Each print is one INFO record; nothing goes to standard output."""
        automation = await world.started("lights", SOURCE)
        capsys.readouterr()
        with caplog.at_level(logging.INFO, logger=LIGHTS):
            await automation.call_action("printing")

        assert [(record.levelname, record.getMessage()) for record in records_of(caplog)] == [
            ("INFO", "Task started"),
            ("INFO", "Temperature: 21.5 C"),
            ("INFO", "a-b-c"),
            ("INFO", ""),
            ("INFO", "no newline"),
        ]
        assert "Task started" not in capsys.readouterr().out

    async def test_print_at_module_level(self, world: World, caplog: pytest.LogCaptureFixture) -> None:
        """print works while main.py runs, before any action."""
        with caplog.at_level(logging.INFO, logger=LIGHTS):
            await world.started("lights", "print('loading', 1 + 1)\n")
        assert [record.getMessage() for record in records_of(caplog)] == ["loading 2"]

    async def test_print_with_percent_signs(self, world: World, caplog: pytest.LogCaptureFixture) -> None:
        """What is printed is not treated as a format string."""
        with caplog.at_level(logging.INFO, logger=LIGHTS):
            await world.started("lights", "print('100% done, %s left')\n")
        assert [record.getMessage() for record in records_of(caplog)] == ["100% done, %s left"]

    async def test_print_goes_to_the_printing_automation(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Two automations printing each log under their own name."""
        with caplog.at_level(logging.INFO):
            await world.started("lights", "print('from lights')\n")
            await world.started("heating", "print('from heating')\n")
        assert [record.getMessage() for record in records_of(caplog)] == ["from lights"]
        assert [
            record.getMessage()
            for record in records_of(caplog, "custom_components.haanim.automation.heating")
        ] == ["from heating"]


class TestEscapingExceptions:
    """Bullet 3: an exception that escapes an action is logged at ERROR with its traceback."""

    async def test_logged_with_traceback_and_raised(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The caller gets the exception; the automation's log gets the traceback."""
        automation = await world.started("lights", SOURCE)
        with caplog.at_level(logging.ERROR, logger=LIGHTS):
            with pytest.raises(IndexError) as exc_info:
                await automation.call_action("fails")

        (record,) = records_of(caplog)
        assert record.levelno == logging.ERROR
        assert "fails raised IndexError" in record.getMessage()
        assert record.exc_info is not None
        assert record.exc_info[1] is exc_info.value
        assert "IndexError: list index out of range" in caplog.text
        assert "Traceback (most recent call last)" in caplog.text

    async def test_handled_exception_is_not_logged(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Only what escapes is logged by the engine."""
        automation = await world.started("lights", SOURCE)
        with caplog.at_level(logging.ERROR, logger=LIGHTS):
            await automation.call_action("task")
        assert [record.getMessage() for record in records_of(caplog)] == ["Task failed: no work"]
        assert all(record.exc_info is None for record in records_of(caplog))

    async def test_trigger_fired_action(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """With no caller, the traceback is logged too, before the failure is recorded."""
        trigger_world = TriggerWorld(tmp_path)
        automation = await trigger_world.started(
            "lights",
            "from haanim import on_state\n\n@on_state(\"sensor.a == 'on'\")\ndef fails():\n    return [][3]\n",
        )
        with caplog.at_level(logging.ERROR, logger=LIGHTS):
            await trigger_world.fire("fails")

        records = records_of(caplog)
        assert records[0].exc_info is not None and isinstance(records[0].exc_info[1], IndexError)
        assert automation.last_error is not None and automation.last_error.error_type == "IndexError"
        await trigger_world.dispatcher.shutdown()

    async def test_successful_action_logs_no_error(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Nothing at ERROR for an action that returns."""
        automation = await world.started("lights", SOURCE)
        with caplog.at_level(logging.ERROR, logger=LIGHTS):
            await automation.call_action("same_object")
        assert records_of(caplog) == []
