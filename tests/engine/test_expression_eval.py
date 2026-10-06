"""Tests for the state expression language.

See "Expression Syntax" in the design. The cases are tables: each row is an
expression and its value against the states in ``STATES``.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from haanim.engine import expression_eval
from haanim.engine.errors import AutomationSyntaxError
from haanim.engine.expression_eval import (
    Evaluation,
    Expression,
    evaluate_expression,
    parse_expression,
)
from tests.engine.test_lifecycle import World, world  # noqa: F401  pylint: disable=unused-import


def entity(state: str, **attributes: Any) -> SimpleNamespace:
    """Build what the state lookup returns for an entity."""
    return SimpleNamespace(state=state, attributes=attributes)


STATES: dict[str, SimpleNamespace] = {
    "sensor.temperature": entity("26.5"),
    "sensor.outdoor_temp": entity("20"),
    "sensor.indoor": entity("22"),
    "sensor.outdoor": entity("15.5"),
    "sensor.count": entity("25"),
    "sensor.count_float": entity("25.0"),
    "sensor.negative": entity("-4"),
    "sensor.temp1": entity("18"),
    "sensor.temp2": entity("21.5"),
    "sensor.number": entity("3.7"),
    "light.living_room": entity(
        "on", brightness=200, friendly_name="Living Room", effects=["rainbow", "pulse"], is_group=False
    ),
    "light.kitchen": entity("off", brightness="120"),
    "binary_sensor.motion": entity("off"),
    "binary_sensor.door": entity("on"),
    "switch.pump": entity("ON"),
    "input_boolean.flag": entity("True"),
    "input_boolean.other": entity("false"),
    "person.john": entity("home"),
    "person.jane": entity("home"),
    "person.bob": entity("work"),
    "sensor.status": entity("active", friendly_name="online status"),
    "sensor.shouting": entity("ACTIVE"),
    "sensor.file": entity("report.txt"),
    "sensor.message": entity("red alert now"),
    "sensor.value": entity("  padded  "),
    "sensor.csv": entity("a,data,c"),
    "sensor.weather": entity("sunny", temperature=12.5),
    "sensor.dead": entity("unavailable"),
    "sensor.lost": entity("unknown"),
    "sensor.words": entity("abc"),
    "sensor.zero": entity("0"),
}


def lookup(entity_id: str) -> SimpleNamespace | None:
    """Return the state of an entity of the table, or None."""
    return STATES.get(entity_id)


def value_of(source: str) -> bool:
    """Evaluate an expression against the table."""
    return parse_expression(source).evaluate(lookup).result


def check_table(cases: list[tuple[str, bool]]) -> None:
    """Assert every row of a table, reporting all rows that are wrong."""
    wrong = [(source, expected) for source, expected in cases if value_of(source) is not expected]
    assert not wrong, f"wrong value for: {wrong}"


def is_unusable(source: str) -> bool:
    """Return whether evaluating an expression met an unusable value."""
    evaluation = parse_expression(source).evaluate(lookup)
    assert evaluation.unusable is None or evaluation.result is False
    return evaluation.unusable is not None


class TestComparisonOperators:
    """== != > < >= <=."""

    def test_each_operator(self) -> None:
        """One true and one false case per comparison operator."""
        check_table(
            [
                ("person.john == 'home'", True),
                ("person.john == 'work'", False),
                ("person.john != 'work'", True),
                ("person.john != 'home'", False),
                ("sensor.temperature > 10", True),
                ("sensor.temperature > 50", False),
                ("sensor.temperature < 50", True),
                ("sensor.temperature < 10", False),
                ("sensor.outdoor_temp >= 20", True),
                ("sensor.outdoor_temp >= 20.1", False),
                ("sensor.outdoor_temp <= 20", True),
                ("sensor.outdoor_temp <= 19.9", False),
            ]
        )

    def test_literal_on_the_left(self) -> None:
        """The literal can be on either side."""
        check_table(
            [
                ("10 < sensor.temperature", True),
                ("'home' == person.john", True),
                ("True == binary_sensor.door", True),
                ("50 < sensor.temperature", False),
            ]
        )

    def test_chained_comparison(self) -> None:
        """A range check converts the entity to float for both comparisons."""
        check_table(
            [
                ("15 <= sensor.outdoor_temp <= 25", True),
                ("15 <= sensor.temperature <= 25", False),
                ("21 <= sensor.outdoor_temp <= 25", False),
                ("sensor.outdoor < sensor.outdoor_temp < sensor.temperature", True),
                ("0 < sensor.outdoor_temp < 100 > sensor.temperature", True),
            ]
        )


class TestLogicalOperators:
    """and, or, not."""

    def test_each_operator(self) -> None:
        """Truth tables over entity comparisons."""
        check_table(
            [
                ("sensor.temperature > 25 and light.living_room == 'on'", True),
                ("sensor.temperature > 25 and light.living_room == 'off'", False),
                ("sensor.temperature > 50 and light.living_room == 'on'", False),
                ("sensor.temperature > 50 or light.living_room == 'on'", True),
                ("sensor.temperature > 25 or light.living_room == 'off'", True),
                ("sensor.temperature > 50 or light.living_room == 'off'", False),
                ("not sensor.temperature > 50", True),
                ("not sensor.temperature > 25", False),
                ("not (sensor.temperature > 25)", False),
                ("not not binary_sensor.door", True),
            ]
        )

    def test_three_operands(self) -> None:
        """and and or take any number of operands."""
        check_table(
            [
                ("binary_sensor.door and light.living_room and switch.pump", True),
                ("binary_sensor.door and binary_sensor.motion and switch.pump", False),
                ("binary_sensor.motion or input_boolean.other or binary_sensor.door", True),
                ("binary_sensor.motion or input_boolean.other or light.kitchen", False),
            ]
        )


class TestArithmetic:
    """+ - * / // %."""

    def test_each_operator(self) -> None:
        """Every arithmetic operator, with states converted to float."""
        check_table(
            [
                ("sensor.indoor + sensor.outdoor == 37.5", True),
                ("sensor.indoor - sensor.outdoor == 6.5", True),
                ("sensor.indoor * 2 == 44", True),
                ("sensor.indoor / 4 == 5.5", True),
                ("sensor.temperature // 5 == 5", True),
                ("sensor.temperature % 5 == 1.5", True),
                ("sensor.indoor + 1 > 23", False),
                ("sensor.indoor - sensor.outdoor > 5", True),
            ]
        )

    def test_signs(self) -> None:
        """A sign applies to a literal and to an entity."""
        check_table(
            [
                ("sensor.negative == -4", True),
                ("-sensor.negative == 4", True),
                ("+sensor.negative == -4", True),
                ("sensor.negative < -3.5", True),
            ]
        )

    def test_number_alone_is_true_unless_zero(self) -> None:
        """The result of arithmetic used on its own follows Python's truth of numbers."""
        check_table([("sensor.indoor - 22", False), ("sensor.indoor - 21", True)])


