"""Runs the JavaScript unit tests of the card and the panel as part of the suite.

The tests themselves are the ``*.test.mjs`` files next to this one; ``scripts/test-frontend.sh`` runs them
with node's test runner and its 80% coverage gate.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
UI = REPO_ROOT / "custom_components" / "haanim" / "ui"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_frontend_unit_tests() -> None:
    """Test the frontend unit tests pass and reach their coverage gate."""
    result = subprocess.run(
        [str(REPO_ROOT / "scripts" / "test-frontend.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]


def test_modules_the_integration_serves_exist() -> None:
    """Test the panel, the card and what they import are in the folder the integration serves."""
    assert sorted(path.name for path in UI.glob("*.js")) == [
        "haanim-card.js",
        "haanim-panel.js",
        "haanim-render.js",
    ]


@pytest.mark.parametrize("name", ["haanim-card.js", "haanim-panel.js"])
def test_no_markup_from_data_without_the_renderer(name: str) -> None:
    """Test the elements build HTML from data only through the rendering module, which escapes it."""
    source = (UI / name).read_text(encoding="utf-8")
    assert "from './haanim-render.js'" in source
    assert "eval(" not in source
    assert "document.write" not in source
