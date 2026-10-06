"""Date and time expressions: what ``@on_time`` and the time constraints accept.

See "Time Trigger" in the design. This module only parses: it turns the text
into a small structure and says what is wrong with text it cannot read. When
the expression is due is decided elsewhere.

An expression is an optional date, an optional time and an optional offset,
date first: ``"09:00"``, ``"2024-12-25 09:00:00"``, ``"December 25"``,
``"sunset - 30 minutes"``, ``"2025-01-01 + 3 hours"``.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

CLOCK = "clock"
SUNRISE = "sunrise"
SUNSET = "sunset"

# How often an expression comes round
ONCE = "once"
YEARLY = "yearly"
DAILY = "daily"

_MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): number for number, name in enumerate(calendar.month_abbr) if name})

# Days of the week by the design's numbering: 0 is Sunday
_DAY_NAMES = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")
_DAYS = {name: number for number, name in enumerate(_DAY_NAMES)}
_DAYS.update({name[:3]: number for number, name in enumerate(_DAY_NAMES)})
_DAY_GROUPS = {"weekdays": frozenset({1, 2, 3, 4, 5}), "weekends": frozenset({0, 6})}

_UNITS = {"second": 1, "seconds": 1, "minute": 60, "minutes": 60, "hour": 3600, "hours": 3600}

_OFFSET = re.compile(r"(?P<base>.*?)\s*(?P<sign>[+-])\s*(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>[a-z]+)", re.I)
_FULL_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_SHORT_DATE = re.compile(r"(\d{1,2})-(\d{1,2})")
_MONTH_DAY = re.compile(r"([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?", re.I)
_DAY_MONTH = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)", re.I)
_CLOCK_TIME = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")
_AM_PM_TIME = re.compile(r"(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*([ap]m)", re.I)

_NAMED_TIMES = {"noon": (12, 0, 0), "midnight": (0, 0, 0)}


@dataclass(frozen=True)
class DateSpec:
    """The date of an expression.

    Args:
        month: 1 to 12.
        day: 1 to 31.
        year: The year of a full date; None for a short date, which comes round every year.
    """

    month: int
    day: int
    year: int | None = None


@dataclass(frozen=True)
class TimeSpec:
    """The time of an expression.

    Args:
        kind: ``"clock"`` for a time of day, or ``"sunrise"`` or ``"sunset"``.
        hour: The hour of a clock time, 0 to 23.
        minute: The minute of a clock time.
        second: The second of a clock time.
    """

    kind: str = CLOCK
    hour: int = 0
    minute: int = 0
    second: int = 0


MIDNIGHT = TimeSpec()


@dataclass(frozen=True)
class TimeExpression:
    """A parsed date and time expression.

    Args:
        source: The text it was parsed from.
        time: The time. Midnight for an expression that gives only a date.
        date: The date; None for an expression that applies every day.
        offset: What to add to the date and time; negative for ``-``.
    """

    source: str
    time: TimeSpec = MIDNIGHT
    date: DateSpec | None = None
    offset: timedelta = timedelta(0)

    @property
    def recurrence(self) -> str:
        """How often it comes round.

        ``"once"`` for a full date, ``"yearly"`` for a short date, ``"daily"`` without a date.
        """
        if self.date is None:
            return DAILY
        return ONCE if self.date.year is not None else YEARLY

    @property
    def uses_sun(self) -> bool:
        """Whether the time is sunrise or sunset."""
        return self.time.kind in (SUNRISE, SUNSET)


def parse_time_expression(text: Any) -> TimeExpression:
    """Parse a date and/or time expression.

    Args:
        text: The expression, such as ``"09:00"``, ``"December 25 sunset - 30 minutes"``.

    Returns:
        The parsed expression.

    Raises:
        ValueError: If the text is not a date and time expression. The message
            names the part that could not be read.
    """
    if not isinstance(text, str):
        raise ValueError(f"a date and time expression is a string, not {type(text).__name__}")
    source = " ".join(text.split())
    if not source:
        raise ValueError("the date and time expression is empty")

    base, offset = _split_offset(source)
    try:
        parsed_date, parsed_time = _parse_base(base)
    except ValueError as err:
        raise ValueError(f"'{text}' is not a date and time expression: {err}") from None
    return TimeExpression(source=text, time=parsed_time or MIDNIGHT, date=parsed_date, offset=offset)


def parse_date_expression(text: Any) -> DateSpec:
    """Parse a date on its own: a full date or one of the short forms.

    Args:
        text: The date, such as ``"2024-12-25"``, ``"April 1"`` or ``"12-25"``.

    Returns:
        The parsed date.

    Raises:
        ValueError: If the text is not a date. The message names it.
    """
    if not isinstance(text, str):
        raise ValueError(f"a date is a string, not {type(text).__name__}")
    try:
        spec = _try_date(" ".join(text.split()))
    except ValueError as err:
        raise ValueError(str(err)) from None
    if spec is None:
        raise ValueError(f"'{text}' is not a date")
    return spec


def _split_offset(source: str) -> tuple[str, timedelta]:
    """Separate ``<base> +/- <amount> <unit>`` into the base and the offset."""
    match = _OFFSET.fullmatch(source)
    if match is None:
        if "+" in source:
            raise ValueError(
                f"'{source}' is not a date and time expression: "
                "an offset is written '+ <number> seconds', 'minutes' or 'hours'"
            )
        return source, timedelta(0)

    unit = match["unit"].lower()
    if unit not in _UNITS:
        raise ValueError(
            f"'{source}' is not a date and time expression: "
            f"'{match['unit']}' is not a unit of an offset; use seconds, minutes or hours"
        )
    if not match["base"]:
        raise ValueError(f"'{source}' is not a date and time expression: there is nothing before the offset")
    seconds = float(match["amount"]) * _UNITS[unit]
    return match["base"], timedelta(seconds=seconds if match["sign"] == "+" else -seconds)


def _parse_base(base: str) -> tuple[DateSpec | None, TimeSpec | None]:
    """Parse the part before the offset: a date, a time, or a date then a time."""
    parsed_time = _try_time(base)
    if parsed_time is not None:
        return None, parsed_time
    parsed_date = _try_date(base)
    if parsed_date is not None:
        return parsed_date, None

    # A date then a time, separated by a space; either can contain spaces itself
    words = base.split(" ")
    for split in range(1, len(words)):
        parsed_date = _try_date(" ".join(words[:split]))
        parsed_time = _try_time(" ".join(words[split:]))
        if parsed_date is not None and parsed_time is not None:
            return parsed_date, parsed_time

    for split in range(1, len(words)):
        if _try_time(" ".join(words[:split])) is not None and _try_date(" ".join(words[split:])) is not None:
            raise ValueError("the date comes first, then the time")
    raise ValueError(f"'{base}' is neither a date nor a time")


def _try_time(text: str) -> TimeSpec | None:
    """Parse a time, or return None if the text does not look like one.

    Raises:
        ValueError: If the text has the form of a time with a value out of range.
    """
    lowered = text.lower()
    if lowered in _NAMED_TIMES:
        return TimeSpec(CLOCK, *_NAMED_TIMES[lowered])
    if lowered in (SUNRISE, SUNSET):
        return TimeSpec(lowered)

    match = _CLOCK_TIME.fullmatch(text)
    if match is not None:
        return _clock(text, int(match[1]), int(match[2]), int(match[3] or 0))

    match = _AM_PM_TIME.fullmatch(text)
    if match is not None:
        hour = int(match[1])
        if not 1 <= hour <= 12:
            raise ValueError(f"'{text}' is not a time: with am or pm the hour is 1 to 12")
        # 12am is midnight and 12pm is noon
        hour = hour % 12 + (12 if match[4].lower() == "pm" else 0)
        return _clock(text, hour, int(match[2] or 0), int(match[3] or 0))
    return None


def _clock(text: str, hour: int, minute: int, second: int) -> TimeSpec:
    """Build a clock time, checking its ranges."""
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError(f"'{text}' is not a time: hours go to 23, minutes and seconds to 59")
    return TimeSpec(CLOCK, hour, minute, second)


def _try_date(text: str) -> DateSpec | None:
    """Parse a date, or return None if the text does not look like one.

    Raises:
        ValueError: If the text has the form of a date that does not exist.
    """
    match = _FULL_DATE.fullmatch(text)
    if match is not None:
        return _date(text, int(match[2]), int(match[3]), int(match[1]))
    match = _SHORT_DATE.fullmatch(text)
    if match is not None:
        return _date(text, int(match[1]), int(match[2]))

    match = _MONTH_DAY.fullmatch(text)
    if match is not None and match[1].lower() in _MONTHS:
        return _date(text, _MONTHS[match[1].lower()], int(match[2]))
    match = _DAY_MONTH.fullmatch(text)
    if match is not None and match[2].lower() in _MONTHS:
        return _date(text, _MONTHS[match[2].lower()], int(match[1]))
    return None


def _date(text: str, month: int, day: int, year: int | None = None) -> DateSpec:
    """Build a date, checking that it exists. A short date of February 29 exists in leap years."""
    try:
        # 2000 is a leap year: a short date may be any day some year has
        date(year if year is not None else 2000, month, day)
    except ValueError:
        raise ValueError(f"'{text}' is not a date that exists") from None
    return DateSpec(month, day, year)


def _items(value: Any, what: str) -> list[str]:
    """Split a ``day_of_week`` or ``day_of_month`` value into its comma-separated items."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{what} is a string or a number, not {type(value).__name__}")
    items = [item.strip() for item in str(value).split(",")]
    if any(not item for item in items):
        raise ValueError(f"{what} '{value}' has an empty item")
    return items