class TestMembership:
    """in and not in."""

    def test_string_lists(self) -> None:
        """An entity in a list of strings is compared as a string."""
        check_table(
            [
                ("person.john in ['home', 'garden']", True),
                ("person.bob in ['home', 'garden']", False),
                ("person.bob not in ['home', 'garden']", True),
                ("person.john not in ['home', 'garden']", False),
                ("person.john in ('home', 'garden')", True),
            ]
        )

    def test_number_lists(self) -> None:
        """An entity in a list of numbers is converted to float for each item."""
        check_table(
            [
                ("sensor.count in [1, 25, 50]", True),
                ("sensor.count_float in [1, 25, 50]", True),
                ("sensor.count in [1, 2, 3]", False),
                ("sensor.count not in [1, 2, 3]", True),
                ("sensor.count in [24.9, 25.0]", True),
            ]
        )

    def test_boolean_list(self) -> None:
        """An entity in a list of booleans is converted to a boolean."""
        check_table([("binary_sensor.door in [True]", True), ("binary_sensor.motion in [True]", False)])

    def test_list_of_entities(self) -> None:
        """A list can hold entities; each is compared by the entity rule."""
        check_table(
            [
                ("person.john in [person.jane, person.bob]", True),
                ("sensor.count in [sensor.count_float, sensor.zero]", True),
                ("person.bob in [person.jane, person.john]", False),
            ]
        )

    def test_substring(self) -> None:
        """A string in an entity is a substring check on the state."""
        check_table(
            [
                ("'alert' in sensor.message", True),
                ("'calm' in sensor.message", False),
                ("'calm' not in sensor.message", True),
                ("sensor.words in sensor.words", True),
                ("'Room' in light.living_room['friendly_name']", True),
            ]
        )

    def test_item_of_an_attribute_list(self) -> None:
        """Membership in an attribute that is a list."""
        check_table(
            [
                ("'pulse' in light.living_room['effects']", True),
                ("'strobe' in light.living_room['effects']", False),
            ]
        )


