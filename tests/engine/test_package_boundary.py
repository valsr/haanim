"""Tests for the boundary between the ``haanim`` engine package and Home Assistant.

The engine package (``src/haanim``) must not depend on Home Assistant or on the
integration glue (``custom_components.haanim``). The imports that still cross that
boundary are listed in ``SEAMS``; phase 3 of the implementation plan removes them,
and this list must then be empty.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "haanim"

FORBIDDEN_TOP_LEVEL = ("homeassistant", "custom_components")

# Engine module (relative to src/haanim) -> forbidden modules it still imports.
# Do not add to this list. Remove entries as the imports are replaced by interfaces.
SEAMS: dict[str, set[str]] = {
    "engine/action_pool.py": {"custom_components.haanim.config"},
    "engine/automation_context.py": {"homeassistant.core"},
    "engine/constraints/checker.py": {"custom_components.haanim.ha.state"},
    "engine/expression_eval.py": {"homeassistant.core"},
    "engine/haanim_api.py": {
        "custom_components.haanim.automation_manager",
        "homeassistant.core",
        "homeassistant.exceptions",
    },
    "engine/triggers/base.py": {
        "custom_components.haanim.ha.events",
        "custom_components.haanim.ha.state",
        "homeassistant.core",
        "homeassistant.helpers.sun",
        "homeassistant.util",
    },
    "engine/triggers/cron_trigger.py": {
        "custom_components.haanim.ha.events",
        "custom_components.haanim.ha.state",
        "homeassistant.core",
    },
    "engine/triggers/event_trigger.py": {
        "custom_components.haanim.ha.events",
        "custom_components.haanim.ha.state",
        "homeassistant.core",
    },
    "engine/triggers/interval_trigger.py": {
        "custom_components.haanim.ha.events",
        "custom_components.haanim.ha.state",
        "homeassistant.core",
    },
    "engine/triggers/manager.py": {
        "custom_components.haanim.ha.events",
        "custom_components.haanim.ha.state",
        "homeassistant.const",
        "homeassistant.core",
    },
    "engine/triggers/state_trigger.py": {
        "custom_components.haanim.ha.events",
        "custom_components.haanim.ha.state",
        "homeassistant.core",
    },
    "engine/triggers/time_trigger.py": {
        "custom_components.haanim.ha.events",
        "custom_components.haanim.ha.state",
        "homeassistant.core",
        "homeassistant.helpers.sun",
        "homeassistant.util",
    },
    "events.py": {"homeassistant.core"},
}


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


# Modules that cannot yet be imported on their own. Each either loads Home Assistant
# through a seam, or fails with a circular import because a seam leads back into the
# integration, which imports the engine again. They import correctly only after
# ``custom_components.haanim`` has been imported first, which is what Home Assistant
# and this test suite do. Do not add to this list; phase 3 empties it.
NOT_STANDALONE: set[str] = {
    "haanim.engine.action_pool",
    "haanim.engine.automation_context",
    "haanim.engine.decorators",
    "haanim.engine.expression_eval",
    "haanim.engine.haanim_api",
    "haanim.engine.triggers",
    "haanim.engine.triggers.base",
    "haanim.engine.triggers.cron_trigger",
    "haanim.engine.triggers.event_trigger",
    "haanim.engine.triggers.interval_trigger",
    "haanim.engine.triggers.manager",
    "haanim.engine.triggers.state_trigger",
    "haanim.engine.triggers.time_trigger",
    "haanim.events",
}


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

        assert haanim.__version__ == "0.1.0"
        assert haanim.ActionMode is ActionMode
        assert haanim.HAAnimError is HAAnimError
        assert haanim.PUBLIC_ERRORS is PUBLIC_ERRORS
        assert set(haanim.__all__) == {"ActionMode", "HAAnimError", "PUBLIC_ERRORS", "__version__"}
