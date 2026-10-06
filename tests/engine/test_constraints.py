"""Tests for constraints: when a trigger that is due may fire.

See "Constraints" in the design.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from haanim.engine.constraints import Constraints
from haanim.engine.lifecycle import AutomationState
from haanim.testing import FakeSunProvider
from tests.engine.test_time_schedule import NEW_YORK, TOKYO, PartialSun, TimeWorld, at

SUN = FakeSunProvider(sunrise="07:00", sunset="19:00")


def no_states(_: str) -> None:
    """A lookup with no entities."""
    return None


def allowed(
    constraints: dict[str, Any], *moments: str, sun: Any = SUN, states: Any = no_states
) -> list[bool]:
    """Return, for each moment in New York, whether the constraints allow a trigger to fire."""
    parsed = Constraints.parse(constraints)
    return [parsed.allows(at(moment), states, sun) for moment in moments]


class TestNoConstraints:
    """Without constraints a trigger always fires."""

    def test_empty(self) -> None:
        """No arguments, or only None, is no constraint."""
        assert Constraints.parse({}).is_empty
        assert Constraints.parse({"start_time": None, "when": None}).is_empty
        assert allowed({}, "2025-01-06 03:00", "2025-07-04 23:59:59") == [True, True]

    def test_not_empty(self) -> None:
        """Any constraint makes it non-empty."""
        assert not Constraints.parse({"day_of_week": "monday"}).is_empty


class TestMissingBounds:
    """One test per row of the missing-bounds table."""

    def test_missing_start_time(self) -> None:
        """00:00:00 to end_time."""
        assert allowed(
            {"end_time": "18:00"},
            "2025-01-06 00:00:00",
            "2025-01-06 17:59:59",
            "2025-01-06 18:00:00",
            "2025-01-06 23:00",
        ) == [True, True, False, False]

    def test_missing_end_time(self) -> None:
        """start_time to 00:00:00."""
        assert allowed(
            {"start_time": "08:00"},
            "2025-01-06 07:59:59",
            "2025-01-06 08:00:00",
            "2025-01-06 23:59:59",
            "2025-01-07 00:00",
        ) == [False, True, True, False]

    def test_missing_start_date(self) -> None:
        """January 1st to end_date."""
        assert allowed(
            {"end_date": "May 19"},
            "2025-01-01 00:00",
            "2025-05-18 23:59",
            "2025-05-19 00:00",
            "2025-12-31 12:00",
        ) == [True, True, False, False]

    def test_missing_end_date(self) -> None:
        """start_date to January 1st of the next year."""
        assert allowed(
            {"start_date": "April 1"},
            "2025-03-31 23:59",
            "2025-04-01 00:00",
            "2025-12-31 23:59",
            "2026-01-01 00:00",
        ) == [False, True, True, False]


class TestRangeRules:
    """One test or more per Range rules bullet."""

    def test_start_is_inclusive_and_end_is_exclusive(self) -> None:
        """08:00 to 18:00 allows 08:00:00 up to but not including 18:00:00."""
        assert allowed(
            {"start_time": "08:00", "end_time": "18:00"},
            "2025-01-06 07:59:59",
            "2025-01-06 08:00:00",
            "2025-01-06 12:00:00",
            "2025-01-06 17:59:59",
            "2025-01-06 18:00:00",
        ) == [False, True, True, True, False]

    def test_date_start_is_inclusive_and_end_is_exclusive(self) -> None:
        """April 1 to May 19 allows the whole of April 1 and nothing of May 19."""
        assert allowed(
            {"start_date": "April 1", "end_date": "May 19"},
            "2025-03-31 23:59:59",
            "2025-04-01 00:00:00",
            "2025-05-18 23:59:59",
            "2025-05-19 00:00:00",
        ) == [False, True, True, False]

    def test_time_range_wraps_around_midnight(self) -> None:
        """22:00 to 06:00 allows 22:00 through midnight to 06:00."""
        assert allowed(
            {"start_time": "22:00", "end_time": "06:00"},
            "2025-01-06 21:59:59",
            "2025-01-06 22:00:00",
            "2025-01-06 23:59:59",
            "2025-01-07 00:00:00",
            "2025-01-07 05:59:59",
            "2025-01-07 06:00:00",
            "2025-01-07 12:00:00",
        ) == [False, True, True, True, True, False, False]

    def test_date_range_wraps_around_new_year(self) -> None:
        """November 1 to March 1 allows November through February."""
        assert allowed(
            {"start_date": "November 1", "end_date": "March 1"},
            "2025-10-31 12:00",
            "2025-11-01 00:00",
            "2025-12-31 23:59",
            "2026-01-01 00:00",
            "2026-02-28 23:59",
            "2026-03-01 00:00",
            "2026-07-01 12:00",
        ) == [False, True, True, True, True, False, False]

    def test_day_of_week_with_a_wrapping_range_is_the_day_the_range_started(self) -> None:
        """Friday 22:00 to 06:00 includes Saturday morning and excludes Friday morning."""
        # 10 January 2025 is a Friday
        constraints = {"start_time": "22:00", "end_time": "06:00", "day_of_week": "friday"}
        assert allowed(
            constraints,
            "2025-01-10 03:00",  # Friday morning: Thursday's range
            "2025-01-10 22:00",  # Friday evening
            "2025-01-11 05:59",  # Saturday morning: Friday's range
            "2025-01-11 22:00",  # Saturday evening
        ) == [False, True, True, False]

    def test_equal_start_and_end_time_is_an_error(self) -> None:
        """An empty time range cannot be given."""
        with pytest.raises(ValueError, match="start_time '08:00' and end_time '08:00' are the same time"):
            Constraints.parse({"start_time": "08:00", "end_time": "08:00"})
        with pytest.raises(ValueError, match="are the same time: the range is empty"):
            Constraints.parse({"start_time": "noon", "end_time": "12:00:00"})
        with pytest.raises(ValueError, match="are the same time"):
            Constraints.parse({"start_time": "11:30 + 30 minutes", "end_time": "12pm"})

    def test_equal_start_and_end_date_is_an_error(self) -> None:
        """An empty date range cannot be given."""
        with pytest.raises(ValueError, match="start_date 'April 1' and end_date '04-01' are the same date"):
            Constraints.parse({"start_date": "April 1", "end_date": "04-01"})
        with pytest.raises(ValueError, match="are the same date: the range is empty"):
            Constraints.parse({"start_date": "2025-04-01", "end_date": "2025-04-01"})

    def test_all_constraints_must_hold(self) -> None:
        """Time, date, day and state constraints are combined with AND."""
        states = {"person.john": SimpleNamespace(state="home", attributes={})}.get
        constraints = {
            "start_time": "08:00",
            "end_time": "18:00",
            "start_date": "April 1",
            "end_date": "May 19",
            "day_of_week": "weekdays",
            "when": "person.john == 'home'",
        }
        # 7 April 2025 is a Monday
        assert allowed(constraints, "2025-04-07 09:00", states=states) == [True]
        assert allowed(constraints, "2025-04-07 07:00", states=states) == [False]  # time
        assert allowed(constraints, "2025-06-02 09:00", states=states) == [False]  # date
        assert allowed(constraints, "2025-04-06 09:00", states=states) == [False]  # Sunday
        assert allowed(constraints, "2025-04-07 09:00") == [False]  # state

    def test_evaluated_in_the_hosts_time_zone(self) -> None:
        """The same instant is inside the range in one zone and outside in another."""
        parsed = Constraints.parse({"start_time": "08:00", "end_time": "18:00"})
        instant = at("2025-01-06 09:00")
        assert parsed.allows(instant, no_states, SUN) is True
        # 09:00 in New York is 23:00 in Tokyo
        assert parsed.allows(instant.astimezone(TOKYO), no_states, SUN) is False


class TestTimeBounds:
    """start_time and end_time take the time expressions of the time trigger."""

    def test_formats(self) -> None:
        """Clock times, am and pm, noon and midnight."""
        assert allowed(
            {"start_time": "9am", "end_time": "5:30pm"}, "2025-01-06 09:00", "2025-01-06 17:30"
        ) == [
            True,
            False,
        ]
        assert allowed({"start_time": "noon"}, "2025-01-06 11:59", "2025-01-06 12:00") == [False, True]
        assert allowed({"end_time": "midnight + 6 hours"}, "2025-01-06 05:59", "2025-01-06 06:00") == [
            True,
            False,
        ]

    def test_sunrise_and_sunset(self) -> None:
        """A bound can be the sun's time of the day, with an offset."""
        daylight = {"start_time": "sunrise", "end_time": "sunset"}
        assert allowed(
            daylight, "2025-01-06 06:59", "2025-01-06 07:00", "2025-01-06 18:59", "2025-01-06 19:00"
        ) == [
            False,
            True,
            True,
            False,
        ]
        night = {"start_time": "sunset + 30 minutes", "end_time": "sunrise - 30 minutes"}
        assert allowed(
            night, "2025-01-06 19:29", "2025-01-06 19:30", "2025-01-07 06:29", "2025-01-07 06:30"
        ) == [
            False,
            True,
            True,
            False,
        ]

    def test_no_sunrise_blocks(self) -> None:
        """On a day without the sun event a bound needs, the trigger does not fire."""
        sun = PartialSun({date(2025, 1, 7)})
        assert allowed({"start_time": "sunrise"}, "2025-01-06 12:00", "2025-01-07 12:00", sun=sun) == [
            True,
            False,
        ]

    def test_a_date_is_not_a_time(self) -> None:
        """start_time with a date is rejected, naming the argument."""
        with pytest.raises(ValueError, match="start_time: '2025-01-01 08:00' has a date"):
            Constraints.parse({"start_time": "2025-01-01 08:00"})
        with pytest.raises(ValueError, match="end_time: '25:00' is not a date and time expression"):
            Constraints.parse({"end_time": "25:00"})


