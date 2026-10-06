"""Tests for when a date and time expression is due, and for the time trigger.

See "Scheduling Rules" under "Time Trigger" in the design. Each rule has a test
class named after it.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from haanim.engine.action_dispatcher import ActionDispatcher
from haanim.engine.action_pool import ActionWorkerPool
from haanim.engine.automation_status import AutomationStatusManager
from haanim.engine.lifecycle import Automation, AutomationState
from haanim.engine.time_schedule import TimeSchedule, is_past_one_time, local_instant, next_fire
from haanim.engine.triggers.manager import TriggerManager
from haanim.events import ManualEvent, TimeEvent
from haanim.testing import FakeClock, FakeSunProvider, LocalFileSystem, make_host
from tests.engine.test_lifecycle import World

UTC = timezone.utc
NEW_YORK = ZoneInfo("America/New_York")
BERLIN = ZoneInfo("Europe/Berlin")
TOKYO = ZoneInfo("Asia/Tokyo")
SUN = FakeSunProvider(sunrise="07:00", sunset="19:00")


def at(text: str, zone: Any = NEW_YORK) -> datetime:
    """Build an aware datetime from ``YYYY-MM-DD HH:MM[:SS]`` in a zone."""
    return datetime.fromisoformat(text).replace(tzinfo=zone)


def fires(
    expression: str,
    start: datetime,
    count: int,
    *,
    sun: Any = SUN,
    day_of_week: str | int | None = None,
    day_of_month: str | int | None = None,
) -> list[str]:
    """Return the next ``count`` fires of a schedule after ``start``, as local wall-clock text."""
    schedule = TimeSchedule.parse(expression, day_of_week, day_of_month)
    result: list[str] = []
    instant: datetime | None = start
    for _ in range(count):
        assert instant is not None
        instant = next_fire(schedule, instant, sun)
        if instant is None:
            break
        result.append(instant.strftime("%Y-%m-%d %H:%M:%S"))
    return result


# (expression, after, expected next fire) in New York; None for no fire
NEXT_FIRE: list[tuple[str, str, str | None]] = [
    # A time alone fires every day
    ("09:00", "2025-01-06 08:00", "2025-01-06 09:00:00"),
    ("09:00", "2025-01-06 09:00", "2025-01-07 09:00:00"),
    ("09:00", "2025-01-06 09:00:01", "2025-01-07 09:00:00"),
    ("09:00", "2025-01-06 08:59:59", "2025-01-06 09:00:00"),
    ("09:00:30", "2025-01-06 09:00", "2025-01-06 09:00:30"),
    ("5:47pm", "2025-01-06 12:00", "2025-01-06 17:47:00"),
    ("noon", "2025-01-06 12:00", "2025-01-07 12:00:00"),
    ("midnight", "2025-01-06 12:00", "2025-01-07 00:00:00"),
    ("23:59:59", "2025-12-31 23:59:59", "2026-01-01 23:59:59"),
    # Offsets
    ("noon + 30 minutes", "2025-01-06 12:00", "2025-01-06 12:30:00"),
    ("noon + 30 minutes", "2025-01-06 12:30", "2025-01-07 12:30:00"),
    ("09:00 - 45 seconds", "2025-01-06 00:00", "2025-01-06 08:59:15"),
    # Sunrise and sunset (07:00 and 19:00 here)
    ("sunrise", "2025-01-06 06:00", "2025-01-06 07:00:00"),
    ("sunrise", "2025-01-06 07:00", "2025-01-07 07:00:00"),
    ("sunset", "2025-01-06 12:00", "2025-01-06 19:00:00"),
    ("sunset + 30 minutes", "2025-01-06 12:00", "2025-01-06 19:30:00"),
    ("sunrise - 15 minutes", "2025-01-06 12:00", "2025-01-07 06:45:00"),
    ("sunset - 90 minutes", "2025-01-06 12:00", "2025-01-06 17:30:00"),
    # A short date fires every year
    ("12-25", "2025-01-06 12:00", "2025-12-25 00:00:00"),
    ("December 25", "2025-12-25 00:00", "2026-12-25 00:00:00"),
    ("December 25 09:00", "2025-12-25 08:00", "2025-12-25 09:00:00"),
    ("January 1st noon", "2025-01-06 12:00", "2026-01-01 12:00:00"),
    ("December 25 sunset - 30 minutes", "2025-01-06 12:00", "2025-12-25 18:30:00"),
    # A full date fires once
    ("2025-12-25 09:00:00", "2025-01-06 12:00", "2025-12-25 09:00:00"),
    ("2025-12-25 09:00:00", "2025-12-25 08:59:59", "2025-12-25 09:00:00"),
    ("2025-12-25 09:00:00", "2025-12-25 09:00:00", None),
    ("2025-12-25", "2025-01-06 12:00", "2025-12-25 00:00:00"),
    ("2026-01-01 + 3 hours", "2025-01-06 12:00", "2026-01-01 03:00:00"),
    ("2024-12-25 09:00:00", "2025-01-06 12:00", None),
]


class TestNextFire:
    """The first fire after an instant."""

    @pytest.mark.parametrize(("expression", "after", "expected"), NEXT_FIRE)
    def test_table(self, expression: str, after: str, expected: str | None) -> None:
        """One row per kind of expression."""
        result = next_fire(TimeSchedule.parse(expression), at(after), SUN)
        assert (result.strftime("%Y-%m-%d %H:%M:%S") if result else None) == expected

    def test_strictly_after(self) -> None:
        """A fire at exactly the given instant is not returned again."""
        assert fires("09:00", at("2025-01-06 00:00"), 3) == [
            "2025-01-06 09:00:00",
            "2025-01-07 09:00:00",
            "2025-01-08 09:00:00",
        ]

    def test_result_is_in_the_zone_of_the_instant(self) -> None:
        """The fire is returned in the time zone it was asked in."""
        result = next_fire(TimeSchedule.parse("09:00"), at("2025-01-06 00:00", TOKYO), SUN)
        assert result is not None and result.tzinfo is TOKYO

    def test_needs_a_time_zone(self) -> None:
        """A naive datetime is rejected."""
        with pytest.raises(ValueError, match="timezone-aware"):
            next_fire(TimeSchedule.parse("09:00"), datetime(2025, 1, 6), SUN)

    def test_pure(self) -> None:
        """The same question has the same answer; nothing is remembered."""
        schedule = TimeSchedule.parse("sunset + 30 minutes", day_of_week="weekdays")
        answers = {next_fire(schedule, at("2025-01-06 12:00"), SUN) for _ in range(3)}
        assert len(answers) == 1

    def test_invalid_arguments_are_named(self) -> None:
        """A schedule cannot be built from text the parser rejects."""
        with pytest.raises(ValueError, match="'25:00' is not a time"):
            TimeSchedule.parse("25:00")
        with pytest.raises(ValueError, match="'funday' is not a day of the week"):
            TimeSchedule.parse("09:00", day_of_week="funday")
        with pytest.raises(ValueError, match="'32' is not a day of the month"):
            TimeSchedule.parse("09:00", day_of_month="32")


class TestTimeZone:
    """Rule: expressions are interpreted in the host's time zone."""

    def test_same_expression_different_zones(self) -> None:
        """09:00 is a different instant in New York, Berlin and Tokyo."""
        schedule = TimeSchedule.parse("09:00")
        start = datetime(2025, 1, 6, 0, 0, tzinfo=UTC)
        instants = {
            zone.key: next_fire(schedule, start.astimezone(zone), SUN) for zone in (NEW_YORK, BERLIN, TOKYO)
        }
        assert {
            key: value.astimezone(UTC).strftime("%d %H:%M") for key, value in instants.items() if value
        } == {
            "America/New_York": "06 14:00",
            "Europe/Berlin": "06 08:00",
            "Asia/Tokyo": "07 00:00",
        }

    def test_day_of_week_is_the_local_day(self) -> None:
        """Monday means Monday where the host is, whatever the day is in UTC."""
        # Monday 6 January, 08:00 in Tokyo is still Sunday in UTC
        result = next_fire(
            TimeSchedule.parse("08:00", day_of_week="monday"), at("2025-01-05 12:00", TOKYO), SUN
        )
        assert result is not None
        assert result.strftime("%A %H:%M") == "Monday 08:00"
        assert result.astimezone(UTC).strftime("%A") == "Sunday"

    def test_day_of_month_is_the_local_day(self) -> None:
        """The first of the month is the local first."""
        result = next_fire(TimeSchedule.parse("00:30", day_of_month="1"), at("2025-01-15 00:00", TOKYO), SUN)
        assert result is not None and (result.month, result.day, result.hour) == (2, 1, 0)
        assert result.astimezone(UTC).day == 31

    def test_utc_host(self) -> None:
        """A zone without daylight saving works the same way."""
        assert fires("09:00", datetime(2025, 3, 29, 12, 0, tzinfo=UTC), 2) == [
            "2025-03-30 09:00:00",
            "2025-03-31 09:00:00",
        ]


