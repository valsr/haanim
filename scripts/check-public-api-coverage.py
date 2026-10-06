#!/usr/bin/env python3
"""Fail unless the public automation-facing API is covered at 100%.

The design asks for 80% line coverage overall and 100% for everything an
automation uses: ``haa``, the decorators, the event objects and the errors.
This reads ``coverage.xml`` as the test run writes it and checks every line and
every branch of the modules listed in ``PUBLIC_API``.

Usage: scripts/check-public-api-coverage.py [coverage.xml]
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PUBLIC_API = (
    "src/haanim/__init__.py",
    "src/haanim/const.py",
    "src/haanim/events.py",
    "src/haanim/entity.py",
    "src/haanim/types.py",
    "src/haanim/engine/assets.py",
    "src/haanim/engine/card.py",
    "src/haanim/engine/card_checks.py",
    "src/haanim/engine/card_elements.py",
    "src/haanim/engine/decorators.py",
    "src/haanim/engine/errors.py",
    "src/haanim/engine/haanim_api.py",
    "src/haanim/engine/haanim_module.py",
    "src/haanim/engine/logging_wrapper.py",
    "src/haanim/engine/variables.py",
)
"""The modules behind what an automation imports from ``haanim``."""


def uncovered(report: Path) -> dict[str, list[str]]:
    """Return what is not fully covered in each public module, by module.

    A module that the report does not mention at all is reported as missing.

    Args:
        report: Path of a Cobertura ``coverage.xml``.
    """
    root = ET.parse(report).getroot()
    sources = [Path(source.text or "") for source in root.iter("source")]
    seen: dict[str, list[str]] = {}
    for cls in root.iter("class"):
        filename = cls.get("filename", "")
        candidates = {Path(filename).as_posix(), *((source / filename).as_posix() for source in sources)}
        module = next((name for name in PUBLIC_API if any(path.endswith(name) for path in candidates)), None)
        if module is None:
            continue
        problems = seen.setdefault(module, [])
        for line in cls.iter("line"):
            number = line.get("number", "?")
            if line.get("hits") == "0":
                problems.append(f"line {number} is not executed")
            elif line.get("branch") == "true" and not (line.get("condition-coverage") or "").startswith(
                "100%"
            ):
                problems.append(f"line {number}: branches {line.get('condition-coverage')}")
    for module in PUBLIC_API:
        seen.setdefault(module, ["not in the coverage report"])
    return {module: problems for module, problems in seen.items() if problems}


def main(arguments: list[str]) -> int:
    """Check the report and print what is missing. Returns the exit code."""
    report = Path(arguments[0]) if arguments else Path("coverage.xml")
    if not report.is_file():
        print(f"No coverage report at {report}; run the tests first", file=sys.stderr)
        return 2
    problems = uncovered(report)
    for module in sorted(problems):
        for problem in problems[module]:
            print(f"{module}: {problem}", file=sys.stderr)
    if problems:
        print(f"Public API is not at 100%: {len(problems)} of {len(PUBLIC_API)} modules", file=sys.stderr)
        return 1
    print(f"Public API at 100%: {len(PUBLIC_API)} modules")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
