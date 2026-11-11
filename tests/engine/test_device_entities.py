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
    validate_state,
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
        (lambda: sensor_entity(device_class="timestamp"), "device_class"),
        (lambda: sensor_entity(device_class="enum"), "device_class"),
        (lambda: number_entity(min="low"), "min"),
        (lambda: text_entity(min_length="3"), "min_length"),
        (lambda: text_entity(max_length=True), "max_length"),
        (lambda: text_entity(max_length=-1), "max_length"),
        (lambda: text_entity(max_length=256), "max_length"),
        (lambda: text_entity(min_length=10, max_length=5), "min_length 10 is greater than max_length 5"),
        (lambda: text_entity(min_length=300), "min_length"),
        (lambda: sensor_entity(precision="2"), "precision"),
        (lambda: sensor_entity(precision=-1), "precision"),
        (lambda: sensor_entity(unit=5), "unit"),
        (lambda: number_entity(unit=5), "unit"),
        (lambda: switch_entity(attributes={"since": object()}), "attributes"),
        (lambda: switch_entity(attributes=["a"]), "attributes"),
        (lambda: switch_entity(attributes={1: "a"}), "attributes"),
    ],
)
def test_bad_declarations(decorate: Any, message: str) -> None:
    with pytest.raises(AutomationDefinitionError, match=message):
        decorate()(type("thing", (), {}))


def test_decorating_a_function_fails() -> None:
    with pytest.raises(AutomationDefinitionError, match="class"):
        sensor_entity()(lambda: None)


# --- State validation -------------------------------------------------------------


@pytest.mark.parametrize(
    "platform, options, value, expected",
    [
        ("sensor", {"unit": "°C"}, 21, 21.0),
        ("sensor", {"state_class": "measurement"}, "3.5", 3.5),
        ("sensor", {}, "hello", "hello"),
        ("sensor", {}, {"a": [1, 2]}, {"a": [1, 2]}),
        ("binary_sensor", {}, "on", True),
        ("binary_sensor", {}, "off", False),
        ("switch", {}, False, False),
        ("number", {"min": 0, "max": 10}, "5", 5.0),
        ("number", {}, 100, 100.0),
        ("select", {"options": ["a", "b"]}, "b", "b"),
        ("text", {"pattern": "[a-z]+"}, "abc", "abc"),
        ("text", {}, "", ""),
        ("sensor", {"unit": "°C"}, None, None),
        ("switch", {}, None, None),
        ("sensor", {"device_class": "temperature"}, "21", 21.0),
    ],
)
def test_valid_states(platform: str, options: dict[str, Any], value: Any, expected: Any) -> None:
    assert validate_state(platform, options, value) == expected


@pytest.mark.parametrize(
    "platform, options, value",
    [
        ("sensor", {"unit": "°C"}, "warm"),
        ("sensor", {"unit": "°C"}, True),
        ("number", {"min": 0, "max": 10}, 11),
        ("number", {}, -1),
        ("number", {}, True),
        ("switch", {}, "yes"),
        ("switch", {}, 1),
        ("select", {"options": ["a"]}, "z"),
        ("text", {"max_length": 2}, "abc"),
        ("text", {"min_length": 2}, "a"),
        ("text", {}, "x" * 256),
        ("text", {"pattern": "[a-z]+"}, "abc1"),
        ("text", {}, 5),
        ("button", {}, 1),
        ("sensor", {}, object()),
        ("sensor", {"device_class": "temperature"}, "hot"),
        ("sensor", {"precision": 1}, "hot"),
        ("sensor", {"unit": "°C"}, float("nan")),
        ("number", {}, float("inf")),
    ],
)
def test_invalid_states(platform: str, options: dict[str, Any], value: Any) -> None:
    with pytest.raises(ValueError):
        validate_state(platform, options, value)


def test_initial_is_validated() -> None:
    with pytest.raises(AutomationDefinitionError, match="initial"):
        number_entity(min=0, max=10, initial=11)(type("thing", (), {}))


def test_valid_initial_is_normalized() -> None:
    @switch_entity(initial="on")
    class boost:  # pylint: disable=invalid-name
        pass

    declaration = get_declaration(boost)
    assert declaration is not None
    assert declaration.initial is True
