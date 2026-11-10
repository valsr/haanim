"""Tests for the entities demo: the entities of the automation's device and their hooks."""

from __future__ import annotations

from pathlib import Path

from haanim.testing import AutomationHarness

DEMO = Path(__file__).parents[1] / "demo_entities"


async def test_entities_are_declared() -> None:
    """The device has a sensor, a switch, a number, a select and a button."""
    async with AutomationHarness(DEMO) as automation:
        assert [(e.object_id, e.platform) for e in automation.entities] == [
            ("boost", "switch"),
            ("mode", "select"),
            ("reset", "button"),
            ("target", "number"),
            ("ticks", "sensor"),
        ]
        assert automation.entity("ticks").entity_id == "sensor.haanim_demo_entities_ticks"


async def test_sensor_counts_minutes() -> None:
    """The sensor counts the minutes since the automation started."""
    async with AutomationHarness(DEMO) as automation:
        assert automation.entity("ticks").state == 0
        await automation.advance_time(minutes=3)
        assert automation.entity("ticks").state == 3


async def test_switch_turns_on_and_off() -> None:
    """The switch's hooks confirm the new state and set the message."""
    async with AutomationHarness(DEMO) as automation:
        await automation.command("boost", "turn_on")
        assert automation.entity("boost").state is True
        assert automation.message == "Boost on"
        await automation.command("boost", "turn_off")
        assert automation.entity("boost").state is False


async def test_number_and_select() -> None:
    """The number takes a new target; choosing eco lowers it."""
    async with AutomationHarness(DEMO) as automation:
        await automation.command("target", "set_value", 23)
        assert automation.entity("target").state == 23
        await automation.command("mode", "select_option", "eco")
        assert automation.entity("mode").state == "eco"
        assert automation.entity("target").state == 18


async def test_button_resets_the_count() -> None:
    """Pressing the button sets the sensor back to zero."""
    async with AutomationHarness(DEMO) as automation:
        await automation.advance_time(minutes=2)
        await automation.command("reset", "press")
        assert automation.entity("ticks").state == 0


async def test_stored_state_is_kept() -> None:
    """An entity starts with its stored state, not its initial one."""
    async with AutomationHarness(DEMO, entities={"target": 21.5}) as automation:
        assert automation.entity("target").state == 21.5
