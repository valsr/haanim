"""Tests for commands from Home Assistant: they run the hooks of declared entities."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from haanim.testing import AutomationHarness

MAIN = """
from haanim import ActionMode, EntityCommandEvent, haa, number_entity, switch_entity

@switch_entity(initial=False)
class boost:
    async def turn_on(self, entity, event):
        haa.set_variable("event", [event.command, event.entity_id, event.source, event.value])
        entity.set_state(True)

@switch_entity(initial=False)
class half:
    def turn_on(self, entity, event):
        entity.set_state(True)

@switch_entity
class broken:
    def turn_on(self, entity, event):
        raise RuntimeError("no heat")

    def turn_off(self, entity, event):
        entity.set_state("sideways")

@number_entity(min=0, max=10)
class level:
    def set_value(self, entity, event):
        entity.set_state(event.value)

@switch_entity(action_mode=ActionMode.DROP)
class slow:
    async def turn_on(self, entity, event):
        await haa.sleep(10)
        entity.set_state(True)
"""


def write(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "main.py").write_text(MAIN)
    return folder


async def test_turn_on_runs_hook_and_hook_confirms(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "climate")) as h:
        await h.command("boost", "turn_on")
        assert h.entity("boost").state is True
        assert h.variables["event"] == ["turn_on", "switch.haanim_climate_boost", "entity", None]


async def test_missing_hook_warns_and_is_noop(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    async with AutomationHarness(write(tmp_path / "climate")) as h:
        await h.command("half", "turn_on")
        with caplog.at_level(logging.WARNING):
            await h.command("half", "turn_off")
        assert h.entity("half").state is True
        assert '"half" has no turn_off hook; command ignored' in caplog.text
        assert h.last_error is None


async def test_stopped_automation_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    async with AutomationHarness(write(tmp_path / "climate")) as h:
        await h.stop()
        with caplog.at_level(logging.WARNING):
            await h.command("boost", "turn_on")
        assert h.entity("boost").state is False
        assert '"boost" ignored turn_on: automation is not running' in caplog.text


async def test_hook_exception_is_recorded_not_raised(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "climate"), expect_failures=True) as h:
        await h.command("broken", "turn_on")
        assert h.last_error is not None
        assert (h.last_error.action, h.last_error.error_type) == ("broken.turn_on", "RuntimeError")
        assert h.state == "on"


async def test_hook_invalid_set_state_is_failure(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "climate"), expect_failures=True) as h:
        await h.command("broken", "turn_off")
        assert h.last_error is not None
        assert (h.last_error.action, h.last_error.error_type) == ("broken.turn_off", "ValueError")
        assert h.entity("broken").state is None


async def test_number_set_value_passes_value(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "climate")) as h:
        await h.command("level", "set_value", 7)
        assert h.entity("level").state == 7.0


async def test_drop_mode_drops_concurrent_command(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "climate")) as h:
        first = asyncio.ensure_future(h.command("slow", "turn_on"))
        await h.clock.settle()
        await h.command("slow", "turn_on")
        assert h.last_error is not None and h.last_error.error_type == "ActionDroppedError"
        await h.advance_time(seconds=10)
        await first
        assert h.entity("slow").state is True


async def test_unknown_entity_or_command_is_a_caller_error(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "climate")) as h:
        with pytest.raises(KeyError):
            await h.command("nope", "turn_on")
        with pytest.raises(KeyError):
            await h.command("boost", "press")