class TestPrecedence:
    """The design's precedence list, highest first."""

    def test_multiplication_before_addition(self) -> None:
        """2 + 3 * 4 is 14."""
        check_table([("2 + 3 * 4 == 14", True), ("(2 + 3) * 4 == 20", True), ("10 - 6 // 4 == 9", True)])

    def test_arithmetic_before_comparison(self) -> None:
        """a + 1 > b is (a + 1) > b."""
        check_table(
            [("sensor.outdoor + 7 > sensor.indoor", True), ("sensor.outdoor + 6 > sensor.indoor", False)]
        )

    def test_comparison_before_not(self) -> None:
        """not a == b is not (a == b)."""
        check_table([("not person.john == 'work'", True), ("not person.john == 'home'", False)])

    def test_not_before_and(self) -> None:
        """not a and b is (not a) and b."""
        check_table(
            [
                ("not binary_sensor.motion and binary_sensor.door", True),
                ("not binary_sensor.door and binary_sensor.motion", False),
            ]
        )

    def test_and_before_or(self) -> None:
        """a or b and c is a or (b and c)."""
        check_table(
            [
                ("binary_sensor.door or binary_sensor.motion and binary_sensor.motion", True),
                ("(binary_sensor.door or binary_sensor.motion) and binary_sensor.motion", False),
            ]
        )

    def test_parentheses_first(self) -> None:
        """Grouping overrides everything."""
        check_table(
            [
                ("(binary_sensor.motion or binary_sensor.door) and light.living_room", True),
                ("binary_sensor.motion or binary_sensor.door and light.kitchen", False),
            ]
        )


class TestConversionTable:
    """One test per row of the design's conversion table."""

    def test_string_literal_is_no_conversion(self) -> None:
        """With a string literal the state is compared as a string, even if it looks numeric."""
        check_table(
            [
                ("sensor.count == '25'", True),
                ("sensor.count_float == '25'", False),
                ("sensor.count == '25.0'", False),
                ("switch.pump == 'on'", False),
                ("switch.pump == 'ON'", True),
                ("sensor.words > 'abb'", True),
            ]
        )

    def test_number_literal_converts_to_float(self) -> None:
        """25 and 25.0 behave the same."""
        check_table(
            [
                ("sensor.count == 25", True),
                ("sensor.count == 25.0", True),
                ("sensor.count_float == 25", True),
                ("sensor.count_float == 25.0", True),
                ("sensor.number == 3.7", True),
                ("sensor.number > 3", True),
            ]
        )

    def test_true_and_false_convert_to_boolean(self) -> None:
        """With True or False the state is converted to a boolean."""
        check_table(
            [
                ("binary_sensor.door == True", True),
                ("binary_sensor.door == False", False),
                ("binary_sensor.motion == False", True),
                ("binary_sensor.motion != True", True),
                ("switch.pump == True", True),
                ("input_boolean.flag == True", True),
                ("input_boolean.other == False", True),
            ]
        )

    def test_two_numeric_entities_compare_as_float(self) -> None:
        """Both numeric: compared as numbers, not as strings."""
        check_table(
            [
                ("sensor.indoor > sensor.outdoor", True),
                ("sensor.count == sensor.count_float", True),
                # As strings "22" < "3.7"; as numbers it is not
                ("sensor.indoor > sensor.number", True),
            ]
        )

    def test_two_entities_otherwise_compare_as_strings(self) -> None:
        """If either is not numeric, the states are compared as strings."""
        check_table(
            [
                ("person.john == person.jane", True),
                ("person.john == person.bob", False),
                ("person.john != person.bob", True),
                ("sensor.count == person.john", False),
                ("sensor.dead == sensor.lost", False),
                ("person.bob > person.john", True),
            ]
        )

    def test_arithmetic_converts_to_float(self) -> None:
        """A state in arithmetic is a number."""
        check_table([("sensor.count + sensor.count_float == 50", True), ("sensor.number * 10 == 37", True)])

    def test_numeric_functions_convert_to_float(self) -> None:
        """abs, min, max and round take the state as a number."""
        check_table(
            [
                ("abs(sensor.negative) == 4", True),
                ("min(sensor.temp1, sensor.temp2) == 18", True),
                ("max(sensor.temp1, sensor.temp2) == 21.5", True),
                ("round(sensor.temperature) == 26", True),
            ]
        )

    def test_entity_on_its_own_converts_to_boolean(self) -> None:
        """Alone, or with and, or, not: on/true are True, off/false are False."""
        check_table(
            [
                ("binary_sensor.door", True),
                ("binary_sensor.motion", False),
                ("not binary_sensor.motion", True),
                ("light.living_room and binary_sensor.door", True),
                ("light.kitchen or binary_sensor.motion", False),
            ]
        )

    def test_list_items_use_the_rule_of_their_own_type(self) -> None:
        """In a list, a string item compares as a string and a number item as a number."""
        check_table(
            [
                ("sensor.count in ['25']", True),
                ("sensor.count_float in ['25']", False),
                ("sensor.count_float in [25]", True),
                ("sensor.count in ['x', 25]", True),
            ]
        )


