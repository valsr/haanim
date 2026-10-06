"""Tests that the built package installs and works in an environment without Home Assistant.

See "Packaging" in the design. The wheel is built from this repository and
installed into a fresh virtual environment; a harness test of the design's
Complete Example then runs there.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import haanim

REPO_ROOT = Path(__file__).parents[2]

CHECK = """
import importlib.util, sys
import haanim
from haanim import action, on_state, StateEvent, HAAnim
from haanim.testing import AutomationHarness
assert importlib.util.find_spec("homeassistant") is None, "Home Assistant is installed"
assert importlib.util.find_spec("custom_components") is None
assert "homeassistant" not in sys.modules
import asyncio

async def main():
    async with AutomationHarness(sys.argv[1]) as automation:
        automation.set_state("sensor.temperature", "25")
        automation.set_state("sensor.temperature", "31")
        await automation.wait_idle()
        assert automation.service_calls("notify.mobile_app")[0].data["message"].startswith("High temperature")
        assert automation.get_variable("alert_count") == 1

asyncio.run(main())
print(haanim.__version__, haanim.__file__)
"""


def run(*command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a command and fail the test with its output if it fails."""
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, timeout=300)
    assert result.returncode == 0, f"{' '.join(command)}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
    return result


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_wheel_installs_and_runs_without_home_assistant(tmp_path: Path) -> None:
    """Test the wheel has py.typed, installs without Home Assistant, and the harness runs from it."""
    dist = tmp_path / "dist"
    run("uv", "build", "--wheel", "--out-dir", str(dist), str(REPO_ROOT), cwd=tmp_path)
    (wheel,) = dist.glob("haanim-*.whl")
    assert wheel.name == f"haanim-{haanim.__version__}-py3-none-any.whl"

    listing = run("python", "-m", "zipfile", "--list", str(wheel), cwd=tmp_path).stdout
    assert "haanim/py.typed" in listing
    assert "haanim/testing/harness.py" in listing
    assert "custom_components" not in listing
    assert "tests/" not in listing

    environment = tmp_path / "venv"
    run("uv", "venv", str(environment), cwd=tmp_path)
    python = str(environment / "bin" / "python")
    run("uv", "pip", "install", "--python", python, str(wheel), cwd=tmp_path)

    installed = run("uv", "pip", "list", "--python", python, cwd=tmp_path).stdout.lower()
    assert "haanim" in installed
    assert "homeassistant" not in installed

    script = tmp_path / "check.py"
    script.write_text(CHECK, encoding="utf-8")
    output = run(python, str(script), str(REPO_ROOT / "examples" / "climate"), cwd=tmp_path).stdout
    assert output.startswith(haanim.__version__)
    assert str(environment) in output, "the harness ran from the installed package, not from the repository"
