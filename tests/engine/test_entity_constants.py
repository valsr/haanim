"""Tests for the constants of device entities and statistics: enums that are their strings, exported to automations."""

from __future__ import annotations

from enum import StrEnum

import pytest

import haanim
from haanim import const

ENUMS = {
    "EntityPlatform": {"sensor", "binary_sensor", "switch", "number", "select", "button", "text"},
    "EntityCommand": {"turn_on", "turn_off", "set_value", "select_option", "press"},
    "StateClass": {"measurement", "total", "total_increasing"},
    "NumberMode": {"auto", "box", "slider"},
    "TextMode": {"text", "password"},
    "Period": {"5minute", "hour", "day", "week", "month"},
    "UnitOfEnergy": {"Wh", "kWh", "MWh"},
    "UnitOfPower": {"W", "kW"},
    "UnitOfTemperature": {"°C", "°F", "K"},
    "UnitOfTime": {"s", "min", "h", "d"},
    "UnitOfVolume": {"L", "m³"},
    "UnitOfPressure": {"hPa", "kPa", "bar"},
    "UnitOfElectricCurrent": {"A"},
    "UnitOfElectricPotential": {"V"},
}


@pytest.mark.parametrize("name", sorted(ENUMS))
def test_enum_values(name: str) -> None:
    """Each enum has exactly the documented values, and its members are their strings."""
    enum = getattr(const, name)
    assert issubclass(enum, StrEnum)
    assert {member.value for member in enum} == ENUMS[name]
    assert all(member == member.value for member in enum)


@pytest.mark.parametrize("name", [*sorted(ENUMS), "PERCENTAGE"])
def test_exported_to_automations(name: str) -> None:
    """Automations import the enums from haanim, as the same objects."""
    assert getattr(haanim, name) is getattr(const, name)
    assert name in haanim.__all__


def test_percentage() -> None:
    assert const.PERCENTAGE == "%"


def test_option_and_field_constants() -> None:
    """The names of declaration options and statistics fields are the strings automations write."""
    assert (const.OPTION_UNIT, const.OPTION_STATE_CLASS, const.OPTION_INITIAL_ATTRIBUTES) == (
        "unit",
        "state_class",
        "initial_attributes",
    )
    assert (const.STAT_START, const.STAT_USAGE, const.STAT_CHANGE) == ("start", "usage", "change")


async def test_enums_work_in_an_automation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A declaration and a statistics call written with the enums."""
    from haanim.testing import AutomationHarness  # pylint: disable=import-outside-toplevel

    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "main.py").write_text(
        "from datetime import datetime, timezone\n"
        "from haanim import Period, StateClass, UnitOfEnergy, action, haa, sensor_entity\n"
        "@sensor_entity(unit=UnitOfEnergy.KILO_WATT_HOUR, state_class=StateClass.TOTAL_INCREASING)\n"
        "class energy:\n    pass\n"
        "@action\nasync def week(event):\n"
        "    return await haa.device.entity(energy).statistics(datetime(2025, 1, 1, tzinfo=timezone.utc), period=Period.DAY)\n"
    )
    async with AutomationHarness(folder) as automation:
        assert automation.entity("energy").options == {"unit": "kWh", "state_class": "total_increasing"}
        assert await automation.call("week") == []