class TestDateBounds:
    """start_date and end_date take the date expressions of the time trigger."""

    def test_short_dates_recur_every_year(self) -> None:
        """The design's example: April 1 to May 19, every year."""
        constraints = {"start_date": "April 1", "end_date": "May 19"}
        assert allowed(constraints, "2025-04-15 12:00", "2026-04-15 12:00", "2031-05-18 12:00") == [
            True,
            True,
            True,
        ]

    def test_formats(self) -> None:
        """MM-DD, Month Day and Day Month."""
        for start, end in (("04-01", "05-19"), ("April 1st", "May 19th"), ("1 April", "19 May")):
            assert allowed(
                {"start_date": start, "end_date": end}, "2025-04-15 12:00", "2025-06-01 12:00"
            ) == [
                True,
                False,
            ]

    def test_full_dates_are_one_period(self) -> None:
        """Dates with a year name one range, which does not recur."""
        constraints = {"start_date": "2025-04-01", "end_date": "2025-05-19"}
        assert allowed(constraints, "2025-04-15 12:00", "2026-04-15 12:00", "2024-04-15 12:00") == [
            True,
            False,
            False,
        ]

    def test_full_date_missing_bound(self) -> None:
        """With a year, a missing bound is January 1st of that year or of the next."""
        assert allowed(
            {"start_date": "2025-04-01"}, "2025-03-31 12:00", "2025-12-31 12:00", "2026-01-01 12:00"
        ) == [
            False,
            True,
            False,
        ]
        assert allowed(
            {"end_date": "2025-04-01"}, "2024-12-31 12:00", "2025-01-01 12:00", "2025-04-01 12:00"
        ) == [
            False,
            True,
            False,
        ]

    def test_invalid_dates(self) -> None:
        """A bound that is not a date is rejected, naming the argument."""
        with pytest.raises(ValueError, match="start_date: 'April 1 09:00' is not a date"):
            Constraints.parse({"start_date": "April 1 09:00"})
        with pytest.raises(ValueError, match="end_date: 'February 30' is not a date that exists"):
            Constraints.parse({"end_date": "February 30"})
        with pytest.raises(ValueError, match="give the year for both dates or for neither"):
            Constraints.parse({"start_date": "April 1", "end_date": "2025-05-19"})
        with pytest.raises(ValueError, match="the start is after the end"):
            Constraints.parse({"start_date": "2025-05-19", "end_date": "2025-04-01"})

    def test_date_with_a_wrapping_time_range(self) -> None:
        """The date range is matched against the day the time range started, like day_of_week."""
        constraints = {"start_time": "22:00", "end_time": "06:00", "end_date": "May 19"}
        assert allowed(constraints, "2025-05-18 23:00", "2025-05-19 05:00", "2025-05-19 23:00") == [
            True,
            True,
            False,
        ]


