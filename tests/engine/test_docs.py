"""Tests that the code in the documentation runs.

Every Python block of the automation guide and of the README is loaded as an
automation with the harness: blocks with decorators as they are, and loose
statements as the body of an action, which is then called. A name that does not
exist, a decorator argument that is not valid or a call that fails shows up here.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Any

import pytest

import haanim
from haanim.testing import AutomationHarness

REPO_ROOT = Path(__file__).parents[2]
DOCUMENTS = [REPO_ROOT / "docs" / "AUTOMATIONS.md", REPO_ROOT / "README.md"]

# Everything an automation can import from haanim, so that fragments need not repeat their imports
HEADER = (
    "from haanim import ("
    + ", ".join(
        name
        for name in haanim.__all__
        if name not in ("__version__", "PUBLIC_ERRORS", "RUNTIME_ONLY", "LoggerWrapper", "hass")
    )
    + ")\n"
)

STATES: dict[str, Any] = {
    "sensor.temperature": "21.5",
    "sensor.3d_printer": "printing",
    "light.kitchen": ("on", {"brightness": 200}),
    "light.hall": "off",
    "light.porch": "off",
    "binary_sensor.door": "off",
    "binary_sensor.motion": "off",
    "sun.sun": "above_horizon",
    "person.john": "home",
    "weather.home": "sunny",
}


def blocks() -> list[tuple[str, str]]:
    """Return every automation code block of the documents as ``(where, code)``."""
    found: list[tuple[str, str]] = []
    for document in DOCUMENTS:
        text = document.read_text(encoding="utf-8")
        for index, match in enumerate(re.finditer(r"```python\n(.*?)```", text, re.DOTALL)):
            code = match.group(1)
            if "haanim.testing" in code:
                continue  # a test, not an automation: the harness tests cover those
            line = text[: match.start()].count("\n") + 2
            found.append((f"{document.name}:{line}", code))
    return found


def as_automation(code: str) -> tuple[str, bool]:
    """Turn a block into the source of a main.py; the flag says whether it became the body of an action."""
    is_fragment = not re.search(r"^(@|def |async def )", code, re.MULTILINE)
    if is_fragment:
        body = "\n".join(line for line in code.splitlines() if not line.startswith("from haanim import"))
        return HEADER + "\n@action\nasync def fragment(event):\n" + textwrap.indent(body, "    ") + "\n", True
    # Decorator lines that stand alone in the guide ("@on_state(...)" as an illustration) get a function
    code = re.sub(
        r"^(@\w+\(.*\))\n(?!@|def |async def )",
        r"\1\ndef illustration(event): ...\n",
        code,
        flags=re.MULTILINE,
    )
    code = re.sub(
        r"^(@\w+\(.*\))\Z", r"\1\ndef illustration(event): ...\n", code.rstrip() + "\n", flags=re.MULTILINE
    )
    return HEADER + code, False


BLOCKS = blocks()


def test_the_documents_have_code() -> None:
    """Test the guide and the README are found and have automation code in them."""
    assert len(BLOCKS) >= 12
    assert {where.split(":")[0] for where, _ in BLOCKS} == {"AUTOMATIONS.md", "README.md"}


@pytest.mark.parametrize(("where", "code"), BLOCKS, ids=[where for where, _ in BLOCKS])
async def test_code_block_runs(tmp_path: Path, where: str, code: str) -> None:
    """Test a code block loads and starts as an automation, and loose statements run without an error."""
    source, is_fragment = as_automation(code)
    folder = tmp_path / "documented"
    (folder / "assets").mkdir(parents=True)
    (folder / "main.py").write_text(source, encoding="utf-8")
    assets = {"phrases.json": "[]", "chime.mp3": b"ID3", "logo.png": b"\x89PNG"}

    async with AutomationHarness(
        folder, states=STATES, assets=assets, variables={"count": 1}, now="2025-01-06 12:00:00"
    ) as automation:
        assert automation.state == "on", automation.error
        automation.stub_automation("notifications", send_message="sent")
        automation.stub_automation("irrigation")
        automation.stub_service("weather.get_forecasts", response={"weather.home": {"forecast": []}})
        if is_fragment:
            import asyncio  # pylint: disable=import-outside-toplevel

            call = asyncio.ensure_future(automation.call("fragment"))
            # Fragments that sleep or wait get their time
            for _ in range(20):
                if call.done():
                    break
                await automation.advance_time(seconds=60)
            assert call.done(), f"{where} did not finish"
            call.result()
