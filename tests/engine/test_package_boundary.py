"""Tests for the boundary between the ``haanim`` engine package and Home Assistant.

The engine package (``src/haanim``) must not depend on Home Assistant or on the
integration glue (``custom_components.haanim``). These tests fail if any engine
module imports either, anywhere, including inside functions and
``if TYPE_CHECKING:`` blocks.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "haanim"

FORBIDDEN_TOP_LEVEL = ("homeassistant", "custom_components")

# Engine module (relative to src/haanim) -> forbidden modules it imports.
# Empty since phase 3. It must stay empty: the engine reaches its host only through
# the protocols in haanim.interfaces.
SEAMS: dict[str, set[str]] = {}


def forbidden_imports(source: str) -> set[str]:
    """Return the forbidden modules imported anywhere in the given source.

    Every import statement counts, including those inside functions and
    ``if TYPE_CHECKING:`` blocks.

    Args:
        source: Python source code.

    Returns:
        Dotted names of imported modules whose top-level package is forbidden.
    """
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return {module for module in modules if module.split(".")[0] in FORBIDDEN_TOP_LEVEL}


def package_modules() -> list[str]:
    """Return every module of the engine package, relative to the package root."""
    return sorted(path.relative_to(PACKAGE_ROOT).as_posix() for path in PACKAGE_ROOT.rglob("*.py"))


class TestForbiddenImportsHelper:
    """Tests for the import scanner used by the boundary tests."""

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("import os\nimport json", set()),
            ("import homeassistant", {"homeassistant"}),
            ("import homeassistant.core as ha", {"homeassistant.core"}),
            ("from homeassistant.core import State", {"homeassistant.core"}),
            ("from custom_components.haanim.ha import state", {"custom_components.haanim.ha"}),
            ("def f():\n    from homeassistant.util import dt", {"homeassistant.util"}),
            (
                "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from homeassistant.core import State",
                {"homeassistant.core"},
            ),
            ("from . import homeassistant", set()),
            ("from .homeassistant import x", set()),
            ("import homeassistant_like", set()),
            ("text = 'import homeassistant'", set()),
        ],
    )
    def test_forbidden_imports(self, source: str, expected: set[str]) -> None:
        """Test the scanner finds forbidden imports at any nesting and nothing else."""
        assert forbidden_imports(source) == expected


class TestPackageBoundary:
    """The engine package imports Home Assistant only through the listed seams."""

    def test_package_has_modules(self) -> None:
        """Test the package is found where the tests expect it."""
        modules = package_modules()
        assert "__init__.py" in modules
        assert "engine/errors.py" in modules

    @pytest.mark.parametrize("module", package_modules())
    def test_module_imports_only_listed_seams(self, module: str) -> None:
        """Test a module's forbidden imports are exactly those recorded for it.

        Fails when a module gains a forbidden import, and also when a recorded
        seam has been removed from the code but not from SEAMS.
        """
        found = forbidden_imports((PACKAGE_ROOT / module).read_text(encoding="utf-8"))
        assert found == SEAMS.get(module, set())

    def test_seams_name_existing_modules(self) -> None:
        """Test SEAMS has no entries for modules that no longer exist."""
        assert set(SEAMS) <= set(package_modules())

    def test_no_empty_seam_entries(self) -> None:
        """Test a module with no remaining seams is removed from SEAMS."""
        assert all(SEAMS.values())


# Modules that cannot be imported on their own, first, in a fresh interpreter.
# Empty since phase 3, and it must stay empty.
NOT_STANDALONE: set[str] = set()


def dotted_name(module: str) -> str:
    """Convert a path relative to the package root into a dotted module name."""
    parts = ["haanim", *Path(module).with_suffix("").parts]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def all_dotted_modules() -> list[str]:
    """Return the dotted name of every module in the engine package."""
    return sorted(dotted_name(module) for module in package_modules())


class TestImportWithoutHomeAssistant:
    """Importing the package does not load Home Assistant or the integration."""

    @pytest.mark.parametrize(
        ("module", "expected"),
        [
            ("__init__.py", "haanim"),
            ("const.py", "haanim.const"),
            ("engine/__init__.py", "haanim.engine"),
            ("engine/triggers/base.py", "haanim.engine.triggers.base"),
        ],
    )
    def test_dotted_name(self, module: str, expected: str) -> None:
        """Test path to dotted-name conversion."""
        assert dotted_name(module) == expected

    def test_not_standalone_names_existing_modules(self) -> None:
        """Test NOT_STANDALONE has no entries for modules that no longer exist."""
        assert NOT_STANDALONE <= set(all_dotted_modules())

    @pytest.mark.parametrize("module", [m for m in all_dotted_modules() if m not in NOT_STANDALONE])
    def test_import_does_not_load_home_assistant(self, module: str) -> None:
        """Test importing a module first, in a fresh interpreter, leaves Home Assistant unloaded."""
        code = (
            "import sys\n"
            f"import {module}\n"
            "loaded = sorted(m for m in sys.modules if m.split('.')[0] in ('homeassistant', 'custom_components'))\n"
            "print(','.join(loaded))\n"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == ""

    def test_public_names(self) -> None:
        """Test the package exposes its version, ActionMode and the public errors."""
        import haanim  # pylint: disable=import-outside-toplevel
        from haanim.const import ActionMode  # pylint: disable=import-outside-toplevel
        from haanim.engine.errors import PUBLIC_ERRORS, HAAnimError  # pylint: disable=import-outside-toplevel

        assert haanim.__version__
        assert haanim.ActionMode is ActionMode
        assert haanim.HAAnimError is HAAnimError
        assert haanim.PUBLIC_ERRORS is PUBLIC_ERRORS
        assert {"ActionMode", "HAAnimError", "PUBLIC_ERRORS", "__version__"} <= set(haanim.__all__)


class TestEngineTestsWithoutHomeAssistant:
    """The engine test suite itself does not need Home Assistant."""

    def test_engine_tests_pass_with_home_assistant_blocked(self) -> None:
        """Test ``tests/engine`` passes in an interpreter where Home Assistant cannot be imported.

        Home Assistant, its pytest plugin and the integration are made unimportable
        before pytest starts, so any engine test that still depended on them would
        fail to collect or run.
        """
        repo_root = Path(__file__).parents[2]
        code = (
            "import sys\n"
            "for name in ('homeassistant', 'pytest_homeassistant_custom_component', 'custom_components'):\n"
            "    sys.modules[name] = None\n"
            "import pytest\n"
            "sys.exit(pytest.main([\n"
            "    'tests/engine', '-q', '-p', 'no:cacheprovider', '-o', 'addopts=', '-p', 'asyncio',\n"
            "    '--deselect', 'tests/engine/test_package_boundary.py::TestEngineTestsWithoutHomeAssistant',\n"
            "]))\n"
        )
        env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=False, cwd=repo_root, env=env
        )
        assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
        assert " passed" in result.stdout
        # Nothing is skipped for want of Home Assistant. One test compares an example with the design
        # document, which is not in every checkout, and is skipped without it.
        skipped = "skipped" in result.stdout.splitlines()[-1]
        assert skipped == (not (repo_root / "_design.md").is_file()), result.stdout[-500:]
