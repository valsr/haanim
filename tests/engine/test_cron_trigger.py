"""Tests for the cron trigger.

See "Cron Trigger" in the design: the five-field dialect, day-of-month OR
day-of-week, and the scheduling rules it shares with the time trigger.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from haanim.engine import cron_schedule
from haanim.engine.cron_schedule import next_cron_fire, validate_cron
from haanim.engine.lifecycle import AutomationState
from haanim.engine.triggers import cron_trigger
from haanim.events import CronEvent, ManualEvent
from tests.engine.test_time_schedule import BERLIN, NEW_YORK, TimeWorld, at, elapsed

UTC = timezone.utc

ACCEPTED = [
    "0 9 * * 1-5",
    "* * * * *",
    "*/10 * * * *",
    "0 */2 * * *",
    "0 9 1,15 * *",
    "30 8 * * mon",
    "30 8 * * MON-FRI",
    "0 0 1 jan *",
    "0 0 1 JAN,JUL *",
    "0 9 * * 0",
    "0 9 * * 7",
    "15,45 6-18 * * *",
    "0 0 29 2 *",
    "5-55/10 * * * *",
    "0   9   *   *   1-5",
    "  0 9 * * 1-5  ",
]

REJECTED = [
    ("@daily", "aliases such as @daily are not supported"),
    ("@hourly", "aliases such as @daily are not supported"),
    ("@reboot", "aliases such as @daily are not supported"),
    ("0 0 9 * * *", "has six fields; a seconds field is not supported"),
    ("*/5 * * * * *", "has six fields; a seconds field is not supported"),
    ("0 9 * *", "has 4 fields; a cron expression has five"),
    ("0", "has 1 field; a cron expression has five"),
    ("* * * * * * *", "has 7 fields; a cron expression has five"),
    ("", "the cron expression is empty"),
    ("   ", "the cron expression is empty"),
    ("60 * * * *", "is not a cron expression"),
    ("* 24 * * *", "is not a cron expression"),
    ("* * 32 * *", "is not a cron expression"),
    ("* * * 13 *", "is not a cron expression"),
    ("* * * * 8", "is not a cron expression"),
    ("a b c d e", "is not a cron expression"),
    ("0 9 * * funday", "is not a cron expression"),
    ("09:00", "has 1 field"),
    ("every day at nine", "has 4 fields"),
]


def cron_fires(expression: str, start: datetime, count: int) -> list[str]:
    """Return the next ``count`` fires of an expression after ``start``, as local wall-clock text."""
    result = []
    instant: datetime | None = start
    for _ in range(count):
        assert instant is not None
        instant = next_cron_fire(expression, instant)
        if instant is None:
            break
        result.append(instant.strftime("%Y-%m-%d %H:%M"))
    return result


class TestDialect:
    """Five fields as cronsim implements them; no seconds field and no aliases."""

    @pytest.mark.parametrize("expression", ACCEPTED)
    def test_accepted(self, expression: str) -> None:
        """Ranges, lists, steps and month and weekday names."""
        assert validate_cron(expression) == " ".join(expression.split())
        assert next_cron_fire(expression, at("2025-01-06 12:00")) is not None

    @pytest.mark.parametrize(("expression", "reason"), REJECTED, ids=[repr(text) for text, _ in REJECTED])
    def test_rejected(self, expression: str, reason: str) -> None:
        """Everything else is a ValueError that says why and quotes the expression."""
        with pytest.raises(ValueError, match=reason) as exc_info:
            validate_cron(expression)
        if expression.strip():
            assert f"'{expression}'" in str(exc_info.value)

    @pytest.mark.parametrize("value", [None, 5, ["0 9 * * *"], True])
    def test_not_a_string(self, value: Any) -> None:
        """Only text is a cron expression."""
        with pytest.raises(ValueError, match="a cron expression is a string"):
            validate_cron(value)

    def test_ranges_lists_steps_and_names(self) -> None:
        """What each construct of the design means."""
        monday = at("2025-01-06 00:00")
        assert cron_fires("0 9 * * 1-5", monday, 6)[-2:] == ["2025-01-10 09:00", "2025-01-13 09:00"]
        assert cron_fires("0 9 1,15 * *", monday, 2) == ["2025-01-15 09:00", "2025-02-01 09:00"]
        assert cron_fires("*/10 * * * *", monday, 3) == [
            "2025-01-06 00:10",
            "2025-01-06 00:20",
            "2025-01-06 00:30",
        ]
        assert cron_fires("0 0 1 jan *", monday, 1) == ["2026-01-01 00:00"]
        assert cron_fires("0 9 * * mon", monday, 2) == ["2025-01-06 09:00", "2025-01-13 09:00"]

    def test_zero_and_seven_are_sunday(self) -> None:
        """Day of week 0 and 7 both mean Sunday."""
        monday = at("2025-01-06 00:00")
        assert (
            cron_fires("0 9 * * 0", monday, 2)
            == cron_fires("0 9 * * 7", monday, 2)
            == [
                "2025-01-12 09:00",
                "2025-01-19 09:00",
            ]
        )
        assert cron_fires("0 9 * * sun", monday, 1) == ["2025-01-12 09:00"]

    def test_design_example(self) -> None:
        """The design's example: 9 AM on weekdays."""
        friday_noon = at("2025-01-10 12:00")
        assert cron_fires("0 9 * * 1-5", friday_noon, 2) == ["2025-01-13 09:00", "2025-01-14 09:00"]


