"""Where the integration gets the HAAnim engine, the ``haanim`` package, from.

The engine is developed as a package of its own (``src/haanim`` in the
repository). A released integration carries a copy of it, in ``bundled/``
next to this file, so that installing the integration is all it takes: no
package has to be installed into Home Assistant.

- With a bundled engine, that one is used, whatever else is installed: it is
  the engine this integration was released with.
- Without one, as in a checkout of the repository, the installed ``haanim``
  package is used (``pip install -e .``), which is the same source.

This module is imported first by the integration, before anything imports
``haanim``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

BUNDLED = Path(__file__).parent / "bundled"
"""The folder a released integration has its copy of the ``haanim`` package in."""

MISSING = (
    "The HAAnim engine (the 'haanim' package) was not found. Install HAAnim from a release, which has the "
    "engine in it, or install the package into Home Assistant's Python environment: pip install haanim"
)


def use_bundled_engine(bundled: Path = BUNDLED, path: list[str] | None = None) -> bool:
    """Put the bundled engine first among the places Python imports from, if there is one.

    Args:
        bundled: The folder that has the ``haanim`` package in it.
        path: The import path to change; ``sys.path`` if omitted.

    Returns:
        Whether there is a bundled engine.
    """
    places = sys.path if path is None else path
    if not (bundled / "haanim" / "__init__.py").is_file():
        return False
    entry = str(bundled)
    if entry in places:
        places.remove(entry)
    places.insert(0, entry)
    return True


def check_engine(manifest: Path, engine_version: str | None) -> None:
    """Check that there is an engine and that it is the integration's version.

    Args:
        manifest: The integration's ``manifest.json``, which states its version.
        engine_version: The version of the ``haanim`` package found; None if none was.

    Raises:
        ImportError: If there is no engine, or it is of another version.
    """
    if engine_version is None:
        raise ImportError(MISSING)
    wanted = json.loads(manifest.read_text(encoding="utf-8"))["version"]
    if engine_version != wanted:
        raise ImportError(
            f"The HAAnim integration is version {wanted}, but the 'haanim' package found is version "
            f"{engine_version}. Install HAAnim from a release, or install the matching package: "
            f"pip install haanim=={wanted}"
        )


def engine_version() -> str | None:
    """Return the version of the ``haanim`` package Python finds, or None if it finds none."""
    if importlib.util.find_spec("haanim") is None:
        return None
    import haanim  # pylint: disable=import-outside-toplevel

    return haanim.__version__


use_bundled_engine()
check_engine(Path(__file__).parent / "manifest.json", engine_version())