class TestDaylightSavingSkippedTime:
    """Rule: a time that does not exist on a day fires at the first instant after the gap."""

    def test_new_york_spring_forward(self) -> None:
        """02:30 on 9 March 2025 does not exist; the fire is at 03:00."""
        assert fires("02:30", at("2025-03-08 12:00"), 2) == ["2025-03-09 03:00:00", "2025-03-10 02:30:00"]

    def test_berlin_spring_forward(self) -> None:
        """In Berlin the gap is on 30 March 2025, from 02:00 to 03:00."""
        assert fires("02:30", at("2025-03-29 12:00", BERLIN), 2) == [
            "2025-03-30 03:00:00",
            "2025-03-31 02:30:00",
        ]

    def test_start_of_the_gap(self) -> None:
        """02:00 itself is the first skipped time."""
        assert fires("02:00", at("2025-03-08 12:00"), 1) == ["2025-03-09 03:00:00"]

    def test_only_one_fire_on_the_day(self) -> None:
        """The moved fire replaces the skipped time; it fires once that day."""
        instants = fires("02:30", at("2025-03-09 00:00"), 2)
        assert instants == ["2025-03-09 03:00:00", "2025-03-10 02:30:00"]

    def test_times_outside_the_gap_are_unaffected(self) -> None:
        """01:59 and 03:00 on the day exist as written."""
        assert fires("01:59", at("2025-03-09 00:00"), 1) == ["2025-03-09 01:59:00"]
        assert fires("03:00", at("2025-03-09 00:00"), 1) == ["2025-03-09 03:00:00"]

    def test_instant_after_the_gap(self) -> None:
        """The fire is the instant the clocks change: one second after 01:59:59."""
        fire = next_fire(TimeSchedule.parse("02:30"), at("2025-03-08 12:00"), SUN)
        before = next_fire(TimeSchedule.parse("01:59:59"), at("2025-03-08 12:00"), SUN)
        assert fire is not None and before is not None
        assert fire.astimezone(UTC) - before.astimezone(UTC) == timedelta(seconds=1)


