"""Constraints: when a trigger that is due may fire.

See "Constraints" in the design. ``Constraints`` holds what one trigger
decorator was given (``start_time``, ``end_time``, ``start_date``,
``end_date``, ``day_of_week``, ``when``, ``when_not``) in parsed form, and
``allows()`` answers, for one instant, whether all of them hold. It is pure:
it reads the instant, the state lookup and the sun provider it is given.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from haanim.engine.expression_eval import Expression, StateLookup, parse_expression
from haanim.engine.time_expr import (
    CLOCK,
    DateSpec,
    TimeExpression,
    day_of_week_index,
    parse_date_expression,
    parse_day_of_week,
    parse_time_expression,
)
from haanim.engine.time_schedule import local_instant

if TYPE_CHECKING:
    from haanim.interfaces import SunProvider

_DAY_SECONDS = 24 * 3600


def _parse_time(name: str, value: Any) -> TimeExpression:
    """Parse ``start_time`` or ``end_time``: a time expression without a date."""
    try:
        expression = parse_time_expression(value)
    except ValueError as err:
        raise ValueError(f"{name}: {err}") from None
    if expression.date is not None:
        raise ValueError(f"{name}: '{value}' has a date; use start_date and end_date for dates")
    return expression


def _parse_date(name: str, value: Any) -> DateSpec:
    """Parse ``start_date`` or ``end_date``: a date without a time."""
    try:
        return parse_date_expression(value)
    except ValueError as err:
        raise ValueError(f"{name}: {err}") from None


def _clock_seconds(expression: TimeExpression) -> float | None:
    """Return the time of day of a clock time with its offset, in seconds; None for a sun time."""
    if expression.time.kind != CLOCK:
        return None
    time = expression.time
    return (
        time.hour * 3600 + time.minute * 60 + time.second + expression.offset.total_seconds()
    ) % _DAY_SECONDS


@dataclass(frozen=True)
class Constraints:
    """The constraints of one trigger.

    Args:
        start_time: Start of the allowed time of day, inclusive; None for 00:00:00.
        end_time: End of the allowed time of day, exclusive; None for the end of the day.
        start_date: Start of the allowed dates, inclusive; None for January 1st.
        end_date: End of the allowed dates, exclusive; None for January 1st of the next year.
        days_of_week: The allowed days of the week, 0 for Sunday; None for every day.
        when: A state expression that must be true.
        when_not: A state expression that must be false.
    """

    start_time: TimeExpression | None = None
    end_time: TimeExpression | None = None
    start_date: DateSpec | None = None
    end_date: DateSpec | None = None
    days_of_week: frozenset[int] | None = None
    when: Expression | None = None
    when_not: Expression | None = None

    @classmethod
    def parse(cls, given: Mapping[str, Any]) -> Constraints:
        """Build the constraints from the keyword arguments of a trigger decorator.

        Args:
            given: The constraint arguments by name. Missing ones and None are not constraints.

        Returns:
            The parsed constraints.

        Raises:
            ValueError: If an argument cannot be read, or a range is empty.
                The message names the argument and the offending text.
        """
        values = {name: value for name, value in given.items() if value is not None}
        constraints = cls(
            start_time=_parse_time("start_time", values["start_time"]) if "start_time" in values else None,
            end_time=_parse_time("end_time", values["end_time"]) if "end_time" in values else None,
            start_date=_parse_date("start_date", values["start_date"]) if "start_date" in values else None,
            end_date=_parse_date("end_date", values["end_date"]) if "end_date" in values else None,
            days_of_week=parse_day_of_week(values["day_of_week"]) if "day_of_week" in values else None,
            when=cls._expression("when", values.get("when")),
            when_not=cls._expression("when_not", values.get("when_not")),
        )
        constraints._check_ranges(values)
        return constraints

    @staticmethod
    def _expression(name: str, value: Any) -> Expression | None:
        """Parse a state expression of ``when`` or ``when_not``."""
        if value is None:
            return None
        try:
            return parse_expression(value)
        except Exception as err:
            raise ValueError(f"{name}: {err}") from None

    def _check_ranges(self, values: Mapping[str, Any]) -> None:
        """Reject ranges that allow nothing or cannot be compared."""
        if self.start_time is not None and self.end_time is not None:
            times = f"start_time '{values['start_time']}' and end_time '{values['end_time']}'"
            start = _clock_seconds(self.start_time)
            if start is not None and start == _clock_seconds(self.end_time):
                raise ValueError(f"{times} are the same time: the range is empty")

        if self.start_date is not None and self.end_date is not None:
            dates = f"start_date '{values['start_date']}' and end_date '{values['end_date']}'"
            if (self.start_date.year is None) != (self.end_date.year is None):
                raise ValueError(f"{dates}: give the year for both dates or for neither")
            if self.start_date == self.end_date:
                raise ValueError(f"{dates} are the same date: the range is empty")
            if self.start_date.year is not None and self._as_date(self.start_date) > self._as_date(
                self.end_date
            ):
                raise ValueError(f"{dates}: the start is after the end, so the range is empty")

    @property
    def is_empty(self) -> bool:
        """Whether there is no constraint at all."""
        return self == Constraints()

    @staticmethod
    def _as_date(spec: DateSpec) -> date:
        """Return a full date as a calendar date."""
        assert spec.year is not None
        return date(spec.year, spec.month, spec.day)

    # --- Evaluation ---------------------------------------------------------------

    def allows(self, now: datetime, lookup: StateLookup, sun: SunProvider) -> bool:
        """Return whether a trigger that is due at an instant may fire.

        All given constraints must hold.

        Args:
            now: The instant, timezone-aware, in the host's time zone.
            lookup: Returns the state of an entity, or None if it does not exist.
            sun: Sunrise and sunset at the host's location.
        """
        day = self._range_day(now, sun)
        if day is None:
            return False
        if self.days_of_week is not None and day_of_week_index(day) not in self.days_of_week:
            return False
        if not self._date_allows(day):
            return False
        if self.when is not None and not self.when.holds(lookup):
            return False
        return self.when_not is None or not self.when_not.blocks(lookup)

    def _time_of_day(self, expression: TimeExpression, now: datetime, sun: SunProvider) -> float | None:
        """Return a bound of the time range in seconds of the day; None if the sun has no such event today."""
        seconds = _clock_seconds(expression)
        if seconds is not None:
            return seconds
        zone = now.tzinfo
        assert zone is not None
        start_of_day = local_instant(now.date(), 0, 0, 0, zone)
        event = sun.next_event(expression.time.kind, start_of_day - timedelta(microseconds=1))
        if event is None or event.astimezone(zone).date() != now.date():
            return None
        local = event.astimezone(zone)
        return (
            local.hour * 3600 + local.minute * 60 + local.second + expression.offset.total_seconds()
        ) % _DAY_SECONDS

    def _range_day(self, now: datetime, sun: SunProvider) -> date | None:
        """Return the day the time range that contains ``now`` started on; None if no range contains it.

        Without a time range that is today. With a range that wraps around
        midnight, the hours after midnight belong to the day before.
        """
        if self.start_time is None and self.end_time is None:
            return now.date()

        current = now.hour * 3600 + now.minute * 60 + now.second + now.microsecond / 1_000_000
        start = self._time_of_day(self.start_time, now, sun) if self.start_time is not None else 0.0
        # A missing end is the end of the day: 00:00:00 of the next one
        end = self._time_of_day(self.end_time, now, sun) if self.end_time is not None else float(_DAY_SECONDS)
        if start is None or end is None or start == end:
            return None

        if start < end:
            return now.date() if start <= current < end else None
        if current >= start:
            return now.date()
        return now.date() - timedelta(days=1) if current < end else None

    def _date_allows(self, day: date) -> bool:
        """Return whether a day is inside the date range."""
        if self.start_date is None and self.end_date is None:
            return True

        known = self.start_date or self.end_date
        assert known is not None
        if known.year is not None:
            # Full dates. A missing bound is January 1st: of that year, or of the year after
            start = self._as_date(self.start_date) if self.start_date else date(known.year, 1, 1)
            end = self._as_date(self.end_date) if self.end_date else date(start.year + 1, 1, 1)
            return start <= day < end

        # Short dates recur every year and are compared as (month, day)
        current = (day.month, day.day)
        start_key = (self.start_date.month, self.start_date.day) if self.start_date else (1, 1)
        if self.end_date is None:
            return current >= start_key
        end_key = (self.end_date.month, self.end_date.day)
        if start_key < end_key:
            return start_key <= current < end_key
        return current >= start_key or current < end_key