class TestDayOfWeek:
    """day_of_week as a constraint does the job it does on the time trigger."""

    def test_formats(self) -> None:
        """Groups, names, and indexes with 0 for Sunday."""
        # 6 January 2025 is a Monday, 11 January a Saturday, 12 January a Sunday
        assert allowed({"day_of_week": "weekdays"}, "2025-01-06 12:00", "2025-01-11 12:00") == [True, False]
        assert allowed({"day_of_week": "weekends"}, "2025-01-06 12:00", "2025-01-11 12:00") == [False, True]
        assert allowed({"day_of_week": "monday, friday"}, "2025-01-06 12:00", "2025-01-07 12:00") == [
            True,
            False,
        ]
        assert allowed(
            {"day_of_week": "0,1,2"}, "2025-01-12 12:00", "2025-01-06 12:00", "2025-01-08 12:00"
        ) == [
            True,
            True,
            False,
        ]
        assert allowed({"day_of_week": 0}, "2025-01-12 12:00", "2025-01-13 12:00") == [True, False]

    def test_invalid(self) -> None:
        """A value that is not a day is rejected."""
        with pytest.raises(ValueError, match="day_of_week: 'funday' is not a day of the week"):
            Constraints.parse({"day_of_week": "funday"})


def states_with(**entities: str) -> Any:
    """Build a state lookup from ``domain__name="state"`` keyword arguments."""
    found = {
        name.replace("__", "."): SimpleNamespace(state=state, attributes={})
        for name, state in entities.items()
    }
    return found.get