class TestDayOfMonthOrDayOfWeek:
    """When both day fields are restricted, the trigger fires when either matches."""

    def test_either_matches(self) -> None:
        """The 13th, and every Friday."""
        fires = cron_fires("0 9 13 * 5", at("2025-01-06 12:00"), 4)
        # Friday the 10th, Monday the 13th, Friday the 17th, Friday the 24th
        assert fires == ["2025-01-10 09:00", "2025-01-13 09:00", "2025-01-17 09:00", "2025-01-24 09:00"]

    def test_differs_from_on_time(self) -> None:
        """@on_time with the same restrictions needs both to match."""
        # pylint: disable-next=import-outside-toplevel
        from haanim.engine.time_schedule import TimeSchedule, next_fire
        from haanim.testing import FakeSunProvider  # pylint: disable=import-outside-toplevel

        both = next_fire(
            TimeSchedule.parse("09:00", day_of_week="friday", day_of_month="13"),
            at("2025-01-06 12:00"),
            FakeSunProvider(),
        )
        either = next_cron_fire("0 9 13 * 5", at("2025-01-06 12:00"))
        assert both is not None and either is not None
        assert (both.strftime("%Y-%m-%d"), either.strftime("%Y-%m-%d")) == ("2025-06-13", "2025-01-10")

    def test_only_one_field_restricted(self) -> None:
        """With one of the two fields a star, only the other counts."""
        assert cron_fires("0 9 13 * *", at("2025-01-06 12:00"), 2) == ["2025-01-13 09:00", "2025-02-13 09:00"]
        assert cron_fires("0 9 * * 5", at("2025-01-06 12:00"), 2) == ["2025-01-10 09:00", "2025-01-17 09:00"]


