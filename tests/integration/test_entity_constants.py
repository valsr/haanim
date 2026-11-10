"""Tests that the engine's mirrored constants have Home Assistant's values: the engine cannot import them."""

from __future__ import annotations

import homeassistant.const as ha
import pytest
from homeassistant.components.number import NumberMode
from homeassistant.components.sensor import SensorStateClass
from homeassistant.components.text import TextMode

from haanim import const

MIRRORED = [
    "UnitOfEnergy",
    "UnitOfPower",
    "UnitOfTemperature",
    "UnitOfTime",
    "UnitOfVolume",
    "UnitOfPressure",
    "UnitOfElectricCurrent",
    "UnitOfElectricPotential",
]


@pytest.mark.parametrize("name", MIRRORED)
def test_units_are_home_assistants(name: str) -> None:
    """Each mirrored unit has the name and value Home Assistant gives it."""
    theirs = getattr(ha, name)
    for member in getattr(const, name):
        assert theirs[member.name] == member.value, f"{name}.{member.name}"


def test_percentage_is_home_assistants() -> None:
    assert const.PERCENTAGE == ha.PERCENTAGE


@pytest.mark.parametrize(
    "ours, theirs",
    [
        (const.EntityPlatform, ha.Platform),
        (const.StateClass, SensorStateClass),
        (const.NumberMode, NumberMode),
        (const.TextMode, TextMode),
    ],
)
def test_enums_are_home_assistants(ours: type, theirs: type) -> None:
    """Every member of the engine's enum is a member of Home Assistant's, with the same name."""
    for member in ours:  # type: ignore[attr-defined]
        assert theirs[member.name] == member.value, f"{ours.__name__}.{member.name}"