class TestBooleanConversion:
    """on and true are True, off and false are False, ignoring case; nothing else converts."""

    @pytest.mark.parametrize("state", ["on", "ON", "On", "true", "True", "TRUE"])
    def test_true_states(self, state: str) -> None:
        """Spellings of on and true."""
        evaluation = Expression("switch.x").evaluate(lambda _: entity(state))
        assert (evaluation.result, evaluation.unusable) == (True, None)

    @pytest.mark.parametrize("state", ["off", "OFF", "Off", "false", "False", "FALSE"])
    def test_false_states(self, state: str) -> None:
        """Spellings of off and false: False, and usable."""
        evaluation = Expression("switch.x").evaluate(lambda _: entity(state))
        assert (evaluation.result, evaluation.unusable) == (False, None)
        assert Expression("not switch.x").evaluate(lambda _: entity(state)).result is True

    @pytest.mark.parametrize("state", ["home", "1", "0", "yes", "no", "", "unavailable", "unknown", "open"])
    def test_other_states_cannot_be_converted(self, state: str) -> None:
        """Any other state is unusable as a boolean, so even its negation is false."""
        for source in ("switch.x", "not switch.x", "switch.x == True", "switch.x == False"):
            evaluation = Expression(source).evaluate(lambda _: entity(state))
            assert evaluation.result is False
            assert evaluation.unusable is not None

    @pytest.mark.parametrize("word", ["on", "off", "true", "false"])
    def test_unquoted_words_are_not_literals(self, word: str) -> None:
        """Booleans are written True and False; on and off need quotes."""
        with pytest.raises(AutomationSyntaxError, match=f"'{word}' is not a literal"):
            Expression(f"light.kitchen == {word}")


class TestAttributes:
    """Attributes use bracket notation and keep the type the host gives them."""

    def test_values_are_not_converted(self) -> None:
        """A number stays a number, a string a string, a boolean a boolean."""
        check_table(
            [
                ("light.living_room['brightness'] > 100", True),
                ("light.living_room['brightness'] == 200", True),
                ("light.living_room['brightness'] == '200'", False),
                ("light.living_room['friendly_name'] == 'Living Room'", True),
                ("sensor.weather['temperature'] < 13", True),
                ("light.living_room['is_group'] == False", True),
                ("not light.living_room['is_group']", True),
                ("light.kitchen['brightness'] == '120'", True),
                ("light.kitchen['brightness'] == 120", False),
            ]
        )

    def test_string_attribute_is_not_converted_for_a_number(self) -> None:
        """A string attribute ordered against a number cannot be compared: unusable."""
        assert is_unusable("light.kitchen['brightness'] > 100")

    def test_attribute_in_arithmetic(self) -> None:
        """A numeric attribute can be calculated with."""
        check_table(
            [
                ("light.living_room['brightness'] / 2 == 100", True),
                ("sensor.weather['temperature'] + sensor.temperature == 39", True),
            ]
        )

    def test_attribute_compared_with_an_entity(self) -> None:
        """An entity compared with an attribute converts by the attribute's type."""
        check_table(
            [
                ("sensor.count < light.living_room['brightness']", True),
                ("person.john == light.living_room['friendly_name']", False),
            ]
        )

    def test_attribute_name_from_double_quotes(self) -> None:
        """Either kind of quote."""
        check_table([('light.living_room["brightness"] == 200', True)])


class TestExplicitConversion:
    """int(), float() and len()."""

    def test_functions(self) -> None:
        """The design's examples of explicit conversion."""
        check_table(
            [
                ("int(sensor.number) == 3", True),
                ("float(sensor.number) == 3.7", True),
                ("int(sensor.count) == 25", True),
                ("float(sensor.count) / 2 == 12.5", True),
                ("len(person.john) == 4", True),
                ("len(sensor.dead) == 11", True),
                ("int(light.kitchen['brightness']) > 100", True),
                ("float('2.5') == 2.5", True),
            ]
        )

    def test_failed_explicit_conversion_is_unusable(self) -> None:
        """int() or float() of a non-numeric state."""
        assert is_unusable("int(person.john) == 1")
        assert is_unusable("float(sensor.dead) > 0")


class TestStringMethods:
    """The string methods of the design, on states and on string attributes."""

    def test_each_method(self) -> None:
        """One case per method, as in the design."""
        check_table(
            [
                ("sensor.status.upper() == 'ACTIVE'", True),
                ("sensor.shouting.lower() == 'active'", True),
                ("sensor.file.endswith('.txt')", True),
                ("sensor.file.endswith('.csv')", False),
                ("sensor.status['friendly_name'].startswith('on')", True),
                ("sensor.status.startswith('in')", False),
                ("'alert' in sensor.message", True),
                ("sensor.value.strip() == 'padded'", True),
                ("sensor.value == 'padded'", False),
                ("sensor.csv.split(',') == ['a', 'data', 'c']", True),
            ]
        )

    def test_methods_chain(self) -> None:
        """The result of a method is a string or list that further methods apply to."""
        check_table(
            [
                ("sensor.value.strip().upper() == 'PADDED'", True),
                ("sensor.csv.upper().split(',')[1] == 'DATA'", True),
                ("sensor.status.upper().lower().startswith('act')", True),
            ]
        )

    def test_method_on_a_numeric_state_uses_the_string(self) -> None:
        """A method is applied to the state string, whatever it holds."""
        check_table([("sensor.count.startswith('2')", True), ("sensor.number.split('.')[0] == '3'", True)])

    def test_method_on_a_missing_entity(self) -> None:
        """Nothing to apply the method to."""
        assert is_unusable("sensor.ghost.upper() == 'X'")

    def test_string_method_on_a_number_is_unusable(self) -> None:
        """A numeric attribute has no string methods."""
        assert is_unusable("light.living_room['brightness'].upper() == 'X'")


