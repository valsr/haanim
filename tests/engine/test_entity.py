"""Tests for entity access from action code: haa.entity, haa.state() and HAAnimEntity.

See "Entity Access" and "HAAnimEntity" in the design.
"""

from __future__ import annotations

import operator
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from haanim.engine.errors import NonExistingEntityError
from haanim.engine.expression_eval import Expression
from haanim.engine.haanim_api import EntityDomain, EntityNamespace, HAAnim
from haanim.entity import HAAnimEntity
from haanim.testing import FakeAutomationRegistry, FakeClock, FakeStateProvider, LocalFileSystem, make_host
from haanim.testing.fakes import DEFAULT_NOW
from tests.engine.helpers import automation_file, load_and_run, make_context


@pytest.fixture
def clock() -> FakeClock:
    """A fake clock."""
    return FakeClock()


@pytest.fixture
def states(clock: FakeClock) -> FakeStateProvider:
    """Entity states with a sensor, a light, and an entity whose ID is not an identifier."""
    provider = FakeStateProvider(clock)
    provider.set_state("sensor.temperature", "21.5", {"unit_of_measurement": "°C"})
    provider.set_state("light.living_room", "on", {"brightness": 200, "effects": ["rainbow"]})
    provider.set_state("sensor.3d_printer", "printing", {"progress": 40})
    provider.set_state("automation.bedtime", "off")
    provider.set_state("sensor.dead", "unavailable")
    return provider


@pytest.fixture
def haa(states: FakeStateProvider, clock: FakeClock, tmp_path: Path) -> HAAnim:
    """The haa instance of an automation."""
    host = make_host(states=states, clock=clock)
    return HAAnim(host, "me", FakeAutomationRegistry())


class TestHaaEntity:
    """haa.entity.<domain>.<name> and haa.entity["<id>"]."""

    def test_by_attribute(self, haa: HAAnim) -> None:
        """haa.entity.<domain>.<name> returns a HAAnimEntity."""
        temp = haa.entity.sensor.temperature
        assert type(temp) is HAAnimEntity
        assert (temp.entity_id, temp.state) == ("sensor.temperature", "21.5")

    def test_by_entity_id_string(self, haa: HAAnim) -> None:
        """haa.entity["<domain>.<name>"] returns the same kind of object."""
        temp = haa.entity["sensor.temperature"]
        assert type(temp) is HAAnimEntity
        assert (temp.entity_id, temp.state) == ("sensor.temperature", "21.5")
        assert temp == haa.entity.sensor.temperature

    def test_entity_id_that_is_not_an_identifier(self, haa: HAAnim) -> None:
        """An ID such as sensor.3d_printer needs the bracket form."""
        printer = haa.entity["sensor.3d_printer"]
        assert (printer.exists, printer.state, printer["progress"]) == (True, "printing", 40)

    def test_entity_id_known_at_run_time(self, haa: HAAnim) -> None:
        """The ID can be built by the automation."""
        room = "living_room"
        assert haa.entity[f"light.{room}"].state == "on"

    def test_attribute_through_brackets(self, haa: HAAnim) -> None:
        """haa.entity.<domain>.<name>["attribute"] gives the attribute or None."""
        assert haa.entity.light.living_room["brightness"] == 200
        assert haa.entity.light.living_room["color_temp"] is None

    def test_namespace_types(self, haa: HAAnim) -> None:
        """haa.entity is a namespace and haa.entity.<domain> a domain of it."""
        assert type(haa.entity) is EntityNamespace
        assert type(haa.entity.sensor) is EntityDomain

    def test_domains_do_not_collide_with_the_haa_api(self, haa: HAAnim) -> None:
        """haa.entity.automation.<name> is a native entity; haa.automation() is a HAAnim automation."""
        assert haa.entity.automation.bedtime.state == "off"
        assert callable(haa.automation)

    def test_missing_entity_never_raises(self, haa: HAAnim) -> None:
        """A missing entity gives an object, not None and not an error."""
        for missing in (
            haa.entity.sensor.nothing,
            haa.entity["sensor.nothing"],
            haa.entity["not even an id"],
        ):
            assert missing is not None
            assert (missing.exists, missing.state) == (False, None)

    def test_each_read_is_a_new_snapshot(self, haa: HAAnim, states: FakeStateProvider) -> None:
        """An object read earlier does not change; reading again gives the current value."""
        before = haa.entity.light.living_room
        states.set_state("light.living_room", "off", {"brightness": 0})

        assert (before.state, before["brightness"]) == ("on", 200)
        after = haa.entity.light.living_room
        assert (after.state, after["brightness"]) == ("off", 0)

    def test_entity_removed_after_the_read(self, haa: HAAnim) -> None:
        """A snapshot of a missing entity stays missing when the entity appears."""
        missing = haa.entity.sensor.later
        haa._host.states.set_state("sensor.later", "1")  # type: ignore[attr-defined]  # pylint: disable=protected-access
        assert missing.exists is False
        assert haa.entity.sensor.later.exists is True

    def test_private_names_are_not_entities(self, haa: HAAnim) -> None:
        """Names with a leading underscore are not looked up as domains or entities."""
        with pytest.raises(AttributeError):
            haa.entity._hidden  # pylint: disable=pointless-statement,protected-access
        with pytest.raises(AttributeError):
            haa.entity.sensor._hidden  # pylint: disable=pointless-statement,protected-access