class TestDaylightSavingRepeatedTime:
    """Rule: a time that occurs twice fires once, at the first occurrence."""

    def test_new_york_fall_back(self) -> None:
        """01:30 on 2 November 2025 occurs twice; the fire is the first, in daylight time."""
        fire = next_fire(TimeSchedule.parse("01:30"), at("2025-11-01 12:00"), SUN)
        assert fire is not None
        assert fire.strftime("%Y-%m-%d %H:%M") == "2025-11-02 01:30"
        assert fire.utcoffset() == timedelta(hours=-4)

    def test_fires_once(self) -> None:
        """The second 01:30 is not a fire: the next one is the following day."""
        first = next_fire(TimeSchedule.parse("01:30"), at("2025-11-01 12:00"), SUN)
        assert first is not None
        second = next_fire(TimeSchedule.parse("01:30"), first, SUN)
        assert second is not None
        assert second.strftime("%Y-%m-%d %H:%M") == "2025-11-03 01:30"
        assert second.astimezone(UTC) - first.astimezone(UTC) == timedelta(hours=25)

    def test_asked_between_the_two_occurrences(self) -> None:
        """Between the first and the second 01:30, the next fire is still the following day."""
        between = datetime(2025, 11, 2, 5, 45, tzinfo=UTC).astimezone(NEW_YORK)  # 01:45, first time round
        fire = next_fire(TimeSchedule.parse("01:30"), between, SUN)
        assert fire is not None and fire.strftime("%Y-%m-%d %H:%M") == "2025-11-03 01:30"

    def test_berlin_fall_back(self) -> None:
        """In Berlin 02:30 occurs twice on 26 October 2025."""
        fire = next_fire(TimeSchedule.parse("02:30"), at("2025-10-25 12:00", BERLIN), SUN)
        assert fire is not None
        assert (fire.strftime("%Y-%m-%d %H:%M"), fire.utcoffset()) == ("2025-10-26 02:30", timedelta(hours=2))


class TestMissedFires:
    """Rule: a time that has passed is not fired later."""

    def test_no_catch_up(self) -> None:
        """Asked after the time, the answer is the next occurrence, not the missed one."""
        assert fires("09:00", at("2025-01-06 09:00:01"), 1) == ["2025-01-07 09:00:00"]
        assert fires("09:00", at("2025-01-10 15:00"), 1) == ["2025-01-11 09:00:00"]

    def test_long_gap(self) -> None:
        """After a month of downtime there is one next fire, not thirty."""
        schedule = TimeSchedule.parse("09:00")
        fire = next_fire(schedule, at("2025-02-06 10:00"), SUN)
        assert fire is not None and fire.strftime("%Y-%m-%d") == "2025-02-07"