class TestListMethods:
    """len() of a list and .index()."""

    def test_design_examples(self) -> None:
        """Counting the items and finding one."""
        check_table(
            [
                ("len(sensor.csv.split(',')) == 3", True),
                ("sensor.csv.split(',').index('data') == 1", True),
                ("sensor.csv.split(',').index('a') == 0", True),
                ("light.living_room['effects'].index('pulse') == 1", True),
                ("len(light.living_room['effects']) == 2", True),
            ]
        )

    def test_index_of_a_missing_item_is_unusable(self) -> None:
        """An item that is not in the list has no index."""
        assert is_unusable("sensor.csv.split(',').index('nope') == 0")

    def test_index_out_of_range_is_unusable(self) -> None:
        """Indexing past the end of a list."""
        assert is_unusable("sensor.csv.split(',')[7] == 'x'")


class TestStandardFunctions:
    """len, abs, min, max, round, int, float."""

    def test_each_function(self) -> None:
        """One case per function, as in the design."""
        check_table(
            [
                ("len(person.john) == 4", True),
                ("abs(sensor.temperature) == 26.5", True),
                ("abs(sensor.negative) == 4", True),
                ("min(sensor.temp1, sensor.temp2) == 18", True),
                ("max(sensor.temp1, sensor.temp2) == 21.5", True),
                ("round(sensor.temperature, 1) == 26.5", True),
                ("round(sensor.number) == 4", True),
                ("int(sensor.number) == 3", True),
                ("float(sensor.count) == 25.0", True),
            ]
        )

    def test_functions_with_literals_and_expressions(self) -> None:
        """Arguments can be numbers and arithmetic."""
        check_table(
            [
                ("max(sensor.temp1, 20, sensor.temp2 - 5) == 20", True),
                ("min(sensor.indoor - sensor.outdoor, 5) == 5", True),
                ("abs(sensor.outdoor - sensor.indoor) > 6", True),
                ("round(sensor.indoor / 3, 2) == 7.33", True),
            ]
        )

    def test_numeric_function_of_a_non_numeric_state_is_unusable(self) -> None:
        """abs, min, max and round need a number."""
        for source in ("abs(person.john) > 1", "min(sensor.dead, 3) == 3", "round(sensor.lost) == 0"):
            assert is_unusable(source), source

    def test_wrong_number_of_arguments_is_unusable(self) -> None:
        """A call that Python would reject makes the expression false."""
        assert is_unusable("len(person.john, person.bob) == 4")
        assert is_unusable("abs() == 0")


