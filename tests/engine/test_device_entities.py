"""Tests for entity declarations: the decorators that declare an automation's device entities."""

from __future__ import annotations

from typing import Any

import pytest

from haanim.const import ActionMode
from haanim.engine.device_entities import (
    PLATFORMS,
    binary_sensor_entity,
    button_entity,
    get_declaration,
    number_entity,
    select_entity,
    sensor_entity,
    switch_entity,
    text_entity,
)
from haanim.engine.errors import AutomationDefinitionError


def test_class_name_is_object_id_and_name() -> None:
    @sensor_entity(unit="°C", device_class="temperature")
    class average_temp:  # pylint: disable=invalid-name
        pass

    declaration = get_declaration(average_temp)
    assert declaration is not None
    assert (declaration.object_id, declaration.platform, declaration.name) == (
        "average_temp",
        "sensor",
        "average temp",
    )
    assert declaration.options == {"unit": "°C", "device_class": "temperature"}
    assert declaration.cls is average_temp


def test_id_override_is_slugged() -> None:
    @switch_entity(id="Boost Mode")
    class Anything:
        pass

    declaration = get_declaration(Anything)
    assert declaration is not None
    assert declaration.object_id == "boost_mode"


def test_bare_decorator() -> None:
    @binary_sensor_entity
    class door:  # pylint: disable=invalid-name
        pass

    declaration = get_declaration(door)
    assert declaration is not None
    assert declaration.platform == "binary_sensor"


def test_default_action_mode_is_drop() -> None:
    @button_entity
    class ring:  # pylint: disable=invalid-name
        pass

    declaration = get_declaration(ring)
    assert declaration is not None
    assert declaration.action_mode is ActionMode.DROP


def test_common_options() -> None:
    @select_entity(
        options=["a", "b"],
        name="Mode",
        icon="mdi:tune",
        attributes={"source": "x"},
        initial="a",
        action_mode=ActionMode.QUEUE,
    )
    class mode:  # pylint: disable=invalid-name
        pass

    declaration = get_declaration(mode)
    assert declaration is not None
    assert (declaration.name, declaration.icon, declaration.initial) == ("Mode", "mdi:tune", "a")
    assert declaration.attributes == {"source": "x"}
    assert declaration.action_mode is ActionMode.QUEUE
    assert declaration.as_stored() == {
        "name": "Mode",
        "icon": "mdi:tune",
        "initial": "a",
        "initial_attributes": {"source": "x"},
        "options": ["a", "b"],
    }


def test_hooks_per_platform() -> None:
    assert PLATFORMS["switch"].hooks == ("turn_on", "turn_off")
    assert PLATFORMS["number"].hooks == ("set_value",)
    assert PLATFORMS["select"].hooks == ("select_option",)
    assert PLATFORMS["button"].hooks == ("press",)
    assert PLATFORMS["text"].hooks == ("set_value",)
    assert PLATFORMS["sensor"].hooks == ()
    assert PLATFORMS["binary_sensor"].hooks == ()
    assert not PLATFORMS["button"].stateful


@pytest.mark.parametrize(
    "decorate, message",
    [
        (lambda: number_entity(min=5, max=1), "min"),
        (lambda: number_entity(step=0), "step"),
        (lambda: number_entity(mode="dial"), "mode"),
        (lambda: select_entity(options=[]), "options"),
        (lambda: select_entity(), "options"),
        (lambda: sensor_entity(device_class="nope"), "device_class"),
        (lambda: sensor_entity(state_class="sometimes"), "state_class"),
        (lambda: switch_entity(unit="W"), "unit"),
        (lambda: text_entity(pattern="("), "pattern"),
        (lambda: text_entity(mode="secret"), "mode"),
        (lambda: button_entity(initial=1), "initial"),
    ],
)
def test_bad_declarations(decorate: Any, message: str) -> None:
    with pytest.raises(AutomationDefinitionError, match=message):
        decorate()(type("thing", (), {}))


def test_decorating_a_function_fails() -> None:
    with pytest.raises(AutomationDefinitionError, match="class"):
        sensor_entity()(lambda: None)
