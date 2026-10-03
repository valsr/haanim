"""Tests that the engine and its tests take time only from the injected clock.

The engine must not read the system clock or sleep on the event loop directly;
it uses ``haanim.interfaces.Clock``. The tests must not depend on real time
either, so they stay fast and deterministic.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
ENGINE_ROOT = REPO_ROOT / "src" / "haanim"
TESTS_ROOT = REPO_ROOT / "tests"

# module name -> attributes that read or wait on real time.
FORBIDDEN: dict[str, set[str]] = {
    "datetime": {"now", "utcnow", "today"},
    "date": {"today"},
    "time": {"time", "monotonic", "perf_counter", "sleep", "time_ns", "monotonic_ns"},
    "asyncio": {"sleep", "wait_for", "timeout", "timeout_at"},
}

# The contract tests run each protocol against Home Assistant's real implementation.
# For the real clock that means letting a little real time pass; nothing else may.
TESTS_EXEMPT = {"integration/test_contracts.py"}

# The fakes are the one place in the package allowed to yield to the event loop
# directly: FakeClock is what the rest of the code uses instead.
ENGINE_EXEMPT = {"testing/fakes.py"}


def real_time_uses(source: str, *, allow_zero_sleep: bool = False) -> list[str]:
    """Return a description of every use of real time in the given source.

    A use is any reference to a forbidden attribute, such as ``datetime.now``
    or ``asyncio.sleep``, whether it is called or only passed around (for
    example ``field(default_factory=datetime.now)``).

    Args:
        source: Python source code.
        allow_zero_sleep: Do not report ``asyncio.sleep(0)``, which yields to the
            event loop without waiting for any time to pass.

    Returns:
        ``"<line>: <module>.<attribute>"`` for each use, in source order.
    """
    tree = ast.parse(source)
    allowed: set[int] = set()
    if allow_zero_sleep:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and (node.func.value.id, node.func.attr) == ("asyncio", "sleep")
                and len(node.args) == 1
                and not node.keywords
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == 0
            ):
                allowed.add(id(node.func))

    uses: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.attr in FORBIDDEN.get(node.value.id, set())
            and id(node) not in allowed
        ):
            uses.append(f"{node.lineno}: {node.value.id}.{node.attr}")
    return sorted(uses, key=lambda use: int(use.split(":")[0]))


def python_files(root: Path) -> list[str]:
    """Return every Python file under a directory, relative to it."""
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*.py"))


class TestRealTimeUsesHelper:
    """Tests for the scanner used below."""

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("x = 1", []),
            ("from datetime import datetime\nnow = datetime.now()", ["2: datetime.now"]),
            ("import datetime as dt\nnow = dt.datetime.now()", []),
            ("from datetime import datetime\nf = field(default_factory=datetime.now)", ["2: datetime.now"]),
            ("from datetime import datetime\nd = datetime.utcnow()", ["2: datetime.utcnow"]),
            ("from datetime import date\nd = date.today()", ["2: date.today"]),
            ("import time\nt = time.time()", ["2: time.time"]),
            ("import time\ntime.sleep(1)", ["2: time.sleep"]),
            ("import time\nt = time.monotonic()", ["2: time.monotonic"]),
            ("import asyncio\nawait asyncio.sleep(1)", ["2: asyncio.sleep"]),
            ("import asyncio\nawait asyncio.sleep(0)", ["2: asyncio.sleep"]),
            ("import asyncio\nawait asyncio.wait_for(x, 1)", ["2: asyncio.wait_for"]),
            ("import asyncio\nasync with asyncio.timeout(1): pass", ["2: asyncio.timeout"]),
            ("import asyncio\nt = asyncio.create_task(x)", []),
            ("stamp = sun_time.time()", []),
            ("when = datetime.fromtimestamp(0)", []),
            ("now = self.clock.now()", []),
            ("await self.host.clock.sleep(5)", []),
            ("text = 'datetime.now()'", []),
            ("a = datetime.now()\nb = time.time()", ["1: datetime.now", "2: time.time"]),
        ],
    )
    def test_real_time_uses(self, source: str, expected: list[str]) -> None:
        """Test the scanner reports direct uses of real time and nothing else."""
        assert real_time_uses(source) == expected

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("await asyncio.sleep(0)", []),
            ("await asyncio.sleep(0.0)", []),
            ("await asyncio.sleep(1)", ["1: asyncio.sleep"]),
            ("await asyncio.sleep(delay)", ["1: asyncio.sleep"]),
            ("await asyncio.sleep(0, result=1)", ["1: asyncio.sleep"]),
            ("sleep = asyncio.sleep", ["1: asyncio.sleep"]),
            ("await asyncio.sleep(0)\nawait asyncio.sleep(2)", ["2: asyncio.sleep"]),
        ],
    )
    def test_allow_zero_sleep(self, source: str, expected: list[str]) -> None:
        """Test only a literal asyncio.sleep(0) is exempted when zero sleeps are allowed."""
        assert real_time_uses(source, allow_zero_sleep=True) == expected


class TestEngineUsesTheClock:
    """No engine module reads the system clock or sleeps on the loop directly."""

    def test_engine_has_modules(self) -> None:
        """Test the engine is found where this test expects it."""
        modules = python_files(ENGINE_ROOT)
        assert "engine/action_pool.py" in modules
        assert ENGINE_EXEMPT <= set(modules)

    @pytest.mark.parametrize("module", [m for m in python_files(ENGINE_ROOT) if m not in ENGINE_EXEMPT])
    def test_module_does_not_use_real_time(self, module: str) -> None:
        """Test an engine module contains no direct use of real time."""
        assert real_time_uses((ENGINE_ROOT / module).read_text(encoding="utf-8")) == []

    def test_fakes_only_yield(self) -> None:
        """Test the fakes use nothing beyond asyncio.sleep(0), which yields without waiting."""
        source = (ENGINE_ROOT / "testing" / "fakes.py").read_text(encoding="utf-8")
        assert real_time_uses(source, allow_zero_sleep=True) == []


class TestTestsDoNotUseRealTime:
    """No test waits on or reads real time, apart from the real clock's contract tests."""

    def test_exempt_modules_exist(self) -> None:
        """Test the exemption list names real files."""
        assert TESTS_EXEMPT <= set(python_files(TESTS_ROOT))

    @pytest.mark.parametrize("module", [m for m in python_files(TESTS_ROOT) if m not in TESTS_EXEMPT])
    def test_test_module_does_not_use_real_time(self, module: str) -> None:
        """Test a test module only ever yields; it never sleeps, times out or reads the clock."""
        source = (TESTS_ROOT / module).read_text(encoding="utf-8")
        assert real_time_uses(source, allow_zero_sleep=True) == []