class TestTimeZoneAndDaylightSaving:
    """As in the scheduling rules of the time trigger."""

    def test_host_time_zone(self) -> None:
        """The fields are matched against the host's wall clock."""
        start = datetime(2025, 1, 6, 0, 0, tzinfo=UTC)
        new_york = next_cron_fire("0 9 * * *", start.astimezone(NEW_YORK))
        berlin = next_cron_fire("0 9 * * *", start.astimezone(BERLIN))
        assert new_york is not None and berlin is not None
        assert new_york.tzinfo is NEW_YORK
        assert new_york.astimezone(UTC).hour == 14
        assert berlin.astimezone(UTC).hour == 8

    def test_skipped_time_fires_after_the_gap(self) -> None:
        """30 2 * * * on the night the clocks go forward fires at 03:00."""
        assert cron_fires("30 2 * * *", at("2025-03-08 12:00"), 2) == ["2025-03-09 03:00", "2025-03-10 02:30"]

    def test_several_skipped_times_fire_once(self) -> None:
        """Every half hour: 02:00 and 02:30 do not exist; there is one fire at 03:00, not three."""
        assert cron_fires("*/30 * * * *", at("2025-03-09 01:15"), 4) == [
            "2025-03-09 01:30",
            "2025-03-09 03:00",
            "2025-03-09 03:30",
            "2025-03-09 04:00",
        ]

    def test_repeated_time_fires_once(self) -> None:
        """30 1 * * * on the night the clocks go back fires at the first 01:30 only."""
        first = next_cron_fire("30 1 * * *", at("2025-11-01 12:00"))
        assert first is not None
        assert (first.strftime("%Y-%m-%d %H:%M"), first.utcoffset()) == (
            "2025-11-02 01:30",
            timedelta(hours=-4),
        )

        second = next_cron_fire("30 1 * * *", first)
        assert second is not None
        assert second.strftime("%Y-%m-%d %H:%M") == "2025-11-03 01:30"
        assert second.astimezone(UTC) - first.astimezone(UTC) == timedelta(hours=25)

    def test_asked_during_the_repeated_hour(self) -> None:
        """Asked in the second 01:xx hour, the next 01:30 is tomorrow's."""
        second_time_round = datetime(2025, 11, 2, 6, 15, tzinfo=UTC).astimezone(NEW_YORK)
        assert second_time_round.strftime("%H:%M") == "01:15"
        fire = next_cron_fire("30 1 * * *", second_time_round)
        assert fire is not None and fire.strftime("%Y-%m-%d %H:%M") == "2025-11-03 01:30"

    def test_no_catch_up(self) -> None:
        """Asked after a match, the answer is the next match."""
        assert cron_fires("0 9 * * *", at("2025-01-06 09:00"), 1) == ["2025-01-07 09:00"]
        assert cron_fires("0 9 * * *", at("2025-02-20 15:00"), 1) == ["2025-02-21 09:00"]

    def test_strictly_after(self) -> None:
        """A match at exactly the given instant is not returned again."""
        fire = next_cron_fire("*/5 * * * *", at("2025-01-06 12:00"))
        assert fire is not None and fire.strftime("%H:%M") == "12:05"

    def test_seconds_of_the_instant_do_not_shift_the_match(self) -> None:
        """Matches are on whole minutes whatever second it is asked at."""
        fire = next_cron_fire("*/5 * * * *", at("2025-01-06 12:04:59"))
        assert fire is not None and (fire.minute, fire.second, fire.microsecond) == (5, 0, 0)

    @pytest.mark.parametrize("expression", ["0 0 30 2 *", "0 0 31 4 *", "0 0 31 feb,apr *"])
    def test_a_date_that_does_not_exist_is_not_an_expression(self, expression: str) -> None:
        """30 February would never fire: it is refused when the automation is loaded, not waited for."""
        with pytest.raises(ValueError, match="is not a cron expression"):
            validate_cron(expression)
        with pytest.raises(ValueError, match="is not a cron expression"):
            next_cron_fire(expression, at("2025-01-06 12:00"))

    def test_29_february_fires_in_leap_years(self) -> None:
        """A date that exists only in some years is waited for."""
        assert cron_fires("0 0 29 2 *", at("2025-01-06 12:00"), 2) == ["2028-02-29 00:00", "2032-02-29 00:00"]

    def test_no_further_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An expression the library finds no further match for has no next fire."""
        monkeypatch.setattr(cron_schedule, "CronSim", lambda expression, start: iter(()))
        assert next_cron_fire("0 9 * * *", at("2025-01-06 12:00")) is None

    def test_needs_a_time_zone(self) -> None:
        """A naive datetime is rejected."""
        with pytest.raises(ValueError, match="timezone-aware"):
            next_cron_fire("0 9 * * *", datetime(2025, 1, 6))


class TestNeverReadsTheSystemClock:
    """Done when: the trigger never reads the system clock."""

    @pytest.mark.parametrize("module", [cron_schedule, cron_trigger], ids=["cron_schedule", "cron_trigger"])
    def test_no_clock_calls(self, module: Any) -> None:
        """Neither module asks for the current time; it comes from the injected clock."""
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert not attributes & {"today", "utcnow", "time", "monotonic", "sleep"}
        now_calls = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "now"
        ]
        assert set(now_calls) <= {"self.host.clock.now()"}

    def test_cronsim_is_always_given_its_start(self) -> None:
        """The cron library walks on from the time it is given; it is always given one, never the system's."""
        tree = ast.parse(Path(cron_schedule.__file__).read_text(encoding="utf-8"))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "CronSim"
        ]
        assert len(calls) == 2, "one to check an expression, one to walk it"
        assert all(len(call.args) == 2 for call in calls)
        starts = sorted(ast.unparse(call.args[1]) for call in calls)
        assert starts == ["_ANY_TIME", "after.replace(tzinfo=None, second=0, microsecond=0)"]

    def test_same_answer_whenever_it_is_asked(self) -> None:
        """The result depends only on the arguments."""
        answers = {next_cron_fire("0 9 * * 1-5", at("2031-05-05 12:00")) for _ in range(3)}
        assert len(answers) == 1
        (answer,) = answers
        assert answer is not None and answer.year == 2031