class TestOneTimeInThePast:
    """Rule: a full date and time that has already passed never fires."""

    def test_never_fires(self) -> None:
        """There is no next fire."""
        assert next_fire(TimeSchedule.parse("2024-12-25 09:00:00"), at("2025-01-06 12:00"), SUN) is None
        assert next_fire(TimeSchedule.parse("2025-01-06"), at("2025-01-06 12:00"), SUN) is None

    def test_recognised_as_past(self) -> None:
        """is_past_one_time tells it apart from a schedule that merely has nothing left this year."""
        now = at("2025-01-06 12:00")
        assert is_past_one_time(TimeSchedule.parse("2024-12-25 09:00:00"), now, SUN) is True
        assert is_past_one_time(TimeSchedule.parse("2025-12-25 09:00:00"), now, SUN) is False
        assert is_past_one_time(TimeSchedule.parse("12-25"), now, SUN) is False
        assert is_past_one_time(TimeSchedule.parse("09:00"), now, SUN) is False

    def test_one_time_with_offset_still_ahead(self) -> None:
        """What counts is the fire, offset included."""
        assert next_fire(TimeSchedule.parse("2025-01-06 + 20 hours"), at("2025-01-06 12:00"), SUN) is not None


class TestDaysThatDoNotExist:
    """Rule: day 31 fires only in months with 31 days; February 29 only in leap years."""

    def test_day_31(self) -> None:
        """Months with 30 days or fewer are skipped."""
        assert fires("10:00", at("2025-01-06 12:00"), 5, day_of_month="31") == [
            "2025-01-31 10:00:00",
            "2025-03-31 10:00:00",
            "2025-05-31 10:00:00",
            "2025-07-31 10:00:00",
            "2025-08-31 10:00:00",
        ]

    def test_day_30_skips_february(self) -> None:
        """February has no 30th."""
        assert fires("10:00", at("2025-01-31 12:00"), 2, day_of_month="30") == [
            "2025-03-30 10:00:00",
            "2025-04-30 10:00:00",
        ]

    def test_day_29_in_february(self) -> None:
        """The 29th exists in February only in a leap year."""
        assert fires("10:00", at("2025-01-30 12:00"), 1, day_of_month="29") == ["2025-03-29 10:00:00"]
        assert fires("10:00", at("2028-01-30 12:00"), 1, day_of_month="29") == ["2028-02-29 10:00:00"]

    def test_february_29_short_date(self) -> None:
        """A short date of February 29 fires in leap years only."""
        assert fires("February 29 09:00", at("2025-01-06 12:00"), 2) == [
            "2028-02-29 09:00:00",
            "2032-02-29 09:00:00",
        ]

    def test_several_days_of_month(self) -> None:
        """The design's example: the 1st and the 15th."""
        assert fires("10:00:00", at("2025-01-06 12:00"), 3, day_of_month="1,15") == [
            "2025-01-15 10:00:00",
            "2025-02-01 10:00:00",
            "2025-02-15 10:00:00",
        ]


class TestDayOfWeekWithDayOfMonth:
    """Rule: when both are given, both must match."""

    def test_friday_the_13th(self) -> None:
        """day_of_week AND day_of_month."""
        assert fires("09:00", at("2025-01-06 12:00"), 2, day_of_week="friday", day_of_month="13") == [
            "2025-06-13 09:00:00",
            "2026-02-13 09:00:00",
        ]

    def test_either_alone(self) -> None:
        """Each restriction on its own."""
        assert fires("09:00", at("2025-01-06 12:00"), 2, day_of_week="friday") == [
            "2025-01-10 09:00:00",
            "2025-01-17 09:00:00",
        ]
        assert fires("09:00", at("2025-01-06 12:00"), 2, day_of_month="13") == [
            "2025-01-13 09:00:00",
            "2025-02-13 09:00:00",
        ]

    def test_design_example_three_days_a_week(self) -> None:
        """The design's example: Monday, Wednesday, Friday at 09:00."""
        # 6 January 2025 is a Monday
        assert fires("09:00:00", at("2025-01-06 00:00"), 4, day_of_week="monday,wednesday,friday") == [
            "2025-01-06 09:00:00",
            "2025-01-08 09:00:00",
            "2025-01-10 09:00:00",
            "2025-01-13 09:00:00",
        ]

    def test_weekdays_and_weekends(self) -> None:
        """The groups."""
        assert fires("09:00", at("2025-01-09 12:00"), 3, day_of_week="weekdays") == [
            "2025-01-10 09:00:00",
            "2025-01-13 09:00:00",
            "2025-01-14 09:00:00",
        ]
        assert fires("09:00", at("2025-01-09 12:00"), 2, day_of_week="weekends") == [
            "2025-01-11 09:00:00",
            "2025-01-12 09:00:00",
        ]

    def test_sunday_is_zero(self) -> None:
        """Index 0 is Sunday."""
        assert fires("09:00", at("2025-01-06 12:00"), 1, day_of_week=0) == ["2025-01-12 09:00:00"]

    def test_with_a_short_date(self) -> None:
        """A date restricted to a day of the week fires in the years where they coincide."""
        assert fires("December 25 09:00", at("2025-01-06 12:00"), 1, day_of_week="friday") == [
            "2026-12-25 09:00:00"
        ]