class TestHaaState:
    """haa.state(entity_id)."""

    def test_raw_state_string(self, haa: HAAnim) -> None:
        """The state is returned as the string it is, with no conversion."""
        assert haa.state("sensor.temperature") == "21.5"
        assert haa.state("light.living_room") == "on"
        assert haa.state("sensor.dead") == "unavailable"
        assert haa.state("sensor.3d_printer") == "printing"

    def test_missing_entity_is_none(self, haa: HAAnim) -> None:
        """None if the entity does not exist."""
        assert haa.state("sensor.nothing") is None

    def test_reads_the_current_state(self, haa: HAAnim, states: FakeStateProvider) -> None:
        """Each call reads the state at that moment."""
        states.set_state("sensor.temperature", "30")
        assert haa.state("sensor.temperature") == "30"


class TestOldAccessIsGone:
    """haa.<domain>.<name> no longer exists."""

    def test_domain_is_not_an_attribute_of_haa(self, haa: HAAnim) -> None:
        """Entities are only reachable through haa.entity."""
        for domain in ("sensor", "light", "binary_sensor"):
            with pytest.raises(AttributeError):
                getattr(haa, domain)

    def test_service_access_is_unaffected(self, haa: HAAnim) -> None:
        """haa.service is still the service namespace."""
        assert haa.service is not None


