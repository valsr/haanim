"""Cron expressions: validation and when one is due.

See "Cron Trigger" in the design. The dialect is the standard five fields
``minute hour day-of-month month day-of-week`` as ``cronsim`` implements
them (the library Home Assistant itself uses). Time zone and daylight saving follow the scheduling rules of the time
trigger: a skipped time fires at the first instant after the gap, and a time
that occurs twice fires once, at the first occurrence.
"""

from __future__ import annotations

from datetime import datetime, timezone

from cronsim import CronSim, CronSimError

from haanim.engine.time_schedule import local_instant

# How many matching wall-clock times are looked at for one that is later than the
# instant asked about. Around a clock change a few of them map to the same instant.
_MAX_STEPS = 1000

# A time to parse an expression against: which one does not matter
_ANY_TIME = datetime(2000, 1, 1)


def validate_cron(expression: object) -> str:
    """Check a cron expression against the dialect.

    Args:
        expression: The expression.

    Returns:
        The expression with its fields separated by single spaces.

    Raises:
        ValueError: If it is not a five-field cron expression. The message says why.
    """
    if not isinstance(expression, str):
        raise ValueError(f"a cron expression is a string, not {type(expression).__name__}")
    fields = expression.split()
    if not fields:
        raise ValueError("the cron expression is empty")
    if fields[0].startswith("@"):
        raise ValueError(f"'{expression}': aliases such as @daily are not supported; write the five fields")
    if len(fields) == 6:
        raise ValueError(f"'{expression}' has six fields; a seconds field is not supported")
    if len(fields) != 5:
        count = f"{len(fields)} field{'s' if len(fields) != 1 else ''}"
        raise ValueError(
            f"'{expression}' has {count}; a cron expression has five: "
            "minute hour day-of-month month day-of-week"
        )
    normalized = " ".join(fields)
    try:
        # The start only has to be a time: parsing is all that is wanted here
        CronSim(normalized, _ANY_TIME)
    except CronSimError as err:
        raise ValueError(f"'{expression}' is not a cron expression: {err}") from None
    return normalized


def next_cron_fire(expression: str, after: datetime) -> datetime | None:
    """Return the first instant after ``after`` at which a cron expression matches.

    The expression is matched against the wall clock of the time zone of
    ``after``, which is the host's.

    Args:
        expression: A valid cron expression.
        after: The instant to look from, timezone-aware. A match exactly at
            this instant is not returned.

    Returns:
        The next fire in the time zone of ``after``; None if no further match is
        found. A date that does not exist, such as 30 February, is not a valid
        expression in the first place.

    Raises:
        ValueError: If ``after`` has no time zone or the expression is not valid.
    """
    zone = after.tzinfo
    if zone is None:
        raise ValueError("next_cron_fire needs a timezone-aware datetime")
    after_utc = after.astimezone(timezone.utc)

    # cronsim walks the wall clock (it is given a time without a zone); each match is then placed on
    # the time line. It gives up on an expression that does not match for fifty years.
    walker = CronSim(validate_cron(expression), after.replace(tzinfo=None, second=0, microsecond=0))
    for _ in range(_MAX_STEPS):
        try:
            wall: datetime = next(walker)
        except StopIteration:
            return None
        fire = local_instant(wall.date(), wall.hour, wall.minute, 0, zone)
        if fire.astimezone(timezone.utc) > after_utc:
            return fire
    return None