def source(decorator: str) -> str:
    """An automation with one cron trigger function that logs its event."""
    return f"from haanim import on_cron\n\n{decorator}\ndef job(event):\n    log.append(event)\n"


class TestCronTrigger:
    """@on_cron on the fake clock."""

    async def test_weekday_mornings(self, tmp_path: Path) -> None:
        """The design's example fires at 09:00 Monday to Friday."""
        cron_world = TimeWorld(tmp_path, at("2025-01-09 12:00"))  # a Thursday
        await cron_world.started("jobs", source('@on_cron("0 9 * * 1-5")'))
        await cron_world.clock.advance(days=5)
        assert cron_world.fired() == ["2025-01-10 09:00:00", "2025-01-13 09:00:00", "2025-01-14 09:00:00"]

    async def test_cron_event(self, tmp_path: Path) -> None:
        """A fire delivers a CronEvent with the expression and the scheduled time."""
        cron_world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        await cron_world.started("jobs", source('@on_cron("0   9 * * *")'))
        await cron_world.clock.advance(hours=1)

        (event,) = cron_world.log
        assert type(event) is CronEvent
        assert event.cron_expression == "0 9 * * *"
        assert event.trigger_time == at("2025-01-06 09:00")
        assert event.call_time == event.trigger_time
        assert (event.automation_id, event.source, event.caller, event.data) == ("jobs", "trigger", None, {})

    async def test_direct_call_is_not_a_cron_event(self, tmp_path: Path) -> None:
        """Called by hand, the function gets a ManualEvent."""
        cron_world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        automation = await cron_world.started("jobs", source('@on_cron("0 9 * * *")'))
        await automation.call_action("job")
        assert type(cron_world.log[0]) is ManualEvent

    async def test_every_ten_minutes(self, tmp_path: Path) -> None:
        """A step expression fires on the wall clock's multiples, not relative to the start."""
        cron_world = TimeWorld(tmp_path, at("2025-01-06 08:03:20"))
        await cron_world.started("jobs", source('@on_cron("*/10 * * * *")'))
        await cron_world.clock.advance(minutes=30)
        assert cron_world.fired() == ["2025-01-06 08:10:00", "2025-01-06 08:20:00", "2025-01-06 08:30:00"]

    async def test_across_the_spring_clock_change(self, tmp_path: Path) -> None:
        """Component test: 02:30 daily over the night the clocks go forward."""
        cron_world = TimeWorld(tmp_path, at("2025-03-08 00:00"))
        await cron_world.started("jobs", source('@on_cron("30 2 * * *")'))
        await cron_world.clock.advance(days=3)

        assert cron_world.fired() == ["2025-03-08 02:30:00", "2025-03-09 03:00:00", "2025-03-10 02:30:00"]
        assert elapsed(cron_world.log) == [timedelta(hours=23, minutes=30)] * 2

    async def test_across_the_autumn_clock_change(self, tmp_path: Path) -> None:
        """Component test: every half hour through the repeated hour fires on each wall-clock time once."""
        cron_world = TimeWorld(tmp_path, at("2025-11-02 00:45"))
        await cron_world.started("jobs", source('@on_cron("*/30 * * * *")'))
        # Four hours of real time take the wall clock from 00:45 to 03:45 that night
        await cron_world.clock.advance(hours=4)

        assert cron_world.fired() == [
            "2025-11-02 01:00:00",
            "2025-11-02 01:30:00",
            "2025-11-02 02:00:00",
            "2025-11-02 02:30:00",
            "2025-11-02 03:00:00",
            "2025-11-02 03:30:00",
        ]
        # The hour from 01:00 to 02:00 comes twice: 01:30 to 02:00 is an hour and a half
        assert elapsed(cron_world.log)[:2] == [timedelta(minutes=30), timedelta(minutes=90)]

    async def test_missed_fires_are_not_caught_up(self, tmp_path: Path) -> None:
        """Matches that pass while the automation is stopped do not fire later."""
        cron_world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        automation = await cron_world.started("jobs", source('@on_cron("0 * * * *")'))
        await automation.stop()
        await cron_world.clock.advance(hours=5, minutes=30)

        assert await automation.start()
        cron_world.expose(automation)
        await cron_world.clock.advance(minutes=30)
        assert cron_world.fired() == ["2025-01-06 14:00:00"]

    async def test_stop_cancels_the_timer(self, tmp_path: Path) -> None:
        """A stopped automation has no pending fire."""
        cron_world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        automation = await cron_world.started("jobs", source('@on_cron("0 9 * * *")'))
        assert cron_world.clock.pending_timers == 1
        await automation.stop()
        assert cron_world.clock.pending_timers == 0

    async def test_follows_the_fake_clock_far_from_today(self, tmp_path: Path) -> None:
        """The schedule follows the injected clock, whatever the real date is."""
        cron_world = TimeWorld(tmp_path, at("2041-07-04 08:59"))
        await cron_world.started("jobs", source('@on_cron("0 9 * * *")'))
        await cron_world.clock.advance(minutes=1)
        assert cron_world.fired() == ["2041-07-04 09:00:00"]