class TestProperties:
    """Every row of the HAAnimEntity table."""

    def test_entity_id(self, haa: HAAnim) -> None:
        """entity_id is the full ID."""
        assert haa.entity.sensor.temperature.entity_id == "sensor.temperature"
        assert haa.entity.sensor.nothing.entity_id == "sensor.nothing"

    def test_exists(self, haa: HAAnim) -> None:
        """exists is False if the host has no such entity."""
        assert haa.entity.sensor.temperature.exists is True
        assert haa.entity.sensor.dead.exists is True
        assert haa.entity.sensor.nothing.exists is False

    def test_state(self, haa: HAAnim) -> None:
        """state is the raw string, None for a missing entity."""
        assert haa.entity.sensor.temperature.state == "21.5"
        assert haa.entity.sensor.nothing.state is None

    def test_attributes(self, haa: HAAnim) -> None:
        """attributes is a dict of all attributes, empty for a missing entity."""
        assert haa.entity.light.living_room.attributes == {"brightness": 200, "effects": ["rainbow"]}
        assert haa.entity.automation.bedtime.attributes == {}
        assert haa.entity.sensor.nothing.attributes == {}

    def test_attributes_cannot_change_the_snapshot(self, haa: HAAnim) -> None:
        """The dict handed out is a copy."""
        light = haa.entity.light.living_room
        light.attributes["brightness"] = 1
        assert light["brightness"] == 200

    def test_single_attribute(self, haa: HAAnim) -> None:
        """["attribute"] is the value, None if missing or if the entity is missing."""
        assert haa.entity.sensor.temperature["unit_of_measurement"] == "°C"
        assert haa.entity.sensor.temperature["nothing"] is None
        assert haa.entity.sensor.nothing["unit_of_measurement"] is None

    def test_no_dotted_attribute_form(self, haa: HAAnim) -> None:
        """There is no entity.brightness."""
        with pytest.raises(AttributeError):
            haa.entity.light.living_room.brightness  # pylint: disable=pointless-statement

    async def test_timestamps(self, haa: HAAnim, states: FakeStateProvider, clock: FakeClock) -> None:
        """last_changed moves with the state, last_updated also with the attributes."""
        first = haa.entity.light.living_room
        assert (first.last_changed, first.last_updated) == (DEFAULT_NOW, DEFAULT_NOW)

        await clock.advance(seconds=300)
        states.set_state("light.living_room", "on", {"brightness": 50})
        second = haa.entity.light.living_room
        assert second.last_changed == DEFAULT_NOW
        assert second.last_updated == DEFAULT_NOW + timedelta(minutes=5)
        assert (first.last_changed, first.last_updated) == (DEFAULT_NOW, DEFAULT_NOW)

    def test_timestamps_of_a_missing_entity(self, haa: HAAnim) -> None:
        """A missing entity has no timestamps."""
        missing = haa.entity.sensor.nothing
        assert (missing.last_changed, missing.last_updated) == (None, None)

    def test_str(self, haa: HAAnim) -> None:
        """str() is the state string; empty for a missing entity."""
        assert str(haa.entity.sensor.temperature) == "21.5"
        assert f"{haa.entity.light.living_room}" == "on"
        assert str(haa.entity.sensor.nothing) == ""

    def test_float(self, haa: HAAnim) -> None:
        """float() converts the state."""
        assert float(haa.entity.sensor.temperature) == 21.5

    def test_int_truncates(self, haa: HAAnim) -> None:
        """int() converts the state as in an expression: 21.5 gives 21."""
        assert int(haa.entity.sensor.temperature) == 21
        assert int(HAAnimEntity("sensor.count", "25")) == 25

    def test_float_and_int_of_a_non_numeric_state(self, haa: HAAnim) -> None:
        """ValueError if the state is not numeric, for example unavailable."""
        with pytest.raises(ValueError, match="sensor.dead is 'unavailable', which is not a number"):
            float(haa.entity.sensor.dead)
        with pytest.raises(ValueError):
            int(haa.entity.sensor.dead)

    def test_float_and_int_of_a_missing_entity(self, haa: HAAnim) -> None:
        """NonExistingEntityError if the entity is missing."""
        with pytest.raises(NonExistingEntityError) as exc_info:
            float(haa.entity.sensor.nothing)
        assert exc_info.value.entity_id == "sensor.nothing"
        with pytest.raises(NonExistingEntityError):
            int(haa.entity.sensor.nothing)

    def test_repr(self, haa: HAAnim) -> None:
        """repr() names the entity and its state."""
        assert repr(haa.entity.sensor.temperature) == "HAAnimEntity('sensor.temperature', state='21.5')"
        assert repr(haa.entity.sensor.nothing) == "HAAnimEntity('sensor.nothing', missing)"

    def test_never_none(self, haa: HAAnim) -> None:
        """The object is never None; exists is the test."""
        assert haa.entity.sensor.nothing is not None

    def test_not_hashable(self, haa: HAAnim) -> None:
        """Equality is by state, so the object cannot be a dict key or set member."""
        with pytest.raises(TypeError):
            hash(haa.entity.sensor.temperature)