class TestUnusableValues:
    """If any value is unusable, the whole expression is false."""

    def test_missing_entity(self) -> None:
        """An entity that does not exist."""
        for source in (
            "sensor.ghost > 5",
            "sensor.ghost == 'on'",
            "sensor.ghost",
            "sensor.ghost == 'unavailable'",
            "sensor.ghost in ['a', 'b']",
            "sensor.ghost['brightness'] == 1",
        ):
            assert is_unusable(source), source

    def test_failed_number_conversion(self) -> None:
        """unavailable, unknown or other non-numeric text used with a number."""
        for source in (
            "sensor.dead > 25",
            "sensor.lost < 25",
            "person.john == 5",
            "sensor.dead + 1 > 0",
            "sensor.words * 2 == 4",
            "sensor.dead in [1, 2, 3]",
            "15 <= sensor.dead <= 25",
        ):
            assert is_unusable(source), source

    def test_failed_boolean_conversion(self) -> None:
        """A state other than on/off/true/false used as a boolean."""
        for source in (
            "person.john",
            "sensor.dead",
            "sensor.count and binary_sensor.door",
            "person.john == True",
        ):
            assert is_unusable(source), source

    def test_missing_attribute(self) -> None:
        """An attribute that does not exist, in a comparison or in arithmetic."""
        for source in (
            "light.living_room['color_temp'] > 300",
            "light.living_room['color_temp'] == 300",
            "light.living_room['color_temp'] + 1 > 0",
        ):
            assert is_unusable(source), source

    def test_negation_is_also_false(self) -> None:
        """not (sensor.temperature > 25) is false while the sensor is unavailable."""
        assert value_of("sensor.dead > 25") is False
        assert value_of("not (sensor.dead > 25)") is False
        assert value_of("not sensor.dead > 25") is False
        assert value_of("sensor.dead != 25") is False

    def test_or_does_not_rescue_the_expression(self) -> None:
        """a > 5 or b < 3 is false while a is unavailable even if b < 3 holds."""
        assert value_of("sensor.zero < 3") is True
        assert value_of("sensor.dead > 5 or sensor.zero < 3") is False
        assert value_of("sensor.zero < 3 or sensor.dead > 5") is False

    def test_and_with_a_false_side_is_still_unusable(self) -> None:
        """There is no short circuit: the unusable value is noticed on either side."""
        assert is_unusable("sensor.zero > 3 and sensor.dead > 5")
        assert is_unusable("sensor.dead > 5 and sensor.zero > 3")

    def test_unusable_item_in_a_list(self) -> None:
        """Every item of a list is looked at, also after a match."""
        assert is_unusable("person.john in ['home', person.ghost]")
        assert is_unusable("sensor.dead in ['unavailable', 5]")

    def test_division_by_zero(self) -> None:
        """A calculation that cannot be done."""
        assert is_unusable("sensor.count / sensor.zero > 1")
        assert is_unusable("sensor.count % 0 == 1")

    def test_comparing_values_that_cannot_be_ordered(self) -> None:
        """Ordering a list against a number, or a string against a number."""
        assert is_unusable("light.living_room['effects'] > 3")
        assert is_unusable("sensor.status.upper() > 3")

    def test_explicit_test_for_unavailability(self) -> None:
        """Comparing with a string is never a conversion."""
        check_table(
            [
                ("sensor.dead == 'unavailable'", True),
                ("sensor.temperature == 'unavailable'", False),
                ("sensor.dead in ['unavailable', 'unknown']", True),
                ("sensor.lost in ['unavailable', 'unknown']", True),
                ("sensor.temperature in ['unavailable', 'unknown']", False),
                ("sensor.dead != 'unavailable'", False),
                ("sensor.dead == 'unavailable' or sensor.temperature > 25", True),
            ]
        )

    def test_when_not_blocks_on_an_unusable_value(self) -> None:
        """As when_not, an expression blocks when it is true and also when a value is unusable."""
        assert parse_expression("binary_sensor.door").blocks(lookup) is True
        assert parse_expression("binary_sensor.motion").blocks(lookup) is False
        assert parse_expression("sensor.dead > 25").blocks(lookup) is True
        assert parse_expression("sensor.ghost == 'on'").blocks(lookup) is True

    def test_when_holds_only_if_usable_and_true(self) -> None:
        """As when, an expression lets a trigger through only when it is true."""
        assert parse_expression("binary_sensor.door").holds(lookup) is True
        assert parse_expression("binary_sensor.motion").holds(lookup) is False
        assert parse_expression("sensor.dead > 25").holds(lookup) is False

    def test_becomes_true_when_the_entity_becomes_available(self) -> None:
        """False because of an unusable value counts as false: the next evaluation can be true."""
        states = {"sensor.t": entity("unavailable")}
        expression = parse_expression("sensor.t > 25")
        assert expression.holds(states.get) is False
        states["sensor.t"] = entity("30")
        assert expression.holds(states.get) is True

    def test_entity_with_no_state_is_missing(self) -> None:
        """A lookup result without a state is treated as a missing entity."""
        evaluation = Expression("sensor.t == 'x'").evaluate(
            lambda _: SimpleNamespace(state=None, attributes={})
        )
        assert evaluation.unusable == "sensor.t does not exist"

    def test_logged_at_debug_level_only(self, caplog: pytest.LogCaptureFixture) -> None:
        """An unusable value is not a warning."""
        with caplog.at_level(logging.DEBUG, logger="haanim.engine.expression_eval"):
            assert value_of("sensor.dead > 25") is False
            assert value_of("sensor.ghost == 'on'") is False

        assert [record.levelno for record in caplog.records] == [logging.DEBUG, logging.DEBUG]
        assert "sensor.dead is 'unavailable', which is not a number" in caplog.text
        assert "sensor.ghost does not exist" in caplog.text

    def test_usable_expression_logs_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        """Nothing is logged for an ordinary true or false result."""
        with caplog.at_level(logging.DEBUG, logger="haanim.engine.expression_eval"):
            value_of("sensor.temperature > 25")
            value_of("sensor.temperature > 99")
        assert caplog.records == []


