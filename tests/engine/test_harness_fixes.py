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