class TestStringMethods:
    """The string methods of expressions are forwarded to the state string."""

    def test_each_method(self) -> None:
        """One call per method."""
        status = HAAnimEntity("sensor.status", "  Active,Now  ")
        assert status.upper() == "  ACTIVE,NOW  "
        assert status.lower() == "  active,now  "
        assert status.strip() == "Active,Now"
        assert status.strip().startswith("Act") is True
        assert HAAnimEntity("sensor.file", "report.txt").endswith(".txt") is True
        assert HAAnimEntity("sensor.file", "report.txt").startswith("x") is False
        assert HAAnimEntity("sensor.csv", "a,data,c").split(",") == ["a", "data", "c"]
        assert HAAnimEntity("sensor.csv", "a b  c").split() == ["a", "b", "c"]

    def test_substring(self) -> None:
        """A string in an entity is a substring check on the state."""
        message = HAAnimEntity("sensor.message", "red alert now")
        assert "alert" in message
        assert "calm" not in message

    @pytest.mark.parametrize("method", ["upper", "lower", "strip", "split"])
    def test_method_on_a_missing_entity(self, method: str) -> None:
        """There is no state to apply the method to."""
        with pytest.raises(NonExistingEntityError):
            getattr(HAAnimEntity("sensor.nothing"), method)()

    def test_no_other_string_methods(self) -> None:
        """Only the methods of the expression language exist on the object."""
        with pytest.raises(AttributeError):
            HAAnimEntity("sensor.status", "x").replace("x", "y")  # type: ignore[attr-defined]  # pylint: disable=no-member


OPERATORS = {
    "==": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}

# (state of sensor.x, operator, value compared with, expected); a state of None is a missing entity.
# The same table is evaluated as a trigger expression and as a comparison of a HAAnimEntity.
LITERAL_CASES: list[tuple[str | None, str, Any, bool]] = [
    # A string literal: no conversion
    ("on", "==", "on", True),
    ("on", "==", "off", False),
    ("on", "!=", "off", True),
    ("25", "==", "25", True),
    ("25.0", "==", "25", False),
    ("ON", "==", "on", False),
    ("abc", ">", "abb", True),
    ("abc", "<=", "abc", True),
    # A number literal: float
    ("25", "==", 25, True),
    ("25", "==", 25.0, True),
    ("25.0", "==", 25, True),
    ("26.5", ">", 25, True),
    ("26.5", "<", 25, False),
    ("20", ">=", 20, True),
    ("20", "<=", 19.9, False),
    ("-4", "<", -3.5, True),
    ("21.5", "!=", 21, True),
    # True and False: boolean conversion
    ("on", "==", True, True),
    ("ON", "==", True, True),
    ("true", "==", True, True),
    ("off", "==", False, True),
    ("False", "==", False, True),
    ("on", "!=", False, True),
    ("off", "==", True, False),
    # Unusable: the comparison is false whichever way it is asked
    ("unavailable", ">", 25, False),
    ("unavailable", "<", 25, False),
    ("unavailable", "==", 25, False),
    ("unavailable", "!=", 25, False),
    ("unknown", ">=", 0, False),
    ("home", "==", True, False),
    ("home", "!=", True, False),
    ("home", "==", False, False),
    ("abc", ">", 1, False),
    # Testing for unavailability with a string is not a conversion
    ("unavailable", "==", "unavailable", True),
    ("unavailable", "!=", "unavailable", False),
    ("21.5", "==", "unavailable", False),
    # A missing entity: everything is false
    (None, "==", "on", False),
    (None, "!=", "on", False),
    (None, ">", 5, False),
    (None, "==", True, False),
    (None, "==", "unavailable", False),
]