class TestStateConstraints:
    """when must be true and when_not must be false."""

    def test_when(self) -> None:
        """The design's example: only when John is home."""
        constraints = {"when": "person.john == 'home'"}
        assert allowed(constraints, "2025-01-06 07:00", states=states_with(person__john="home")) == [True]
        assert allowed(constraints, "2025-01-06 07:00", states=states_with(person__john="work")) == [False]

    def test_when_not(self) -> None:
        """The design's example: not during sleep mode."""
        constraints = {"when_not": "input_boolean.sleep_mode == 'on'"}
        assert allowed(
            constraints, "2025-01-06 07:00", states=states_with(input_boolean__sleep_mode="off")
        ) == [True]
        assert allowed(
            constraints, "2025-01-06 07:00", states=states_with(input_boolean__sleep_mode="on")
        ) == [False]

    def test_both(self) -> None:
        """when and when_not together."""
        constraints = {"when": "person.john == 'home'", "when_not": "binary_sensor.guests"}
        home = {"person__john": "home"}
        assert allowed(
            constraints, "2025-01-06 07:00", states=states_with(binary_sensor__guests="off", **home)
        ) == [True]
        assert allowed(
            constraints, "2025-01-06 07:00", states=states_with(binary_sensor__guests="on", **home)
        ) == [False]

    def test_when_with_an_unusable_value_blocks(self) -> None:
        """A missing or unavailable entity makes when false."""
        constraints = {"when": "sensor.temperature > 25"}
        assert allowed(constraints, "2025-01-06 07:00") == [False]
        assert allowed(
            constraints, "2025-01-06 07:00", states=states_with(sensor__temperature="unavailable")
        ) == [False]
        assert allowed(constraints, "2025-01-06 07:00", states=states_with(sensor__temperature="30")) == [
            True
        ]

    def test_when_not_with_an_unusable_value_blocks(self) -> None:
        """For when_not, an unusable value also blocks the trigger."""
        constraints = {"when_not": "sensor.temperature > 25"}
        assert allowed(constraints, "2025-01-06 07:00") == [False]
        assert allowed(
            constraints, "2025-01-06 07:00", states=states_with(sensor__temperature="unavailable")
        ) == [False]
        assert allowed(
            constraints, "2025-01-06 07:00", states=states_with(sensor__temperature="unknown")
        ) == [False]
        assert allowed(constraints, "2025-01-06 07:00", states=states_with(sensor__temperature="20")) == [
            True
        ]
        assert allowed(constraints, "2025-01-06 07:00", states=states_with(sensor__temperature="30")) == [
            False
        ]

    def test_explicit_test_for_unavailability(self) -> None:
        """Comparing with 'unavailable' is usable, so it can be a constraint."""
        constraints = {"when_not": "sensor.temperature == 'unavailable'"}
        assert allowed(
            constraints, "2025-01-06 07:00", states=states_with(sensor__temperature="unavailable")
        ) == [False]
        assert allowed(constraints, "2025-01-06 07:00", states=states_with(sensor__temperature="21")) == [
            True
        ]

    def test_invalid_expression(self) -> None:
        """An expression that cannot be parsed is rejected, naming the argument."""
        with pytest.raises(ValueError, match="when: Invalid state expression 'sensor.a =='"):
            Constraints.parse({"when": "sensor.a =="})
        with pytest.raises(ValueError, match="when_not: Invalid state expression"):
            Constraints.parse({"when_not": "temperature > 5"})