class TestDesignExamples:
    """Every example of the Expression Syntax section."""

    def test_type_handling(self) -> None:
        """The Type Handling examples."""
        check_table(
            [
                ("sensor.temperature > 20", True),
                ('person.john == "home"', True),
                ("binary_sensor.motion", False),
                ("binary_sensor.door", True),
                ("15 <= sensor.outdoor_temp <= 25", True),
                ("sensor.indoor > sensor.outdoor", True),
            ]
        )

    def test_entity_access(self) -> None:
        """The Entity Access examples, used in comparisons."""
        check_table(
            [
                ("light.living_room == 'on'", True),
                ("light.living_room['brightness'] == 200", True),
                ("sensor.weather['temperature'] == 12.5", True),
            ]
        )

    def test_operator_examples(self) -> None:
        """The Operators examples."""
        check_table(
            [
                ('person.john == "home"', True),
                ('person.john != "home"', False),
                ("sensor.temperature > 10", True),
                ("sensor.temperature < 50", True),
                ("sensor.temperature >= 20", True),
                ("sensor.temperature <= 80", True),
                ("person.john in ['home', 'work']", True),
                ("person.john not in ['home', 'work']", False),
                ("(binary_sensor.motion or binary_sensor.door) and light.living_room", True),
            ]
        )


