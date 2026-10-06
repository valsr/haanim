"""Tests for the date and time expression parser.

See "Time Trigger" in the design: Date Expression, Time Expression, Offset
Notes, Combined Date and Time, and the day_of_week and day_of_month formats.
"""

from __future__ import annotations

import ast
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from haanim.engine import time_expr
from haanim.engine.time_expr import (
    DAILY,
    MIDNIGHT,
    ONCE,
    YEARLY,
    DateSpec,
    TimeExpression,
    TimeSpec,
    day_of_week_index,
    parse_day_of_month,
    parse_day_of_week,
    parse_time_expression,
)


def clock(hour: int, minute: int = 0, second: int = 0) -> TimeSpec:
    """A time of day."""
    return TimeSpec("clock", hour, minute, second)


SUNRISE, SUNSET = TimeSpec("sunrise"), TimeSpec("sunset")
NO_OFFSET = timedelta(0)

# text -> (date, time, offset)
TIMES: dict[str, tuple[DateSpec | None, TimeSpec, timedelta]] = {
    # "HH:MM:SS", "HH:MM"
    "09:00": (None, clock(9), NO_OFFSET),
    "09:00:00": (None, clock(9), NO_OFFSET),
    "10:00:00": (None, clock(10), NO_OFFSET),
    "23:59:59": (None, clock(23, 59, 59), NO_OFFSET),
    "00:00": (None, clock(0), NO_OFFSET),
    "9:05": (None, clock(9, 5), NO_OFFSET),
    "17:47:30": (None, clock(17, 47, 30), NO_OFFSET),
    # "9am", "5:47pm"
    "9am": (None, clock(9), NO_OFFSET),
    "5:47pm": (None, clock(17, 47), NO_OFFSET),
    "9AM": (None, clock(9), NO_OFFSET),
    "9 am": (None, clock(9), NO_OFFSET),
    "12am": (None, clock(0), NO_OFFSET),
    "12pm": (None, clock(12), NO_OFFSET),
    "12:30am": (None, clock(0, 30), NO_OFFSET),
    "11:59:59pm": (None, clock(23, 59, 59), NO_OFFSET),
    "1pm": (None, clock(13), NO_OFFSET),
    # Relative
    "noon": (None, clock(12), NO_OFFSET),
    "midnight": (None, clock(0), NO_OFFSET),
    "sunrise": (None, SUNRISE, NO_OFFSET),
    "sunset": (None, SUNSET, NO_OFFSET),
    "Sunset": (None, SUNSET, NO_OFFSET),
    "NOON": (None, clock(12), NO_OFFSET),
}

OFFSETS: dict[str, tuple[DateSpec | None, TimeSpec, timedelta]] = {
    "sunset + 30 minutes": (None, SUNSET, timedelta(minutes=30)),
    "sunrise - 15 minutes": (None, SUNRISE, timedelta(minutes=-15)),
    "noon + 30 minutes": (None, clock(12), timedelta(minutes=30)),
    "2025-01-01 + 3 hours": (DateSpec(1, 1, 2025), MIDNIGHT, timedelta(hours=3)),
    "sunset - 90 minutes": (None, SUNSET, timedelta(minutes=-90)),
    "sunset + 6 hours": (None, SUNSET, timedelta(hours=6)),
    "09:00 + 45 seconds": (None, clock(9), timedelta(seconds=45)),
    "09:00 + 1 second": (None, clock(9), timedelta(seconds=1)),
    "09:00 - 1 minute": (None, clock(9), timedelta(minutes=-1)),
    "09:00 + 1 hour": (None, clock(9), timedelta(hours=1)),
    "sunrise + 1.5 hours": (None, SUNRISE, timedelta(minutes=90)),
    "sunset+30 minutes": (None, SUNSET, timedelta(minutes=30)),
    "sunset  -  30  Minutes": (None, SUNSET, timedelta(minutes=-30)),
    "9am + 2 hours": (None, clock(9), timedelta(hours=2)),
    "12-25 - 30 minutes": (DateSpec(12, 25), MIDNIGHT, timedelta(minutes=-30)),
    "midnight - 1 hour": (None, clock(0), timedelta(hours=-1)),
}