class PartialSun:
    """A sun that does not rise or set on some days."""

    def __init__(self, dark_days: set[date]) -> None:
        self.dark_days = dark_days
        self.inner = FakeSunProvider(sunrise="07:00", sunset="19:00")

    def next_event(self, event: str, after: datetime) -> datetime | None:
        """Return the next event that is not on a dark day."""
        found = self.inner.next_event(event, after)
        while found is not None and found.date() in self.dark_days:
            found = self.inner.next_event(event, found)
        return found


class TestNoSunriseOrSunset:
    """Rule: on days when the sun does not rise or set, triggers based on it do not fire."""

    def test_day_without_a_sunset_is_skipped(self) -> None:
        """There is no fire for the dark days; the next one is on the first day with a sunset."""
        sun = PartialSun({date(2025, 1, 7), date(2025, 1, 8)})
        assert fires("sunset", at("2025-01-06 12:00"), 3, sun=sun) == [
            "2025-01-06 19:00:00",
            "2025-01-09 19:00:00",
            "2025-01-10 19:00:00",
        ]

    def test_offset_does_not_bring_the_fire_back(self) -> None:
        """A dark day has no fire whatever the offset."""
        sun = PartialSun({date(2025, 1, 7)})
        assert fires("sunrise + 2 hours", at("2025-01-06 12:00"), 2, sun=sun) == [
            "2025-01-08 09:00:00",
            "2025-01-09 09:00:00",
        ]

    def test_never_any_sunrise(self) -> None:
        """A place with no sunrise at all has no fire, and the search ends."""
        sun = FakeSunProvider(sunrise=None, sunset="19:00")
        assert next_fire(TimeSchedule.parse("sunrise"), at("2025-01-06 12:00"), sun) is None
        assert fires("sunset", at("2025-01-06 12:00"), 1, sun=sun) == ["2025-01-06 19:00:00"]

    def test_clock_times_do_not_need_the_sun(self) -> None:
        """A clock time fires also where the sun does not rise."""
        sun = FakeSunProvider(sunrise=None, sunset=None)
        assert fires("09:00", at("2025-01-06 12:00"), 1, sun=sun) == ["2025-01-07 09:00:00"]

    def test_dark_named_date(self) -> None:
        """A yearly date on a dark day does not fire that year."""
        sun = PartialSun({date(2025, 12, 25)})
        assert fires("December 25 sunset", at("2025-01-06 12:00"), 1, sun=sun) == ["2026-12-25 19:00:00"]


class TestOffsetsAcrossMidnight:
    """Rule: an offset is applied to the time of the day it is evaluated for."""

    def test_fire_on_the_following_calendar_day(self) -> None:
        """sunset + 6 hours fires after midnight."""
        assert fires("sunset + 6 hours", at("2025-01-06 12:00"), 2) == [
            "2025-01-07 01:00:00",
            "2025-01-08 01:00:00",
        ]

    def test_fire_of_the_previous_day_is_still_ahead(self) -> None:
        """Asked just after midnight, the fire belonging to yesterday's sunset comes first."""
        assert fires("sunset + 6 hours", at("2025-01-07 00:30"), 1) == ["2025-01-07 01:00:00"]

    def test_day_of_week_is_matched_against_the_day_of_the_sunset(self) -> None:
        """Monday's sunset + 6 hours fires on Tuesday morning; Tuesday's sunset does not count."""
        # 6 January 2025 is a Monday
        assert fires("sunset + 6 hours", at("2025-01-06 12:00"), 2, day_of_week="monday") == [
            "2025-01-07 01:00:00",
            "2025-01-14 01:00:00",
        ]

    def test_negative_offset_to_the_previous_day(self) -> None:
        """midnight - 1 hour fires at 23:00 the day before, for the day the midnight belongs to."""
        assert fires("midnight - 1 hour", at("2025-01-06 12:00"), 1) == ["2025-01-06 23:00:00"]
        # Tuesday's midnight minus an hour is Monday 23:00
        assert fires("midnight - 1 hour", at("2025-01-06 12:00"), 1, day_of_week="tuesday") == [
            "2025-01-06 23:00:00"
        ]

    def test_day_of_month_is_matched_against_the_base_day(self) -> None:
        """The 31st's sunset + 6 hours fires on the 1st."""
        assert fires("sunset + 6 hours", at("2025-01-06 12:00"), 1, day_of_month="31") == [
            "2025-02-01 01:00:00"
        ]

    def test_offset_longer_than_a_day(self) -> None:
        """An offset of more than a day is elapsed time from the base."""
        assert fires("noon + 36 hours", at("2025-01-06 12:00"), 2) == [
            "2025-01-07 00:00:00",
            "2025-01-08 00:00:00",
        ]

    def test_offset_is_elapsed_time_across_a_clock_change(self) -> None:
        """midnight + 3 hours is three hours after midnight: 04:00 on the day the clocks go forward."""
        assert fires("midnight + 3 hours", at("2025-03-08 12:00"), 2) == [
            "2025-03-09 04:00:00",
            "2025-03-10 03:00:00",
        ]


