#!/usr/bin/env python3
"""Build the integration as it is released: with the engine in it.

The engine, the ``haanim`` package, is developed in ``src/haanim``. A release
of the integration carries a copy of it in ``custom_components/haanim/bundled``,
so that installing the integration is all it takes. This script makes that:

    uv run python scripts/build-integration.py                  # dist/haanim.zip, what HACS downloads
    uv run python scripts/build-integration.py --folder OUT     # also OUT/haanim, to copy by hand

The zip has the content of ``custom_components/haanim`` at its top, as HACS
expects of a release. To install by hand, copy the folder made with
``--folder`` to ``<config>/custom_components/haanim``.

Nothing in the repository is changed: the copy is made in the output only.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = REPO_ROOT / "custom_components" / "haanim"
ENGINE = REPO_ROOT / "src" / "haanim"
BUNDLED = "bundled"
"""The folder of the integration the engine is copied into; see ``engine_path.py``."""

LEFT_OUT = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", BUNDLED)


def assemble(target: Path) -> Path:
    """Make the released integration in ``target``: the integration, and the engine in its ``bundled`` folder.

    Returns:
        The folder made.
    """
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(INTEGRATION, target, ignore=LEFT_OUT)
    shutil.copytree(ENGINE, target / BUNDLED / "haanim", ignore=LEFT_OUT)
    return target


def archive(folder: Path, destination: Path) -> Path:
    """Zip the content of a folder, the files in the order of their names so that the same input gives the same zip.

    Returns:
        The zip made.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(folder).as_posix())
    return destination


def build(output: Path, folder: Path | None = None) -> Path:
    """Build the release zip, and the unpacked integration as well if a folder is given.

    Returns:
        The zip made.
    """
    with tempfile.TemporaryDirectory() as staging:
        assembled = assemble(Path(staging) / "haanim")
        made = archive(assembled, output)
        if folder is not None:
            assemble(folder / "haanim")
    return made


def main(arguments: list[str]) -> int:
    """Run from the command line."""
    parser = argparse.ArgumentParser(description="Build the HAAnim integration with the engine in it.")
    parser.add_argument(
        "--output", type=Path, default=REPO_ROOT / "dist" / "haanim.zip", help="the zip to write"
    )
    parser.add_argument("--folder", type=Path, help="also write the integration, unpacked, as FOLDER/haanim")
    options = parser.parse_args(arguments)
    made = build(options.output, options.folder)
    print(f"Built {made}")
    if options.folder is not None:
        print(f"Built {options.folder / 'haanim'}: copy it to <config>/custom_components/haanim")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