DATES: dict[str, tuple[DateSpec | None, TimeSpec, timedelta]] = {
    # Full date
    "2024-12-25": (DateSpec(12, 25, 2024), MIDNIGHT, NO_OFFSET),
    "2025-01-01": (DateSpec(1, 1, 2025), MIDNIGHT, NO_OFFSET),
    "2024-02-29": (DateSpec(2, 29, 2024), MIDNIGHT, NO_OFFSET),
    "2025-1-5": (DateSpec(1, 5, 2025), MIDNIGHT, NO_OFFSET),
    # Short date: "MM-DD", "Month Day", "Day Month"
    "12-25": (DateSpec(12, 25), MIDNIGHT, NO_OFFSET),
    "1-5": (DateSpec(1, 5), MIDNIGHT, NO_OFFSET),
    "02-29": (DateSpec(2, 29), MIDNIGHT, NO_OFFSET),
    "January 1st": (DateSpec(1, 1), MIDNIGHT, NO_OFFSET),
    "January 1": (DateSpec(1, 1), MIDNIGHT, NO_OFFSET),
    "1 January": (DateSpec(1, 1), MIDNIGHT, NO_OFFSET),
    "1st January": (DateSpec(1, 1), MIDNIGHT, NO_OFFSET),
    "December 25": (DateSpec(12, 25), MIDNIGHT, NO_OFFSET),
    "december 25th": (DateSpec(12, 25), MIDNIGHT, NO_OFFSET),
    "March 2nd": (DateSpec(3, 2), MIDNIGHT, NO_OFFSET),
    "3rd March": (DateSpec(3, 3), MIDNIGHT, NO_OFFSET),
    "Dec 25": (DateSpec(12, 25), MIDNIGHT, NO_OFFSET),
    "25 dec": (DateSpec(12, 25), MIDNIGHT, NO_OFFSET),
    "February 29": (DateSpec(2, 29), MIDNIGHT, NO_OFFSET),
}

COMBINED: dict[str, tuple[DateSpec | None, TimeSpec, timedelta]] = {
    "2024-12-25 09:00:00": (DateSpec(12, 25, 2024), clock(9), NO_OFFSET),
    "December 25 sunset - 30 minutes": (DateSpec(12, 25), SUNSET, timedelta(minutes=-30)),
    "2025-01-01 03:00:00": (DateSpec(1, 1, 2025), clock(3), NO_OFFSET),
    "12-25 09:00": (DateSpec(12, 25), clock(9), NO_OFFSET),
    "January 1st noon": (DateSpec(1, 1), clock(12), NO_OFFSET),
    "1 January 9am": (DateSpec(1, 1), clock(9), NO_OFFSET),
    "December 25 5:47 pm": (DateSpec(12, 25), clock(17, 47), NO_OFFSET),
    "2024-12-25 sunrise + 10 minutes": (DateSpec(12, 25, 2024), SUNRISE, timedelta(minutes=10)),
    "  2024-12-25   09:00:00  ": (DateSpec(12, 25, 2024), clock(9), NO_OFFSET),
}

INVALID: dict[str, str] = {
    "": "the date and time expression is empty",
    "   ": "the date and time expression is empty",
    "tomorrow": "'tomorrow' is neither a date nor a time",
    "25:00": "'25:00' is not a time: hours go to 23, minutes and seconds to 59",
    "09:60": "'09:60' is not a time",
    "09:00:60": "'09:00:60' is not a time",
    "13pm": "'13pm' is not a time: with am or pm the hour is 1 to 12",
    "0am": "'0am' is not a time: with am or pm the hour is 1 to 12",
    "9:5": "'9:5' is neither a date nor a time",
    "2025-02-30": "'2025-02-30' is not a date that exists",
    "2025-02-29": "'2025-02-29' is not a date that exists",
    "2025-13-01": "'2025-13-01' is not a date that exists",
    "13-01": "'13-01' is not a date that exists",
    "February 30": "'February 30' is not a date that exists",
    "31 April": "'31 April' is not a date that exists",
    "Smarch 3": "'Smarch 3' is neither a date nor a time",
    "09:00 2024-12-25": "the date comes first, then the time",
    "sunset December 25": "the date comes first, then the time",
    "2024-12-25 09:00 extra": "'2024-12-25 09:00 extra' is neither a date nor a time",
    "sunrise + 30m": "'m' is not a unit of an offset; use seconds, minutes or hours",
    "sunset + 5 days": "'days' is not a unit of an offset; use seconds, minutes or hours",
    "sunset + 30": "an offset is written '+ <number> seconds', 'minutes' or 'hours'",
    "sunset +": "an offset is written '+ <number> seconds', 'minutes' or 'hours'",
    "sunset + thirty minutes": "an offset is written '+ <number> seconds', 'minutes' or 'hours'",
    "+ 30 minutes": "there is nothing before the offset",
    "sunset - 30": "'sunset - 30' is neither a date nor a time",
    "sunset + 10 minutes + 5 minutes": "is neither a date nor a time",
    "09:00, 17:00": "'09:00, 17:00' is neither a date nor a time",
    "dawn": "'dawn' is neither a date nor a time",
}