# (state of sensor.x, operator, state of sensor.y, expected)
ENTITY_CASES: list[tuple[str | None, str, str | None, bool]] = [
    # Both numeric: compared as numbers ("22" < "3.7" as strings)
    ("22", ">", "3.7", True),
    ("22", "<", "3.7", False),
    ("25", "==", "25.0", True),
    ("25", "!=", "25.0", False),
    ("15.5", "<=", "22", True),
    # Otherwise: compared as strings
    ("home", "==", "home", True),
    ("home", "==", "work", False),
    ("home", "!=", "work", True),
    ("work", ">", "home", True),
    ("25", "==", "home", False),
    ("unavailable", "==", "unknown", False),
    ("unavailable", "==", "unavailable", True),
    # A missing entity on either side
    (None, "==", "home", False),
    ("home", "==", None, False),
    ("home", "!=", None, False),
    (None, "==", None, False),
]

# (state of sensor.x, the list, expected for "in")
LIST_CASES: list[tuple[str | None, list[Any], bool]] = [
    ("home", ["home", "garden"], True),
    ("work", ["home", "garden"], False),
    ("25", [1, 25, 50], True),
    ("25.0", [1, 25, 50], True),
    ("25", [1, 2, 3], False),
    ("25", ["25"], True),
    ("25.0", ["25"], False),
    ("on", [True], True),
    ("unavailable", ["unavailable", "unknown"], True),
    ("unavailable", [1, 2, 3], False),
    (None, ["home"], False),
]

# States used on their own: (state, expected truth)
TRUTH_CASES: list[tuple[str | None, bool]] = [
    ("on", True),
    ("ON", True),
    ("true", True),
    ("off", False),
    ("False", False),
    ("home", False),
    ("1", False),
    ("unavailable", False),
    (None, False),
]


def lookup_for(**states: str | None) -> Any:
    """Build a state lookup for expressions over sensor.x and sensor.y."""
    found = {
        f"sensor.{name}": SimpleNamespace(state=state, attributes={})
        for name, state in states.items()
        if state is not None
    }
    return found.get


class TestComparisonParity:
    """A comparison means the same in a trigger expression and on a HAAnimEntity."""

    @pytest.mark.parametrize(("state", "symbol", "other", "expected"), LITERAL_CASES)
    def test_with_a_literal(self, state: str | None, symbol: str, other: Any, expected: bool) -> None:
        """The table, as an expression and as a Python comparison, with the entity on either side."""
        in_expression = Expression(f"sensor.x {symbol} {other!r}").evaluate(lookup_for(x=state)).result
        entity = HAAnimEntity("sensor.x", state)
        on_object = OPERATORS[symbol](entity, other)

        assert in_expression is expected
        assert on_object is expected

    @pytest.mark.parametrize(("state", "symbol", "other", "expected"), LITERAL_CASES)
    def test_with_the_literal_on_the_left(
        self, state: str | None, symbol: str, other: Any, expected: bool
    ) -> None:
        """Mirrored: 25 < entity gives what entity > 25 gives, in both worlds."""
        mirrored = {"==": "==", "!=": "!=", "<": ">", "<=": ">=", ">": "<", ">=": "<="}[symbol]
        in_expression = Expression(f"{other!r} {mirrored} sensor.x").evaluate(lookup_for(x=state)).result
        on_object = OPERATORS[mirrored](other, HAAnimEntity("sensor.x", state))

        assert in_expression is expected
        assert on_object is expected

    @pytest.mark.parametrize(("left", "symbol", "right", "expected"), ENTITY_CASES)
    def test_with_another_entity(
        self, left: str | None, symbol: str, right: str | None, expected: bool
    ) -> None:
        """Two entities: numbers if both are numeric, strings otherwise."""
        in_expression = Expression(f"sensor.x {symbol} sensor.y").evaluate(lookup_for(x=left, y=right)).result
        on_object = OPERATORS[symbol](HAAnimEntity("sensor.x", left), HAAnimEntity("sensor.y", right))

        assert in_expression is expected
        assert on_object is expected

    @pytest.mark.parametrize(("state", "items", "expected"), LIST_CASES)
    def test_in_a_list(self, state: str | None, items: list[Any], expected: bool) -> None:
        """Membership in a list compares with each item by the item's type."""
        in_expression = Expression(f"sensor.x in {items!r}").evaluate(lookup_for(x=state)).result
        on_object = HAAnimEntity("sensor.x", state) in items

        assert in_expression is expected
        assert on_object is expected

    @pytest.mark.parametrize(("state", "expected"), TRUTH_CASES)
    def test_on_its_own(self, state: str | None, expected: bool) -> None:
        """Used as a condition, the state is converted to a boolean."""
        in_expression = Expression("sensor.x").evaluate(lookup_for(x=state)).result
        on_object = bool(HAAnimEntity("sensor.x", state))

        assert in_expression is expected
        assert on_object is expected

    def test_chained_comparison(self) -> None:
        """A range check works on the object as in an expression."""
        outdoor = HAAnimEntity("sensor.outdoor_temp", "20")
        assert (15 <= outdoor <= 25) is True
        assert (21 <= outdoor <= 25) is False
        assert Expression("15 <= sensor.x <= 25").evaluate(lookup_for(x="20")).result is True

    def test_substring_parity(self) -> None:
        """'alert' in entity means the same in both."""
        assert Expression("'alert' in sensor.x").evaluate(lookup_for(x="red alert")).result is True
        assert ("alert" in HAAnimEntity("sensor.x", "red alert")) is True
        assert ("alert" in HAAnimEntity("sensor.x")) is False
        assert (5 in HAAnimEntity("sensor.x", "5")) is False

    def test_attribute_values_are_plain_python_values(self) -> None:
        """An attribute read with brackets is not converted in either world."""
        light = HAAnimEntity("light.x", "on", attributes={"brightness": 200})
        assert light["brightness"] > 100
        found = {"light.x": SimpleNamespace(state="on", attributes={"brightness": 200})}
        assert Expression("light.x['brightness'] > 100").evaluate(found.get).result is True