def source(*decorators: str, imports: str = "on_time, on_interval, on_cron, on_state, on_event") -> str:
    """An automation with one function carrying the given trigger decorators."""
    lines = "\n".join(decorators)
    return f"from haanim import {imports}\n\n{lines}\ndef task(event):\n    log.append(event)\n"


class TestConstraintsOnTriggers:
    """Constraints are given to trigger decorators and evaluated when the trigger fires."""

    async def test_business_hours_example(self, tmp_path: Path) -> None:
        """The design's example: 09:00, between 08:00 and 18:00, on weekdays."""
        world = TimeWorld(tmp_path, at("2025-01-09 12:00"))  # a Thursday
        await world.started(
            "office",
            source('@on_time("09:00", start_time="08:00", end_time="18:00", day_of_week="weekdays")'),
        )
        await world.clock.advance(days=5)
        assert world.fired() == ["2025-01-10 09:00:00", "2025-01-13 09:00:00", "2025-01-14 09:00:00"]

    async def test_seasonal_example(self, tmp_path: Path) -> None:
        """The design's example: only between April 1 and May 19."""
        world = TimeWorld(tmp_path, at("2025-03-30 12:00"))
        await world.started("season", source('@on_time("09:00", start_date="April 1", end_date="May 19")'))
        await world.clock.advance(days=3)
        assert world.fired() == ["2025-04-01 09:00:00", "2025-04-02 09:00:00"]

    async def test_interval_inside_a_time_range(self, tmp_path: Path) -> None:
        """An interval trigger fires only inside its range, and its count skips the blocked fires."""
        world = TimeWorld(tmp_path, at("2025-01-06 07:30"))
        await world.started(
            "ticker",
            "from haanim import on_interval\n\n@on_interval('00:30:00', start_time='08:00', end_time='09:30')\n"
            "def task(event):\n    log.append((event.execution_count, event.call_time.strftime('%H:%M')))\n",
        )
        await world.clock.advance(hours=4)
        assert world.log == [(1, "08:00"), (2, "08:30"), (3, "09:00")]

    async def test_cron_with_when(self, tmp_path: Path) -> None:
        """A cron trigger fires only while its when expression holds."""
        world = TimeWorld(tmp_path, at("2025-01-06 07:30"))
        world.host.states.set_state("person.john", "work")
        await world.started("jobs", source('@on_cron("0 * * * *", when="person.john == \'home\'")'))
        await world.clock.advance(hours=2)
        assert world.log == []

        world.host.states.set_state("person.john", "home")
        await world.clock.advance(hours=1)
        assert world.fired() == ["2025-01-06 10:00:00"]

    async def test_when_not_blocks_while_the_entity_is_unavailable(self, tmp_path: Path) -> None:
        """An unusable value in when_not blocks the trigger."""
        world = TimeWorld(tmp_path, at("2025-01-06 07:30"))
        await world.started(
            "jobs", source('@on_cron("0 * * * *", when_not="input_boolean.sleep_mode == \'on\'")')
        )
        await world.clock.advance(hours=1)
        assert world.log == []  # the entity does not exist

        world.host.states.set_state("input_boolean.sleep_mode", "off")
        await world.clock.advance(hours=1)
        world.host.states.set_state("input_boolean.sleep_mode", "on")
        await world.clock.advance(hours=1)
        assert world.fired() == ["2025-01-06 09:00:00"]

    async def test_stacked_triggers_have_their_own_constraints(self, tmp_path: Path) -> None:
        """With stacked triggers, each decorator's constraints apply to that trigger only."""
        world = TimeWorld(tmp_path, at("2025-01-06 00:00"))
        await world.started(
            "stacked",
            source(
                '@on_time("09:00", day_of_week="monday")',
                '@on_time("15:00", day_of_week="tuesday")',
                '@on_time("21:00", start_time="20:00", end_time="22:00")',
            ),
        )
        await world.clock.advance(days=2)
        assert sorted(world.fired()) == [
            "2025-01-06 09:00:00",
            "2025-01-06 21:00:00",
            "2025-01-07 15:00:00",
            "2025-01-07 21:00:00",
        ]

    async def test_stacked_triggers_of_different_kinds(self, tmp_path: Path) -> None:
        """A constraint on one decorator does not restrict a trigger of another kind on the same function."""
        world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        world.host.states.set_state("person.john", "work")
        await world.started(
            "stacked",
            source('@on_time("09:00", when="person.john == \'home\'")', '@on_cron("30 9 * * *")'),
        )
        await world.clock.advance(hours=2)
        assert [type(event).__name__ for event in world.log] == ["CronEvent"]

    async def test_not_evaluated_on_a_direct_call(self, tmp_path: Path) -> None:
        """Calling the function directly ignores the constraints of its triggers."""
        world = TimeWorld(tmp_path, at("2025-01-06 03:00"))
        automation = await world.started(
            "office",
            source(
                '@on_time("09:00", start_time="08:00", end_time="18:00", when="person.nobody == \'home\'")'
            ),
        )
        await automation.call_action("task")
        assert [type(event).__name__ for event in world.log] == ["ManualEvent"]

    async def test_blocked_fire_is_not_a_failure(self, tmp_path: Path) -> None:
        """A trigger that a constraint blocks records nothing."""
        world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        automation = await world.started("office", source('@on_time("09:00", day_of_week="sunday")'))
        await world.clock.advance(days=1)
        assert world.log == []
        assert automation.last_error is None
        assert automation.state is AutomationState.ON