class TestResult:
    """What evaluation returns."""

    def test_result_and_referenced_entities(self) -> None:
        """evaluate_expression returns the value and the entities the expression refers to."""
        result, entities = evaluate_expression(
            "sensor.temperature > 25 and light.living_room == 'on'", lookup
        )
        assert result is True
        assert entities == {"sensor.temperature", "light.living_room"}

    def test_entities_are_known_without_evaluating(self) -> None:
        """The referenced entities come from the text, including those in attributes and calls."""
        expression = parse_expression(
            "max(sensor.a, sensor.b) > light.c['brightness'] or 'x' in sensor.d.upper() or sensor.a in [sensor.e]"
        )
        assert expression.entities == {"sensor.a", "sensor.b", "light.c", "sensor.d", "sensor.e"}

    def test_entities_of_an_unusable_expression(self) -> None:
        """The entities are reported also when the expression is false for an unusable value."""
        evaluation = parse_expression("sensor.ghost > 5 or sensor.zero < 3").evaluate(lookup)
        assert evaluation == Evaluation(
            False, frozenset({"sensor.ghost", "sensor.zero"}), "sensor.ghost does not exist"
        )

    def test_expression_without_entities(self) -> None:
        """A constant expression is allowed and refers to nothing."""
        assert evaluate_expression("1 + 1 == 2", lookup) == (True, frozenset())

    def test_result_is_always_a_boolean(self) -> None:
        """Whatever the expression computes, the result is True or False."""
        for source in ("sensor.count", "sensor.count + 1", "sensor.status.upper()", "sensor.csv.split(',')"):
            assert type(parse_expression(source).evaluate(lookup).result) is bool

    def test_parsing_is_cached(self) -> None:
        """The same text gives the same parsed expression."""
        assert parse_expression("sensor.a > 1") is parse_expression("sensor.a > 1")
        assert repr(parse_expression("sensor.a > 1")) == "Expression('sensor.a > 1')"

    def test_surrounding_whitespace_is_ignored(self) -> None:
        """Leading and trailing blanks do not matter."""
        assert value_of("   sensor.temperature > 25  ") is True

    def test_evaluation_is_pure(self) -> None:
        """Only the lookup is consulted, once per reference, and nothing is written."""
        asked: list[str] = []

        def recording(entity_id: str) -> SimpleNamespace | None:
            asked.append(entity_id)
            return STATES.get(entity_id)

        before = {entity_id: (found.state, dict(found.attributes)) for entity_id, found in STATES.items()}
        parse_expression("sensor.indoor > sensor.outdoor and sensor.indoor < 30").evaluate(recording)

        assert asked == ["sensor.indoor", "sensor.outdoor", "sensor.indoor"]
        assert before == {
            entity_id: (found.state, dict(found.attributes)) for entity_id, found in STATES.items()
        }

    def test_module_imports_nothing_of_the_host(self) -> None:
        """The evaluator depends on the standard library, the engine's errors and its operator table only."""
        tree = ast.parse(Path(expression_eval.__file__).read_text(encoding="utf-8"))
        imported = {
            node.module if isinstance(node, ast.ImportFrom) else alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert {name for name in imported if name and name.startswith("haanim")} == {
            "haanim.engine",
            "haanim.engine.errors",
        }
        assert not any(name and name.startswith("homeassistant") for name in imported)


INVALID = {
    "empty": "",
    "incomplete": "sensor.a ==",
    "unbalanced": "(sensor.a > 1",
    "assignment": "sensor.a = 1",
    "two expressions": "sensor.a > 1; sensor.b > 2",
    "bare name": "temperature > 25",
    "bare word on": "light.kitchen == on",
    "attribute with a dot": "light.kitchen.brightness > 100",
    "method not called": "sensor.status.upper == 'X'",
    "unknown function": "eval('1')",
    "unknown method": "sensor.status.format() == 'x'",
    "call of a call": "len(sensor.a)() == 1",
    "keyword argument": "round(sensor.a, ndigits=1) == 1",
    "power": "sensor.a ** 2 > 4",
    "bitwise": "sensor.a | sensor.b",
    "is": "sensor.a is True",
    "None": "sensor.a == None",
    "bytes": "sensor.a == b'x'",
    "lambda": "lambda: sensor.a",
    "conditional": "sensor.a if sensor.b else sensor.c",
    "comprehension": "[x for x in sensor.a]",
    "f-string": "f'{sensor.a}' == '1'",
    "dict": "sensor.a in {'a': 1}",
    "slice": "sensor.a[1:2] == 'x'",
    "walrus": "(x := sensor.a) > 1",
    "starred": "max(*sensor.a) > 1",
    "bitwise not": "~sensor.a > 1",
    "import": "__import__('os')",
}


class TestParseErrors:
    """Text that is not a state expression raises AutomationSyntaxError when parsed."""

    @pytest.mark.parametrize("source", INVALID.values(), ids=INVALID.keys())
    def test_invalid_expression(self, source: str) -> None:
        """Parsing fails, naming the expression; nothing is evaluated."""
        with pytest.raises(AutomationSyntaxError) as exc_info:
            Expression(source)
        assert f"Invalid state expression '{source}'" in str(exc_info.value)

    def test_messages_say_what_to_write_instead(self) -> None:
        """The common mistakes get a hint."""
        cases = {
            "temperature > 25": "'temperature' is not an entity; an entity is written domain.name",
            "light.kitchen.brightness > 1": "'.brightness' is not available here; attributes use ['name']",
            "sensor.a.upper == 'X'": "'.upper' is not available here; a method must be called",
            "eval('1')": "the function eval() is not available",
            "sensor.a.format()": "the method .format() is not available",
            "sensor.a == None": "the literal None is not available",
            "sensor.a ** 2 > 1": "the operator Pow is not available",
        }
        for source, message in cases.items():
            with pytest.raises(AutomationSyntaxError) as exc_info:
                Expression(source)
            assert message in str(exc_info.value), source

    def test_evaluate_expression_raises_for_invalid_text(self) -> None:
        """The one-call form reports the same error."""
        with pytest.raises(AutomationSyntaxError):
            evaluate_expression("sensor.a ==", lookup)

    def test_error_has_the_column(self) -> None:
        """The error carries where in the expression the problem is."""
        with pytest.raises(AutomationSyntaxError) as exc_info:
            Expression("sensor.a > 1 and oops")
        assert exc_info.value.col_offset == 17


class TestValidationAtStart:
    """State expressions are checked when the automation starts."""

    @staticmethod
    def source(decorator: str) -> str:
        """An automation with one trigger."""
        return f"from haanim import on_state, on_time\n\n{decorator}\ndef react():\n    pass\n"

    @pytest.mark.parametrize(
        ("decorator", "expression"),
        [
            ("@on_state('sensor.a ==')", "sensor.a =="),
            ("@on_state('light.kitchen == on')", "light.kitchen == on"),
            ("@on_state(\"sensor.a == 'on'\", when='temperature > 5')", "temperature > 5"),
            (
                "@on_state(\"sensor.a == 'on'\", when_not='sensor.b.brightness > 5')",
                "sensor.b.brightness > 5",
            ),
            ("@on_time('09:00', when='sensor.a ==')", "sensor.a =="),
        ],
    )
    async def test_invalid_expression_is_a_start_error(
        self, world: World, decorator: str, expression: str
    ) -> None:
        """The automation ends in error, naming the function and the expression."""
        automation = world.add("lights", self.source(decorator))
        assert await automation.load()
        assert not await automation.start()

        assert automation.message is not None
        assert automation.message.startswith(f"'react': Invalid state expression '{expression}'")
        assert world.triggers.registered == []

    @pytest.mark.parametrize(
        "decorator",
        [
            "@on_state('sensor.temperature > 25')",
            "@on_state(\"person.john == 'home'\", when='binary_sensor.motion', when_not=\"sensor.x in ['a', 'b']\")",
            "@on_time('09:00', when=\"light.kitchen['brightness'] > 100\")",
        ],
    )
    async def test_valid_expression_starts(self, world: World, decorator: str) -> None:
        """Valid expressions do not keep an automation from starting."""
        automation = world.add("lights", self.source(decorator))
        assert await automation.load()
        assert await automation.start(), automation.message

    async def test_time_expression_is_not_checked_as_a_state_expression(self, world: World) -> None:
        """Only state expressions go through this parser."""
        automation = world.add("lights", self.source("@on_time('sunrise + 30 minutes')"))
        assert await automation.load()
        assert await automation.start(), automation.message
