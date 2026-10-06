"""Tests for the examples as a set: each is a complete automation folder, tested and type-checked.

The behaviour of each example is tested in ``examples/tests`` with the harness,
as an author would. Here: that every example has those tests, and that the
examples type-check against the installed ``haanim`` package with ``mypy`` and
``pyright``, which is what the package's type information is for.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from haanim.engine.automation_ids import automation_id as derive_automation_id

REPO_ROOT = Path(__file__).parents[2]
EXAMPLES = REPO_ROOT / "examples"
NAMES = sorted(path.name for path in EXAMPLES.iterdir() if (path / "main.py").is_file())
DESIGN = REPO_ROOT / "_design.md"


def test_the_examples() -> None:
    """Test the examples are the three the README lists."""
    assert NAMES == ["climate", "dashboard", "motion_light"]
    readme = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    for name in NAMES:
        assert f"`{name}/`" in readme


@pytest.mark.parametrize("name", NAMES)
class TestEachExample:
    """Every example is an automation folder as the design describes it."""

    def test_folder_name_is_its_id(self, name: str) -> None:
        """Test the folder name is already the automation ID, so the docs can use it."""
        assert derive_automation_id(name) == name

    def test_metadata(self, name: str) -> None:
        """Test metadata.json has the four fields."""
        metadata = json.loads((EXAMPLES / name / "metadata.json").read_text(encoding="utf-8"))
        assert sorted(metadata) == ["author", "description", "name", "version"]
        assert all(isinstance(value, str) and value for value in metadata.values())

    def test_has_harness_tests(self, name: str) -> None:
        """Test the example has a test file that uses the harness, outside the automation's folder."""
        tests = EXAMPLES / "tests" / f"test_{name}.py"
        source = tests.read_text(encoding="utf-8")
        assert "from haanim.testing import AutomationHarness" in source
        assert source.count("async def test_") >= 5
        assert list((EXAMPLES / name).rglob("test_*.py")) == []

    def test_mypy(self, name: str) -> None:
        """Test the example type-checks with mypy's default settings."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mypy",
                "--config-file=",
                "--no-incremental",
                str(EXAMPLES / name / "main.py"),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        assert result.returncode == 0, result.stdout[-3000:]


def test_pyright() -> None:
    """Test the examples and their tests type-check with pyright."""
    result = subprocess.run(
        [sys.executable, "-m", "pyright", str(EXAMPLES)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout[-3000:]
    assert "0 errors" in result.stdout


@pytest.mark.skipif(not DESIGN.is_file(), reason="the design document is not in this checkout")
def test_climate_is_the_designs_complete_example() -> None:
    """Test examples/climate is the Complete Example of the design, word for word."""
    design = DESIGN.read_text(encoding="utf-8")
    section = design[design.index("## Complete Example") :]
    code = section[section.index("```python\n") + len("```python\n") :]
    code = code[: code.index("```")]
    assert (EXAMPLES / "climate" / "main.py").read_text(encoding="utf-8") == code


def test_assets_of_the_dashboard() -> None:
    """Test the image the dashboard example shows is in its assets folder."""
    assert (EXAMPLES / "dashboard" / "assets" / "logo.svg").read_text(encoding="utf-8").startswith("<svg")