def parts(expression: TimeExpression) -> tuple[DateSpec | None, TimeSpec, timedelta]:
    """Return the structure of a parsed expression."""
    return expression.date, expression.time, expression.offset


class TestTimeExpression:
    """Time: clock times, am and pm, and the relative names."""

    @pytest.mark.parametrize("text", TIMES)
    def test_times(self, text: str) -> None:
        """A time alone applies every day."""
        expression = parse_time_expression(text)
        assert parts(expression) == TIMES[text]
        assert expression.recurrence == DAILY

    def test_relative_time_notes(self) -> None:
        """noon is 12:00 PM and midnight is 12:00 AM, the start of the day."""
        assert parse_time_expression("noon").time == parse_time_expression("12:00pm").time == clock(12)
        assert parse_time_expression("midnight").time == parse_time_expression("12:00am").time == clock(0)

    def test_sun_times(self) -> None:
        """sunrise and sunset are kept as such: when they are depends on the day."""
        assert parse_time_expression("sunrise").uses_sun
        assert parse_time_expression("sunset - 90 minutes").uses_sun
        assert not parse_time_expression("noon").uses_sun
        assert not parse_time_expression("2024-12-25").uses_sun


class TestOffsets:
    """<date and/or time> +/- <number> seconds, minutes or hours."""

    @pytest.mark.parametrize("text", OFFSETS)
    def test_offsets(self, text: str) -> None:
        """The offset is kept apart from what it is applied to."""
        assert parts(parse_time_expression(text)) == OFFSETS[text]

    def test_design_equivalences(self) -> None:
        """noon + 30 minutes is 12:30; 2025-01-01 + 3 hours is 2025-01-01 03:00:00."""
        half_past = parse_time_expression("noon + 30 minutes")
        assert (half_past.time, half_past.offset) == (clock(12), timedelta(minutes=30))

        new_year = parse_time_expression("2025-01-01 + 3 hours")
        same = parse_time_expression("2025-01-01 03:00:00")
        assert new_year.date == same.date == DateSpec(1, 1, 2025)
        assert timedelta(hours=new_year.time.hour) + new_year.offset == timedelta(hours=same.time.hour)

    def test_offset_can_cross_midnight(self) -> None:
        """An offset larger than what is left of the day is kept as it is."""
        assert parse_time_expression("sunset + 6 hours").offset == timedelta(hours=6)
        assert parse_time_expression("midnight - 1 hour").offset == timedelta(hours=-1)


class TestDateExpression:
    """Full dates and the three short forms."""

    @pytest.mark.parametrize("text", DATES)
    def test_dates(self, text: str) -> None:
        """A date alone means the start of that day."""
        assert parts(parse_time_expression(text)) == DATES[text]

    def test_full_date_fires_once(self) -> None:
        """A date with a year comes once."""
        assert parse_time_expression("2024-12-25").recurrence == ONCE
        assert parse_time_expression("2024-12-25 09:00:00").recurrence == ONCE

    def test_short_date_fires_every_year(self) -> None:
        """A date without a year comes every year."""
        for text in ("12-25", "December 25", "25 December", "January 1st noon"):
            assert parse_time_expression(text).recurrence == YEARLY

    def test_no_date_fires_every_day(self) -> None:
        """Without a date the expression applies daily."""
        for text in ("09:00", "sunset - 30 minutes", "noon"):
            assert parse_time_expression(text).recurrence == DAILY

    def test_february_29(self) -> None:
        """A short date of February 29 is valid; a full date only in a leap year."""
        assert parse_time_expression("February 29").date == DateSpec(2, 29)
        assert parse_time_expression("2024-02-29").date == DateSpec(2, 29, 2024)
        with pytest.raises(ValueError, match="is not a date that exists"):
            parse_time_expression("2025-02-29")

    @pytest.mark.parametrize(
        "month",
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
    )
    def test_every_month_name(self, month: str) -> None:
        """Month names, full and abbreviated to three letters, in any case."""
        number = parse_time_expression(f"{month} 10").date
        assert number is not None
        for text in (f"10 {month}", f"{month[:3]} 10", f"{month.upper()} 10", f"10th {month.lower()}"):
            assert parse_time_expression(text).date == number


