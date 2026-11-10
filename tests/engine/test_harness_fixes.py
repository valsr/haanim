"""Tests for the harness fixes: the time zone, relative imports of submodules, and failures that fail the test."""

from __future__ import annotations

from pathlib import Path

import pytest

from haanim.testing import AutomationHarness, HarnessError


def automation(tmp_path: Path, files: dict[str, str]) -> Path:
    folder = tmp_path / "demo"
    for name, source in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return folder


# --- Relative imports of submodules -------------------------------------------------

UTIL = "def triple(x):\n    return x * 3\n"
IMPORTS_UTIL = (
    "from haanim import action\nfrom .lib import util\n\n@action\ndef go(event):\n    return util.triple(2)\n"
)


async def test_from_package_import_submodule_without_init(tmp_path: Path) -> None:
    folder = automation(tmp_path, {"main.py": IMPORTS_UTIL, "lib/util.py": UTIL})
    async with AutomationHarness(folder) as harness:
        assert await harness.call("go") == 6


async def test_from_package_import_submodule_with_init(tmp_path: Path) -> None:
    folder = automation(tmp_path, {"main.py": IMPORTS_UTIL, "lib/util.py": UTIL, "lib/__init__.py": ""})
    async with AutomationHarness(folder) as harness:
        assert await harness.call("go") == 6


async def test_package_attribute_wins_over_submodule(tmp_path: Path) -> None:
    source = "from haanim import action\nfrom .lib import util\n\n@action\ndef go(event):\n    return util\n"
    folder = automation(
        tmp_path, {"main.py": source, "lib/util.py": UTIL, "lib/__init__.py": "util = 'attribute'\n"}
    )
    async with AutomationHarness(folder) as harness:
        assert await harness.call("go") == "attribute"


async def test_missing_submodule(tmp_path: Path) -> None:
    source = "from haanim import action\nfrom .lib import nothing\n"
    folder = automation(tmp_path, {"main.py": source, "lib/util.py": UTIL})
    async with AutomationHarness(folder, start=False) as harness:
        assert await harness.load()
        assert not await harness.start()
        assert "cannot import name 'nothing' from '.lib'" in (harness.error or "")


# --- The time zone ------------------------------------------------------------------

CLOCK = """
from haanim import action, haa, on_time

seen = []

@on_time("13:00")
def at_one(event):
    seen.append(haa.now().isoformat())

@action
def now(event):
    return haa.now().isoformat()

@action
def fired(event):
    return seen
"""


async def test_time_zone_without_now(tmp_path: Path) -> None:
    """The clock starts at Monday 2025-01-06 12:00 in the given zone, which automations see."""
    folder = automation(tmp_path, {"main.py": CLOCK})
    async with AutomationHarness(folder, time_zone="Europe/Berlin") as harness:
        assert await harness.call("now") == "2025-01-06T12:00:00+01:00"


async def test_time_trigger_runs_at_local_time(tmp_path: Path) -> None:
    folder = automation(tmp_path, {"main.py": CLOCK})
    async with AutomationHarness(folder, time_zone="America/Toronto") as harness:
        await harness.advance_time(minutes=59)
        assert await harness.call("fired") == []
        await harness.advance_time(minutes=2)
        assert await harness.call("fired") == ["2025-01-06T13:00:00-05:00"]


async def test_time_zone_with_now_unchanged(tmp_path: Path) -> None:
    folder = automation(tmp_path, {"main.py": CLOCK})
    async with AutomationHarness(folder, now="2025-03-01 08:30:00", time_zone="Asia/Tokyo") as harness:
        assert await harness.call("now") == "2025-03-01T08:30:00+09:00"


async def test_default_stays_utc(tmp_path: Path) -> None:
    folder = automation(tmp_path, {"main.py": CLOCK})
    async with AutomationHarness(folder) as harness:
        assert await harness.call("now") == "2025-01-06T12:00:00+00:00"


async def test_sun_times_are_local(tmp_path: Path) -> None:
    source = (
        "from haanim import action, haa, on_time\nseen = []\n"
        "@on_time('sunset')\ndef dusk(event):\n    seen.append(haa.now().isoformat())\n"
        "@action\ndef fired(event):\n    return seen\n"
    )
    folder = automation(tmp_path, {"main.py": source})
    async with AutomationHarness(folder, time_zone="Europe/Berlin", sunset="19:00") as harness:
        await harness.advance_time(hours=7, minutes=1)
        assert await harness.call("fired") == ["2025-01-06T19:00:00+01:00"]


# --- Failures fail the test ---------------------------------------------------------

FAILING = """
from haanim import ActionMode, action, haa, on_event, on_state, shutdown

@on_state("sensor.temperature > 20")
def react(event):
    raise ValueError("sensor went wrong")

@on_event("slow")
@action(execution_mode=ActionMode.DROP)
async def slow(event):
    await haa.sleep(10)

@action
def fine(event):
    return "fine"
"""


async def test_a_triggered_failure_fails_the_next_harness_call(tmp_path: Path) -> None:
    folder = automation(tmp_path, {"main.py": FAILING})
    with pytest.raises(ValueError, match="sensor went wrong") as raised:
        async with AutomationHarness(folder) as harness:
            harness.set_state("sensor.temperature", "21")
            await harness.wait_idle()
    assert any("react" in note for note in raised.value.__notes__)


async def test_a_triggered_failure_fails_the_test_at_exit(tmp_path: Path) -> None:
    folder = automation(tmp_path, {"main.py": FAILING})
    with pytest.raises(ValueError, match="sensor went wrong"):
        async with AutomationHarness(folder) as harness:
            harness.set_state("sensor.temperature", "21")
            await harness.clock.settle()


async def test_a_failure_is_raised_before_the_next_call(tmp_path: Path) -> None:
    folder = automation(tmp_path, {"main.py": FAILING})
    async with AutomationHarness(folder, expect_failures=False) as harness:
        harness.set_state("sensor.temperature", "21")
        await harness.clock.settle()
        with pytest.raises(ValueError):
            await harness.call("fine")
        assert await harness.call("fine") == "fine", "a failure is raised once"


async def test_expect_failures_collects_them(tmp_path: Path) -> None:
    folder = automation(tmp_path, {"main.py": FAILING})
    async with AutomationHarness(folder, expect_failures=True) as harness:
        harness.set_state("sensor.temperature", "21")
        await harness.wait_idle()
        assert [(f.action, type(f.error).__name__, str(f.error)) for f in harness.failures] == [
            ("react", "ValueError", "sensor went wrong")
        ]


async def test_a_dropped_request_does_not_fail(tmp_path: Path) -> None:
    folder = automation(tmp_path, {"main.py": FAILING})
    async with AutomationHarness(folder) as harness:
        harness.fire_event("slow")
        await harness.clock.settle()
        harness.fire_event("slow")
        await harness.clock.settle()
        await harness.advance_time(seconds=10)
        await harness.wait_idle()


async def test_a_failing_shutdown_fails_the_test(tmp_path: Path) -> None:
    source = (
        "from haanim import shutdown\n@shutdown\ndef end(event):\n    raise RuntimeError('cleanup failed')\n"
    )
    folder = automation(tmp_path, {"main.py": source})
    with pytest.raises(HarnessError, match="cleanup failed"):
        async with AutomationHarness(folder):
            pass
