"""Tests for the duration parser.

See "Duration Formats" under "Interval Trigger" in the design.
"""

from __future__ import annotations

from typing import Any

import pytest

from haanim.engine.durations import parse_duration

VALID: list[tuple[Any, float]] = [
    # Seconds: a number or a numeric string
    (3600, 3600.0),
    (1, 1.0),
    (0.5, 0.5),
    (90.25, 90.25),
    ("3600", 3600.0),
    ("0.5", 0.5),
    ("  45  ", 45.0),
    ("1e2", 100.0),
    # "HH:MM:SS", always with all three parts
    ("00:05:00", 300.0),
    ("01:00:00", 3600.0),
    ("00:01:00", 60.0),
    ("00:00:45", 45.0),
    ("00:00:01", 1.0),
    ("01:30:15", 5415.0),
    ("36:00:00", 129600.0),
    ("100:00:00", 360000.0),
    ("0:5:0", 300.0),
    ("00:00:00.5", 0.5),
    (" 00:05:00 ", 300.0),
]

INVALID: list[tuple[Any, str]] = [
    # The two-part form
    ("05:00", "the two-part form is not accepted"),
    ("00:30", "the two-part form is not accepted"),
    ("5:0", "the two-part form is not accepted"),
    # Not greater than zero
    (0, "greater than zero"),
    (0.0, "greater than zero"),
    (-5, "greater than zero"),
    ("0", "greater than zero"),
    ("-1.5", "greater than zero"),
    ("00:00:00", "greater than zero"),
    # Not a duration at all
    ("", "seconds or 'HH:MM:SS'"),
    ("five minutes", "seconds or 'HH:MM:SS'"),
    ("5m", "seconds or 'HH:MM:SS'"),
    ("5 minutes", "seconds or 'HH:MM:SS'"),
    ("00:05:00:00", "seconds or 'HH:MM:SS'"),
    ("aa:bb:cc", "seconds or 'HH:MM:SS'"),
    ("-01:00:00", "seconds or 'HH:MM:SS'"),
    ("01:-5:00", "seconds or 'HH:MM:SS'"),
    ("::", "seconds or 'HH:MM:SS'"),
    ("1:000:00", "seconds or 'HH:MM:SS'"),
    # Out of range parts
    ("00:60:00", "minutes and seconds must be below 60"),
    ("00:00:60", "minutes and seconds must be below 60"),
    ("00:99:99", "minutes and seconds must be below 60"),
    # Not finite
    (float("inf"), "finite"),
    (float("nan"), "finite"),
    ("inf", "finite"),
    ("nan", "finite"),
    # Wrong type
    (None, "not NoneType"),
    (True, "not bool"),
    ([60], "not list"),
    ({"seconds": 5}, "not dict"),
]


class TestParseDuration:
    """parse_duration: seconds or HH:MM:SS, greater than zero."""

    @pytest.mark.parametrize(("value", "seconds"), VALID, ids=[repr(value) for value, _ in VALID])
    def test_valid(self, value: Any, seconds: float) -> None:
        """Each accepted form gives the number of seconds as a float."""
        result = parse_duration(value)
        assert result == seconds
        assert type(result) is float

    @pytest.mark.parametrize(("value", "reason"), INVALID, ids=[repr(value) for value, _ in INVALID])
    def test_invalid(self, value: Any, reason: str) -> None:
        """Everything else is a ValueError that says why."""
        with pytest.raises(ValueError, match=reason):
            parse_duration(value)

    def test_design_examples(self) -> None:
        """The examples of the design."""
        assert parse_duration(3600) == parse_duration("3600") == parse_duration("01:00:00")
        assert parse_duration("0.5") == 0.5
        assert parse_duration("00:05:00") == 300
        with pytest.raises(ValueError):
            parse_duration("05:00")

    def test_pure(self) -> None:
        """The same input gives the same output; nothing else is read."""
        assert [parse_duration("00:01:30") for _ in range(3)] == [90.0, 90.0, 90.0]