INVALID = [
    ('@on_cron("@daily")', "@on_cron: '@daily': aliases such as @daily are not supported"),
    ('@on_cron("0 0 9 * * *")', "@on_cron: '0 0 9 * * *' has six fields; a seconds field is not supported"),
    ('@on_cron("0 9 * *")', "@on_cron: '0 9 * *' has 4 fields; a cron expression has five"),
    ('@on_cron("61 * * * *")', "@on_cron: '61 * * * *' is not a cron expression"),
    ('@on_cron("09:00")', "@on_cron: '09:00' has 1 field"),
]


class TestInvalidExpressions:
    """An invalid expression puts the automation in error when it starts."""

    @pytest.mark.parametrize(("decorator", "message"), INVALID, ids=[decorator for decorator, _ in INVALID])
    async def test_start_error(self, tmp_path: Path, decorator: str, message: str) -> None:
        """The message names the decorator and the expression."""
        cron_world = TimeWorld(tmp_path, at("2025-01-06 08:00"))
        automation = cron_world.add(
            "jobs", f"from haanim import on_cron\n\n{decorator}\ndef job(event):\n    pass\n"
        )
        assert await automation.load()
        assert not await automation.start()

        assert automation.state is AutomationState.ERROR
        assert automation.message is not None
        assert automation.message.startswith(f"ValueError: {message}")
        assert cron_world.clock.pending_timers == 0