class TestCombined:
    """A date and a time in one string, date first."""

    @pytest.mark.parametrize("text", COMBINED)
    def test_combined(self, text: str) -> None:
        """The design's combined examples and their variations."""
        assert parts(parse_time_expression(text)) == COMBINED[text]

    def test_source_is_kept(self) -> None:
        """The expression remembers the text it was parsed from."""
        assert parse_time_expression("  2024-12-25   09:00:00  ").source == "  2024-12-25   09:00:00  "

    def test_result_is_a_value(self) -> None:
        """Parsing the same text twice gives equal, hashable structures."""
        first, second = parse_time_expression("12-25 09:00"), parse_time_expression("12-25 09:00")
        assert first == second
        assert len({first, second}) == 1


class TestInvalid:
    """Text that is not a date and time expression."""

    @pytest.mark.parametrize("text", INVALID, ids=[repr(text) for text in INVALID])
    def test_malformed(self, text: str) -> None:
        """ValueError with a message that names the offending text."""
        with pytest.raises(ValueError) as exc_info:
            parse_time_expression(text)
        assert INVALID[text] in str(exc_info.value)

    def test_message_quotes_the_whole_expression(self) -> None:
        """The message starts with the expression as it was written."""
        with pytest.raises(ValueError, match="^'December 32 noon' is not a date and time expression: "):
            parse_time_expression("December 32 noon")

    @pytest.mark.parametrize("value", [None, 900, 9.5, ["09:00"], True])
    def test_not_a_string(self, value: Any) -> None:
        """Only text is an expression."""
        with pytest.raises(ValueError, match="a date and time expression is a string"):
            parse_time_expression(value)

    def test_old_offset_notation_is_rejected(self) -> None:
        """The abbreviated units of the old code are not part of the language."""
        for text in ("sunrise + 30m", "sunset - 1h", "noon + 10s", "noon + 10 min"):
            with pytest.raises(ValueError, match="is not a unit of an offset"):
                parse_time_expression(text)


SUN, MON, TUE, WED, THU, FRI, SAT = range(7)

DAYS_OF_WEEK: list[tuple[Any, set[int]]] = [
    # Full names
    ("sunday", {SUN}),
    ("monday", {MON}),
    ("tuesday", {TUE}),
    ("wednesday", {WED}),
    ("thursday", {THU}),
    ("friday", {FRI}),
    ("saturday", {SAT}),
    ("Monday", {MON}),
    # Short names
    ("sun", {SUN}),
    ("mon", {MON}),
    ("tue", {TUE}),
    ("wed", {WED}),
    ("thu", {THU}),
    ("fri", {FRI}),
    ("sat", {SAT}),
    ("FRI", {FRI}),
    # Indexes, 0 is Sunday
    (0, {SUN}),
    (1, {MON}),
    (6, {SAT}),
    ("0", {SUN}),
    ("3", {WED}),
    # Groups
    ("weekdays", {MON, TUE, WED, THU, FRI}),
    ("weekends", {SAT, SUN}),
    ("Weekdays", {MON, TUE, WED, THU, FRI}),
    # Lists
    ("monday,wednesday,friday", {MON, WED, FRI}),
    ("monday,wednesday,friday, 0", {SUN, MON, WED, FRI}),
    ("mon, tue ,wed", {MON, TUE, WED}),
    ("weekends, fri", {FRI, SAT, SUN}),
    ("weekdays,weekends", {SUN, MON, TUE, WED, THU, FRI, SAT}),
    ("mon,monday,1", {MON}),
    ("0,1,2,3,4,5,6", {SUN, MON, TUE, WED, THU, FRI, SAT}),
]

BAD_DAYS_OF_WEEK: list[tuple[Any, str]] = [
    ("funday", "day_of_week: 'funday' is not a day of the week"),
    ("monday,funday", "day_of_week: 'funday' is not a day of the week"),
    ("tues", "day_of_week: 'tues' is not a day of the week"),
    ("7", "day_of_week: '7' is not a day index; indexes are 0 (Sunday) to 6 (Saturday)"),
    (7, "day_of_week: '7' is not a day index"),
    (-1, "day_of_week: '-1' is not a day of the week"),
    ("", "day_of_week '' has an empty item"),
    ("mon,,tue", "day_of_week 'mon,,tue' has an empty item"),
    ("mon,", "day_of_week 'mon,' has an empty item"),
    ("weekday", "day_of_week: 'weekday' is not a day of the week"),
    ("1.5", "day_of_week: '1.5' is not a day of the week"),
    (None, "day_of_week is a string or a number, not NoneType"),
    (True, "day_of_week is a string or a number, not bool"),
    (["mon"], "day_of_week is a string or a number, not list"),
    (1.0, "day_of_week is a string or a number, not float"),
]