INVALID = [
    (
        '@on_time("09:00", start_time="08:00", end_time="08:00")',
        "@on_time: start_time '08:00' and end_time '08:00' are the same time: the range is empty",
    ),
    (
        '@on_interval(60, start_date="April 1", end_date="April 1")',
        "@on_interval: start_date 'April 1' and end_date 'April 1' are the same date: the range is empty",
    ),
    (
        '@on_cron("0 9 * * *", start_time="25:00")',
        "@on_cron: start_time: '25:00' is not a date and time expression",
    ),
    ('@on_state("sensor.a > 1", end_date="someday")', "@on_state: end_date: 'someday' is not a date"),
    (
        '@on_event("doorbell", day_of_week="funday")',
        "@on_event: day_of_week: 'funday' is not a day of the week",
    ),
    (
        '@on_time("09:00", start_date="April 1", end_date="2025-05-19")',
        "@on_time: start_date 'April 1' and end_date '2025-05-19': give the year for both dates or for neither",
    ),
    (
        '@on_time("09:00", start_time="2025-01-01 08:00")',
        "@on_time: start_time: '2025-01-01 08:00' has a date",
    ),
]


class TestInvalidConstraints:
    """A constraint that cannot be read, or an empty range, is an error when the automation starts."""

    @pytest.mark.parametrize(("decorator", "message"), INVALID, ids=[decorator for decorator, _ in INVALID])
    async def test_start_error(self, tmp_path: Path, decorator: str, message: str) -> None:
        """The message names the decorator, the argument and the offending text."""
        world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        automation = world.add("broken", source(decorator))
        assert await automation.load()
        assert not await automation.start()

        assert automation.state is AutomationState.ERROR
        assert automation.message is not None
        assert automation.message.startswith(f"ValueError: {message}")

    async def test_every_trigger_decorator_takes_constraints(self, tmp_path: Path) -> None:
        """The constraint arguments are accepted by all five trigger decorators."""
        constraints = (
            'start_time="08:00", end_time="18:00", start_date="April 1", end_date="May 19", '
            'day_of_week="weekdays", when="person.john == \'home\'", when_not="binary_sensor.guests"'
        )
        world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        automation = world.add(
            "all",
            source(
                f'@on_time("09:00", {constraints})',
                f"@on_interval(60, {constraints})",
                f'@on_cron("0 9 * * *", {constraints})',
                f'@on_event("doorbell", {constraints})',
                f'@on_state("sensor.a > 1", {constraints})',
            ),
        )
        assert await automation.load()
        assert await automation.start(), automation.message
        assert len(automation.context.get_triggers()) == 5

    async def test_action_takes_no_constraints(self, tmp_path: Path) -> None:
        """@action has no constraint arguments."""
        world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        automation = world.add(
            "broken", "from haanim import action\n\n@action(start_time='08:00')\ndef task(event):\n    pass\n"
        )
        assert await automation.load()
        assert not await automation.start()
        assert automation.message is not None and "start_time" in automation.message


def test_new_york_is_the_zone_of_the_helper() -> None:
    """The moments of these tests are New York wall-clock times."""
    assert at("2025-01-06 09:00").tzinfo is NEW_YORK
    assert isinstance(at("2025-01-06 09:00"), datetime)
