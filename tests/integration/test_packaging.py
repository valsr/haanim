"""Tests for the packaging of the integration: one version, and the package it requires.

See "Packaging" in the design.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import haanim
from custom_components.haanim.const import VERSION

REPO_ROOT = Path(__file__).parents[2]
MANIFEST = json.loads(
    (REPO_ROOT / "custom_components" / "haanim" / "manifest.json").read_text(encoding="utf-8")
)
PROJECT = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


class TestOneVersion:
    """The package and the integration have the same version, from one place."""

    def test_integration_uses_the_packages_version(self) -> None:
        """Test the integration's VERSION is the package's __version__."""
        assert VERSION == haanim.__version__

    def test_manifest_version(self) -> None:
        """Test manifest.json, which cannot import, states the same version."""
        assert MANIFEST["version"] == haanim.__version__

    def test_project_version_is_read_from_the_package(self) -> None:
        """Test pyproject.toml takes the version from the package instead of repeating it."""
        assert "version" not in PROJECT["project"]
        assert PROJECT["project"]["dynamic"] == ["version"]
        assert PROJECT["tool"]["hatch"]["version"]["path"] == "src/haanim/__init__.py"


class TestRequirement:
    """The integration lists the package, pinned to its own version."""

    def test_manifest_requires_the_package_at_its_version(self) -> None:
        """Test the only requirement is the haanim package at exactly this version."""
        assert MANIFEST["requirements"] == [f"haanim=={haanim.__version__}"]

    def test_package_does_not_require_home_assistant(self) -> None:
        """Test installing the package does not install Home Assistant."""
        names = [
            requirement.split(">")[0].split("=")[0].strip().lower()
            for requirement in PROJECT["project"]["dependencies"]
        ]
        assert names == ["croniter", "python-slugify"]

    def test_what_the_integration_needs_comes_with_the_package(self) -> None:
        """Test the engine's own requirements are the package's, not repeated in the manifest."""
        assert not any(
            requirement.startswith(("croniter", "python-slugify")) for requirement in MANIFEST["requirements"]
        )

    def test_wheel_is_the_engine_package(self) -> None:
        """Test the wheel is built from src/haanim, which has py.typed."""
        assert PROJECT["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/haanim"]
        assert (REPO_ROOT / "src" / "haanim" / "py.typed").is_file()