class TestLocalInstant:
    """Wall-clock time on a day to an instant."""

    def test_ordinary_time(self) -> None:
        """A time that exists once."""
        instant = local_instant(date(2025, 1, 6), 9, 0, 0, NEW_YORK)
        assert instant.astimezone(UTC) == datetime(2025, 1, 6, 14, 0, tzinfo=UTC)

    def test_gap(self) -> None:
        """A skipped time gives the end of the gap."""
        instant = local_instant(date(2025, 3, 9), 2, 30, 0, NEW_YORK)
        assert instant.astimezone(UTC) == datetime(2025, 3, 9, 7, 0, tzinfo=UTC)
        assert instant.strftime("%H:%M:%S") == "03:00:00"

    def test_repeat(self) -> None:
        """A repeated time gives the first occurrence."""
        instant = local_instant(date(2025, 11, 2), 1, 30, 0, NEW_YORK)
        assert instant.astimezone(UTC) == datetime(2025, 11, 2, 5, 30, tzinfo=UTC)

    def test_fixed_offset_zone(self) -> None:
        """A zone without transitions."""
        assert local_instant(date(2025, 3, 9), 2, 30, 0, UTC) == datetime(2025, 3, 9, 2, 30, tzinfo=UTC)

    def test_half_hour_gap(self) -> None:
        """Lord Howe Island moves its clocks by half an hour: 02:00 to 02:30."""
        zone = ZoneInfo("Australia/Lord_Howe")
        instant = local_instant(date(2025, 10, 5), 2, 15, 0, zone)
        assert instant.strftime("%H:%M:%S") == "02:30:00"


# --- The trigger, on the fake clock ---------------------------------------------------------------


class TimeWorld(World):
    """A world in New York whose triggers are fired by the real trigger manager."""

    def __init__(self, root: Path, start: datetime, sun: Any = None) -> None:
        super().__init__(root)
        self.clock = FakeClock(start)
        self.host = make_host(files=LocalFileSystem(), clock=self.clock, sun=sun or SUN)
        self.pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=self.clock)
        self.dispatcher = ActionDispatcher(self.pool)
        self.triggers = TriggerManager(self.host, self.dispatcher)  # type: ignore[assignment]

    def fired(self) -> list[str]:
        """Return the trigger times of the logged events, as local wall-clock text."""
        return [event.trigger_time.strftime("%Y-%m-%d %H:%M:%S") for event in self.log]


def elapsed(events: list[Any]) -> list[timedelta]:
    """Return the real time between consecutive events (not the difference of their wall clocks)."""
    instants = [event.call_time.astimezone(UTC) for event in events]
    return [later - earlier for earlier, later in zip(instants, instants[1:])]


def source(decorator: str) -> str:
    """An automation with one time trigger function that logs its event."""
    return f"from haanim import on_time\n\n{decorator}\ndef at_time(event):\n    log.append(event)\n"