def parse_day_of_week(value: Any) -> frozenset[int]:
    """Parse a ``day_of_week`` value.

    Args:
        value: Day names (``"monday"``, ``"mon"``), indexes (0 is Sunday),
            ``"weekdays"``, ``"weekends"``, or a comma-separated list of those.

    Returns:
        The days as indexes, 0 for Sunday to 6 for Saturday.

    Raises:
        ValueError: If an item is not a day of the week. The message names it.
    """
    days: set[int] = set()
    for item in _items(value, "day_of_week"):
        lowered = item.lower()
        if lowered in _DAY_GROUPS:
            days |= _DAY_GROUPS[lowered]
        elif lowered in _DAYS:
            days.add(_DAYS[lowered])
        elif item.isdigit() and int(item) <= 6:
            days.add(int(item))
        elif item.isdigit():
            raise ValueError(
                f"day_of_week: '{item}' is not a day index; indexes are 0 (Sunday) to 6 (Saturday)"
            )
        else:
            raise ValueError(f"day_of_week: '{item}' is not a day of the week")
    return frozenset(days)


def parse_day_of_month(value: Any) -> frozenset[int]:
    """Parse a ``day_of_month`` value.

    Args:
        value: A day (``"15"`` or ``15``) or a comma-separated list (``"1,15,30"``).

    Returns:
        The days of the month, each 1 to 31.

    Raises:
        ValueError: If an item is not a day of the month. The message names it.
    """
    days: set[int] = set()
    for item in _items(value, "day_of_month"):
        if not item.isdigit() or not 1 <= int(item) <= 31:
            raise ValueError(f"day_of_month: '{item}' is not a day of the month; days are 1 to 31")
        days.add(int(item))
    return frozenset(days)


def day_of_week_index(day: date) -> int:
    """Return the design's index of a date's day of the week: 0 for Sunday to 6 for Saturday."""
    return (day.weekday() + 1) % 7