class TestDayOfWeek:
    """day_of_week: names, short names, indexes, groups and lists."""

    @pytest.mark.parametrize(("value", "days"), DAYS_OF_WEEK, ids=[repr(value) for value, _ in DAYS_OF_WEEK])
    def test_formats(self, value: Any, days: set[int]) -> None:
        """Every format of the design, as indexes with 0 for Sunday."""
        assert parse_day_of_week(value) == days

    @pytest.mark.parametrize(
        ("value", "message"), BAD_DAYS_OF_WEEK, ids=[repr(value) for value, _ in BAD_DAYS_OF_WEEK]
    )
    def test_malformed(self, value: Any, message: str) -> None:
        """The message names the item that is not a day."""
        with pytest.raises(ValueError) as exc_info:
            parse_day_of_week(value)
        assert message in str(exc_info.value)

    def test_design_example(self) -> None:
        """The design's list example: three names and an index."""
        assert parse_day_of_week("monday,wednesday,friday, 0") == {0, 1, 3, 5}

    def test_index_of_a_date(self) -> None:
        """day_of_week_index gives the same numbering for a calendar date."""
        # 5 January 2025 is a Sunday
        assert [day_of_week_index(date(2025, 1, 5 + offset)) for offset in range(7)] == [0, 1, 2, 3, 4, 5, 6]
        assert day_of_week_index(date(2024, 12, 25)) in parse_day_of_week("wednesday")


DAYS_OF_MONTH: list[tuple[Any, set[int]]] = [
    ("1", {1}),
    ("15", {15}),
    (15, {15}),
    ("31", {31}),
    ("1,15", {1, 15}),
    ("1,15,30", {1, 15, 30}),
    (" 1 , 15 ", {1, 15}),
    ("01", {1}),
    ("5,5,5", {5}),
]

BAD_DAYS_OF_MONTH: list[tuple[Any, str]] = [
    ("0", "day_of_month: '0' is not a day of the month; days are 1 to 31"),
    ("32", "day_of_month: '32' is not a day of the month"),
    (0, "day_of_month: '0' is not a day of the month"),
    (-1, "day_of_month: '-1' is not a day of the month"),
    ("1,32", "day_of_month: '32' is not a day of the month"),
    ("first", "day_of_month: 'first' is not a day of the month"),
    ("last", "day_of_month: 'last' is not a day of the month"),
    ("1-15", "day_of_month: '1-15' is not a day of the month"),
    ("1.5", "day_of_month: '1.5' is not a day of the month"),
    ("", "day_of_month '' has an empty item"),
    ("1,,15", "day_of_month '1,,15' has an empty item"),
    (None, "day_of_month is a string or a number, not NoneType"),
    (True, "day_of_month is a string or a number, not bool"),
    ([1, 15], "day_of_month is a string or a number, not list"),
]


class TestDayOfMonth:
    """day_of_month: a day or a list of days."""

    @pytest.mark.parametrize(
        ("value", "days"), DAYS_OF_MONTH, ids=[repr(value) for value, _ in DAYS_OF_MONTH]
    )
    def test_formats(self, value: Any, days: set[int]) -> None:
        """Single days and lists."""
        assert parse_day_of_month(value) == days

    @pytest.mark.parametrize(
        ("value", "message"), BAD_DAYS_OF_MONTH, ids=[repr(value) for value, _ in BAD_DAYS_OF_MONTH]
    )
    def test_malformed(self, value: Any, message: str) -> None:
        """The message names the item that is not a day of the month."""
        with pytest.raises(ValueError) as exc_info:
            parse_day_of_month(value)
        assert message in str(exc_info.value)

    def test_design_examples(self) -> None:
        """The design's examples: "1", "15", "1,15,30" and the decorator's "1,15"."""
        assert parse_day_of_month("1,15") == {1, 15}
        assert parse_day_of_month("1,15,30") == {1, 15, 30}


class TestPurity:
    """The parser is text in, structure out."""

    def test_no_clock_and_no_host(self) -> None:
        """The module reads no clock and imports nothing of the engine or the host."""
        tree = ast.parse(Path(time_expr.__file__).read_text(encoding="utf-8"))
        imported = {
            node.module if isinstance(node, ast.ImportFrom) else alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert imported == {"__future__", "calendar", "re", "dataclasses", "datetime", "typing"}
        names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert not names & {"now", "today", "utcnow"}