class TestTimeTrigger:
    """@on_time on the fake clock."""

    async def test_fires_daily(self, tmp_path: Path) -> None:
        """The design's example: 09:00 every day."""
        time_world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        await time_world.started("morning", source('@on_time("09:00")'))

        await time_world.clock.advance(minutes=59, seconds=59)
        assert time_world.log == []
        await time_world.clock.advance(seconds=1)
        assert time_world.fired() == ["2025-01-06 09:00:00"]

        await time_world.clock.advance(days=2)
        assert time_world.fired() == ["2025-01-06 09:00:00", "2025-01-07 09:00:00", "2025-01-08 09:00:00"]

    async def test_time_event(self, tmp_path: Path) -> None:
        """A fire delivers a TimeEvent whose trigger_time is the scheduled instant."""
        time_world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        await time_world.started("morning", source('@on_time("09:00")'))
        await time_world.clock.advance(hours=1)

        (event,) = time_world.log
        assert type(event) is TimeEvent
        assert event.trigger_time == at("2025-01-06 09:00")
        assert event.trigger_time.tzinfo is not None
        assert event.call_time == event.trigger_time
        assert (event.automation_id, event.source, event.caller, event.data) == (
            "morning",
            "trigger",
            None,
            {},
        )

    async def test_direct_call_is_not_a_time_event(self, tmp_path: Path) -> None:
        """Called by hand, the function gets a ManualEvent."""
        time_world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        automation = await time_world.started("morning", source('@on_time("09:00")'))
        await automation.call_action("at_time")
        assert type(time_world.log[0]) is ManualEvent

    async def test_one_time_fires_once(self, tmp_path: Path) -> None:
        """The design's example: a full date and time fires once and leaves no timer."""
        time_world = TimeWorld(tmp_path, at("2024-12-24 12:00"))
        await time_world.started("christmas", source('@on_time("2024-12-25 09:00:00")'))
        await time_world.clock.advance(days=400)

        assert time_world.fired() == ["2024-12-25 09:00:00"]
        assert time_world.clock.pending_timers == 0

    async def test_day_of_week_and_day_of_month(self, tmp_path: Path) -> None:
        """The decorator's day restrictions reach the schedule."""
        time_world = TimeWorld(tmp_path, at("2025-01-06 00:00"))
        await time_world.started(
            "weekly",
            source('@on_time("09:00:00", day_of_week="monday,wednesday,friday", day_of_month="6,10,15")'),
        )
        await time_world.clock.advance(days=10)
        assert time_world.fired() == ["2025-01-06 09:00:00", "2025-01-10 09:00:00", "2025-01-15 09:00:00"]

    async def test_sunset_with_offset(self, tmp_path: Path) -> None:
        """A sun-based time is asked of the host's sun provider each day."""
        time_world = TimeWorld(tmp_path, at("2025-01-06 12:00"))
        await time_world.started("evening", source('@on_time("sunset - 30 minutes")'))
        await time_world.clock.advance(days=2)
        assert time_world.fired() == ["2025-01-06 18:30:00", "2025-01-07 18:30:00"]

    async def test_across_the_spring_clock_change(self, tmp_path: Path) -> None:
        """Component test: 02:30 daily over the night the clocks go forward."""
        time_world = TimeWorld(tmp_path, at("2025-03-08 00:00"))
        await time_world.started("night", source('@on_time("02:30")'))
        await time_world.clock.advance(days=3)

        assert time_world.fired() == ["2025-03-08 02:30:00", "2025-03-09 03:00:00", "2025-03-10 02:30:00"]
        gaps = elapsed(time_world.log)
        assert gaps == [timedelta(hours=23, minutes=30), timedelta(hours=23, minutes=30)]

    async def test_across_the_autumn_clock_change(self, tmp_path: Path) -> None:
        """Component test: 01:30 daily over the night the clocks go back fires once that night."""
        time_world = TimeWorld(tmp_path, at("2025-11-01 00:00"))
        await time_world.started("night", source('@on_time("01:30")'))
        await time_world.clock.advance(days=3)

        assert time_world.fired() == ["2025-11-01 01:30:00", "2025-11-02 01:30:00", "2025-11-03 01:30:00"]
        offsets = [event.trigger_time.utcoffset() for event in time_world.log]
        assert offsets == [timedelta(hours=-4), timedelta(hours=-4), timedelta(hours=-5)]
        gaps = elapsed(time_world.log)
        assert gaps == [timedelta(hours=24), timedelta(hours=25)]

    async def test_missed_fire_is_not_caught_up(self, tmp_path: Path) -> None:
        """A time that passes while the automation is stopped does not fire when it starts again."""
        time_world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        automation = await time_world.started("morning", source('@on_time("09:00")'))
        await automation.stop()
        await time_world.clock.advance(hours=3)

        assert await automation.start()
        time_world.expose(automation)
        await time_world.clock.advance(hours=1)
        assert time_world.log == []

        await time_world.clock.advance(hours=21)
        assert time_world.fired() == ["2025-01-07 09:00:00"]

    async def test_stop_cancels_the_timer(self, tmp_path: Path) -> None:
        """A stopped automation has no pending fire."""
        time_world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        automation = await time_world.started("morning", source('@on_time("09:00")'))
        assert time_world.clock.pending_timers == 1
        await automation.stop()
        assert time_world.clock.pending_timers == 0

    async def test_one_time_in_the_past_is_a_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """It never fires; the automation log has a warning and the automation is on, not in error."""
        time_world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        with caplog.at_level(logging.WARNING):
            automation = await time_world.started("christmas", source('@on_time("2024-12-25 09:00:00")'))

        assert automation.state is AutomationState.ON
        assert automation.message is None
        records = [
            record for record in caplog.records if record.name == "haanim.engine.automation_context.christmas"
        ]
        assert [record.levelno for record in records] == [logging.WARNING]
        assert "'2024-12-25 09:00:00' of at_time is in the past and will not fire" in records[0].getMessage()

        await time_world.clock.advance(days=800)
        assert time_world.log == []
        assert time_world.clock.pending_timers == 0

    async def test_no_warning_for_a_time_that_recurs(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A daily time that has passed today is simply due tomorrow."""
        time_world = TimeWorld(tmp_path, at("2025-01-06 10:00"))
        with caplog.at_level(logging.WARNING):
            await time_world.started("morning", source('@on_time("09:00")'))
        assert [record for record in caplog.records if record.levelno >= logging.WARNING] == []

    async def test_no_sunrise(self, tmp_path: Path) -> None:
        """Where the sun does not rise, a sunrise trigger does not fire and the automation runs."""
        time_world = TimeWorld(
            tmp_path, at("2025-01-06 08:00"), sun=FakeSunProvider(sunrise=None, sunset="19:00")
        )
        automation = await time_world.started("dawn", source('@on_time("sunrise")'))
        await time_world.clock.advance(days=3)
        assert time_world.log == []
        assert automation.state is AutomationState.ON

    async def test_slow_action_does_not_move_the_schedule(self, tmp_path: Path) -> None:
        """The next fire is scheduled when the time comes, not when the action returns."""
        time_world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        automation = time_world.add(
            "morning",
            "from haanim import ActionMode, action, on_time, sleep\n\n@on_time('09:00')\n"
            "@action(execution_mode=ActionMode.QUEUE)\nasync def at_time(event):\n    log.append(event)\n"
            "    await sleep(30 * 3600)\n",
        )
        await automation.load()
        original = automation.context.execute

        async def execute() -> Any:
            result = await original()
            automation.context.set_symbol("log", time_world.log)
            return result

        automation.context.execute = execute  # type: ignore[method-assign]
        assert await automation.start()
        await time_world.clock.advance(days=2, hours=12)

        # The second run starts late, but its event is the one made at 09:00 the next day
        assert time_world.fired() == ["2025-01-06 09:00:00", "2025-01-07 09:00:00"]
        stopping = asyncio.create_task(automation.stop())
        await time_world.clock.advance(seconds=1)
        await stopping


INVALID = [
    ('@on_time("25:00")', "@on_time: '25:00' is not a date and time expression: '25:00' is not a time"),
    (
        '@on_time("sunrise + 30m")',
        "@on_time: 'sunrise + 30m' is not a date and time expression: 'm' is not a unit",
    ),
    ('@on_time("tomorrow")', "@on_time: 'tomorrow' is not a date and time expression"),
    ('@on_time("cron(0 8 * * *)")', "@on_time: 'cron(0 8 * * *)' is not a date and time expression"),
    ('@on_time("2025-02-30")', "@on_time: '2025-02-30' is not a date and time expression"),
    ('@on_time("09:00", day_of_week="funday")', "@on_time: day_of_week: 'funday' is not a day of the week"),
    ('@on_time("09:00", day_of_week=7)', "@on_time: day_of_week: '7' is not a day index"),
    ('@on_time("09:00", day_of_month="32")', "@on_time: day_of_month: '32' is not a day of the month"),
    ('@on_time("09:00", day_of_month="first")', "@on_time: day_of_month: 'first' is not a day of the month"),
    (
        '@on_interval(60, day_of_week="funday")',
        "@on_interval: day_of_week: 'funday' is not a day of the week",
    ),
]


class TestInvalidExpressions:
    """An expression that cannot be read puts the automation in error when it starts."""

    @pytest.mark.parametrize(("decorator", "message"), INVALID, ids=[decorator for decorator, _ in INVALID])
    async def test_start_error(self, tmp_path: Path, decorator: str, message: str) -> None:
        """The message names the decorator and the offending text."""
        time_world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        automation: Automation = time_world.add(
            "broken",
            f"from haanim import on_time, on_interval\n\n{decorator}\ndef at_time(event):\n    pass\n",
        )
        assert await automation.load()
        assert not await automation.start()

        assert automation.state is AutomationState.ERROR
        assert automation.message is not None
        assert automation.message.startswith(f"ValueError: {message}")
        assert time_world.clock.pending_timers == 0
