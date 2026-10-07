"""When a date and time expression is due.

See "Scheduling Rules" under "Time Trigger" in the design. ``next_fire()`` is a
pure function: given a schedule, an instant and the sun provider, it returns
the first instant after that at which the schedule fires. The time zone is the
one of the instant given, which is the host's.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import TYPE_CHECKING

from haanim.engine.time_expr import (
    CLOCK,
    DAILY,
    ONCE,
    TimeExpression,
    day_of_week_index,
    parse_day_of_month,
    parse_day_of_week,
    parse_time_expression,
)

if TYPE_CHECKING:
    from haanim.interfaces import SunProvider

# How far ahead a day that matches is looked for. A date and day-of-week
# combination, or a February 29, can be years away; days without a sunrise
# can last for months.
_DAILY_HORIZON_DAYS = 366 * 5
_YEARLY_HORIZON_YEARS = 40


@dataclass(frozen=True)
class TimeSchedule:
    """What ``@on_time`` was given: the expression and the day restrictions.

    Args:
        expression: The parsed date and time expression.
        days_of_week: The days of the week it is restricted to, 0 for Sunday; None for every day.
        days_of_month: The days of the month it is restricted to; None for every day.
    """

    expression: TimeExpression
    days_of_week: frozenset[int] | None = None
    days_of_month: frozenset[int] | None = None

    @classmethod
    def parse(
        cls, expression: str, day_of_week: str | int | None = None, day_of_month: str | int | None = None
    ) -> TimeSchedule:
        """Build a schedule from the arguments of ``@on_time``.

        Raises:
            ValueError: If one of them cannot be read. The message names the offending text.
        """
        return cls(
            parse_time_expression(expression),
            parse_day_of_week(day_of_week) if day_of_week is not None else None,
            parse_day_of_month(day_of_month) if day_of_month is not None else None,
        )

    def matches_day(self, day: date) -> bool:
        """Return whether the schedule applies on a calendar day.

        When both restrictions are given, both must match.
        """
        spec = self.expression.date
        if spec is not None:
            if (spec.month, spec.day) != (day.month, day.day):
                return False
            if spec.year is not None and spec.year != day.year:
                return False
        if self.days_of_week is not None and day_of_week_index(day) not in self.days_of_week:
            return False
        return self.days_of_month is None or day.day in self.days_of_month


def local_instant(day: date, hour: int, minute: int, second: int, zone: tzinfo) -> datetime:
    """Return the instant of a wall-clock time on a day in a time zone.

    A time that does not exist that day, because the clocks go forward over
    it, gives the first instant after the gap. A time that occurs twice,
    because the clocks go back, gives the first occurrence.
    """
    wall = datetime(day.year, day.month, day.day, hour, minute, second)
    first = wall.replace(tzinfo=zone, fold=0)
    if first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == wall:
        return first

    # In a gap. With fold=0 the old offset applies and with fold=1 the new one,
    # which puts the transition between the two readings.
    before = wall.replace(tzinfo=zone, fold=1).astimezone(timezone.utc)
    after = first.astimezone(timezone.utc)
    old_offset = before.astimezone(zone).utcoffset()
    while after - before > timedelta(seconds=1):
        middle = before + timedelta(seconds=(after - before) // timedelta(seconds=2))
        if middle.astimezone(zone).utcoffset() == old_offset:
            before = middle
        else:
            after = middle
    return after.astimezone(zone)


def _base_instant(schedule: TimeSchedule, day: date, zone: tzinfo, sun: SunProvider) -> datetime | None:
    """Return the instant of the schedule's time on a day, before the offset.

    None on a day when the sun does not rise or set, for a schedule based on that.
    """
    time = schedule.expression.time
    if time.kind == CLOCK:
        return local_instant(day, time.hour, time.minute, time.second, zone)

    start_of_day = local_instant(day, 0, 0, 0, zone)
    event = sun.next_event(time.kind, start_of_day - timedelta(microseconds=1))
    if event is None or event.astimezone(zone).date() != day:
        return None
    return event.astimezone(zone)


def _fire_on(schedule: TimeSchedule, day: date, zone: tzinfo, sun: SunProvider) -> datetime | None:
    """Return when the schedule fires for a day it applies on; None if it does not fire for it."""
    base = _base_instant(schedule, day, zone, sun)
    if base is None:
        return None
    # The offset is elapsed time, added to the instant, not to the wall clock.
    # It may carry the fire over midnight; the day matched is the day of the base.
    return (base.astimezone(timezone.utc) + schedule.expression.offset).astimezone(zone)


def _candidate_days(schedule: TimeSchedule, first: date) -> list[date]:
    """Return the days the schedule could apply on, from a first day on, in order."""
    spec = schedule.expression.date
    if schedule.expression.recurrence == DAILY or spec is None:
        return [first + timedelta(days=number) for number in range(_DAILY_HORIZON_DAYS)]

    years = [spec.year] if spec.year is not None else range(first.year, first.year + _YEARLY_HORIZON_YEARS)
    days: list[date] = []
    for year in years:
        try:
            days.append(date(year, spec.month, spec.day))
        except ValueError:
            # February 29 outside a leap year
            continue
    return [day for day in days if day >= first]


def next_fire(schedule: TimeSchedule, after: datetime, sun: SunProvider) -> datetime | None:
    """Return the first instant after ``after`` at which the schedule fires.

    Args:
        schedule: The expression and its day restrictions.
        after: The instant to look from, timezone-aware, in the host's time
            zone. A fire exactly at this instant is not returned.
        sun: Sunrise and sunset at the host's location.

    Returns:
        The next fire in the time zone of ``after``; None if there is none. That
        is the case for a full date and time in the past.

    Raises:
        ValueError: If ``after`` has no time zone.
    """
    zone = after.tzinfo
    if zone is None:
        raise ValueError("next_fire needs a timezone-aware datetime")

    # A fire belongs to the day of its base time: with an offset, a fire after
    # ``after`` can belong to an earlier day, or with a negative offset to a later one
    reach = math.ceil(abs(schedule.expression.offset) / timedelta(days=1)) + 1
    first_day = after.date() - timedelta(days=reach)
    after_utc = after.astimezone(timezone.utc)

    for day in _candidate_days(schedule, first_day):
        if not schedule.matches_day(day):
            continue
        fire = _fire_on(schedule, day, zone, sun)
        # Compared as instants: two datetimes of one zone compare by wall clock, which is
        # wrong in the hour that occurs twice
        if fire is not None and fire.astimezone(timezone.utc) > after_utc:
            return fire
    return None


def is_past_one_time(schedule: TimeSchedule, now: datetime, sun: SunProvider) -> bool:
    """Return whether the schedule names one date and time that has already passed."""
    return schedule.expression.recurrence == ONCE and next_fire(schedule, now, sun) is None
