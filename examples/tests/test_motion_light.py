"""Tests for the motion light example."""

from __future__ import annotations

from pathlib import Path

import pytest

from haanim.testing import AutomationHarness

MOTION_LIGHT = Path(__file__).parents[1] / "motion_light"
MOTION = "binary_sensor.hallway_motion"
NIGHT = "2025-01-06 22:00:00"
DAY = "2025-01-06 12:00:00"


async def test_motion_at_night_turns_the_light_on() -> None:
    """Motion after sunset turns the hallway light on."""
    async with AutomationHarness(MOTION_LIGHT, now=NIGHT, states={MOTION: "off"}) as automation:
        automation.set_state(MOTION, "on")
        await automation.advance_time(seconds=1)

        (call,) = automation.service_calls("light.turn_on")
        assert call.data == {"entity_id": "light.hallway", "brightness": 120}
        assert automation.service_calls("light.turn_off") == []
        assert automation.message == "Motion: light on"


async def test_light_goes_off_five_minutes_after_the_motion_ended() -> None:
    """The light stays on while the sensor is on and for five minutes after."""
    async with AutomationHarness(MOTION_LIGHT, now=NIGHT, states={MOTION: "off"}) as automation:
        automation.set_state(MOTION, "on")
        await automation.advance_time(minutes=20)
        assert automation.service_calls("light.turn_off") == []

        automation.set_state(MOTION, "off")
        await automation.advance_time(minutes=4, seconds=59)
        assert automation.service_calls("light.turn_off") == []

        await automation.advance_time(seconds=2)
        (call,) = automation.service_calls("light.turn_off")
        assert call.data == {"entity_id": "light.hallway"}
        assert automation.message == "No motion: light off"
        await automation.wait_idle()


async def test_new_motion_keeps_the_light_on() -> None:
    """Motion during the five minutes starts the wait again."""
    async with AutomationHarness(MOTION_LIGHT, now=NIGHT, states={MOTION: "off"}) as automation:
        automation.set_state(MOTION, "on")
        await automation.advance_time(seconds=10)
        automation.set_state(MOTION, "off")
        await automation.advance_time(minutes=4)

        automation.set_state(MOTION, "on")
        await automation.advance_time(seconds=10)
        automation.set_state(MOTION, "off")
        await automation.advance_time(minutes=4)
        assert automation.service_calls("light.turn_off") == []

        await automation.advance_time(minutes=2)
        assert len(automation.service_calls("light.turn_off")) == 1


async def test_nothing_happens_by_day() -> None:
    """The time constraint keeps the light off between sunrise and sunset."""
    async with AutomationHarness(MOTION_LIGHT, now=DAY, states={MOTION: "off"}) as automation:
        automation.set_state(MOTION, "on")
        await automation.advance_time(minutes=1)
        assert automation.service_calls() == []


async def test_the_delay_can_be_changed() -> None:
    """`set_minutes` stores the delay and the light follows it."""
    async with AutomationHarness(MOTION_LIGHT, now=NIGHT, states={MOTION: "off"}) as automation:
        assert await automation.call("set_minutes", minutes=1) == 1.0
        assert automation.get_variable("minutes") == 1.0

        automation.set_state(MOTION, "on")
        await automation.advance_time(seconds=5)
        automation.set_state(MOTION, "off")
        await automation.advance_time(seconds=61)
        assert len(automation.service_calls("light.turn_off")) == 1


async def test_an_invalid_delay_is_refused() -> None:
    """A delay of zero or less raises and is not stored."""
    async with AutomationHarness(MOTION_LIGHT) as automation:
        with pytest.raises(ValueError, match="minutes must be more than 0"):
            await automation.call("set_minutes", minutes=0)
        assert automation.get_variable("minutes") is None
