"""Durations: the interval and ``delay`` of ``@on_interval`` and the ``hold`` of ``@on_state``.

See "Duration Formats" under "Interval Trigger" in the design. A duration is a
number of seconds, or ``"HH:MM:SS"`` with all three parts, and is greater than
zero.
"""

from __future__ import annotations

import math
import re
from typing import Any

_CLOCK_FORM = re.compile(r"(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)")


def parse_duration(value: Any) -> float:
    """Convert a duration to seconds.

    Args:
        value: A number of seconds, a numeric string such as ``"0.5"``, or
            ``"HH:MM:SS"`` such as ``"00:05:00"``.

    Returns:
        The duration in seconds, greater than zero.

    Raises:
        ValueError: If the value is not a duration. The message says why.
    """
    seconds = _seconds(value)
    if math.isnan(seconds) or math.isinf(seconds):
        raise ValueError("a duration must be a finite number of seconds")
    if seconds <= 0:
        raise ValueError("a duration must be greater than zero")
    return seconds


def _seconds(value: Any) -> float:
    """Read the seconds a value spells, without checking the range."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"a duration is seconds or 'HH:MM:SS', not {type(value).__name__}")
    if not isinstance(value, str):
        return float(value)

    text = value.strip()
    parts = text.split(":")
    if len(parts) == 1:
        try:
            return float(text)
        except ValueError:
            raise ValueError("a duration is seconds or 'HH:MM:SS'") from None
    if len(parts) == 2:
        # "05:00" would be minutes and seconds here, but hours and minutes in a time expression
        raise ValueError("the two-part form is not accepted; write all three parts, 'HH:MM:SS'")

    match = _CLOCK_FORM.fullmatch(text)
    if match is None:
        raise ValueError("a duration is seconds or 'HH:MM:SS'")
    hours, minutes, seconds = int(match[1]), int(match[2]), float(match[3])
    if minutes >= 60 or seconds >= 60:
        raise ValueError("minutes and seconds must be below 60")
    return hours * 3600 + minutes * 60 + seconds