ACTION_SOURCE = """
from haanim import HAAnimEntity, action, haa

@action
def access_entities(event):
    temp = haa.entity.sensor.temperature
    raw = haa.state("sensor.temperature")
    brightness = haa.entity.light.living_room["brightness"]
    printer = haa.entity["sensor.3d_printer"]

    if not temp.exists:
        return "No temperature sensor"

    result = {
        "is_entity": isinstance(temp, HAAnimEntity),
        "raw": raw,
        "brightness": brightness,
        "printer": printer.state,
        "high": temp > 20,
        "state": temp.state,
        "text": f"Temperature: {temp}",
        "number": float(temp) + 1,
    }
    return result

@action
def missing(event):
    ghost = haa.entity.sensor.ghost
    return [ghost.exists, ghost.state, ghost["x"], ghost > 1, haa.state("sensor.ghost")]
"""


class TestFromAutomationCode:
    """The design's example, run by the interpreter."""

    async def test_access_entities(self, states: FakeStateProvider, clock: FakeClock, tmp_path: Path) -> None:
        """An action reads entities, attributes and raw states."""
        path = automation_file(tmp_path, "reader")
        path.write_text(ACTION_SOURCE, encoding="utf-8")
        context = make_context(str(path), host=make_host(states=states, clock=clock, files=LocalFileSystem()))
        await load_and_run(context)

        assert await context.run_action("access_entities") == {
            "is_entity": True,
            "raw": "21.5",
            "brightness": 200,
            "printer": "printing",
            "high": True,
            "state": "21.5",
            "text": "Temperature: 21.5",
            "number": 22.5,
        }
        assert await context.run_action("missing") == [False, None, None, False, None]

    async def test_old_access_fails_in_automation_code(
        self, states: FakeStateProvider, clock: FakeClock, tmp_path: Path
    ) -> None:
        """haa.sensor.temperature raises AttributeError."""
        path = automation_file(tmp_path, "old")
        path.write_text(
            "from haanim import action, haa\n\n@action\ndef old(event):\n    return haa.sensor.temperature\n",
            encoding="utf-8",
        )
        context = make_context(str(path), host=make_host(states=states, clock=clock, files=LocalFileSystem()))
        await load_and_run(context)

        with pytest.raises(AttributeError):
            await context.run_action("old")
