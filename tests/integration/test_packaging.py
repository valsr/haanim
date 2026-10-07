"""Tests for the packaging of the integration: one version, and the engine a release carries.

See "Packaging" in the design.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from importlib.metadata import requires
from pathlib import Path
from typing import Any

import pytest
from packaging.requirements import Requirement

import haanim
from custom_components.haanim import engine_path
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
    """The integration does not require the package: a release carries the engine, and Home Assistant has the rest."""

    def test_manifest_does_not_require_the_package(self) -> None:
        """Test installing the integration installs no haanim package."""
        assert not any(requirement.startswith("haanim") for requirement in MANIFEST["requirements"])

    def test_package_does_not_require_home_assistant(self) -> None:
        """Test installing the package does not install Home Assistant."""
        names = [
            requirement.split(">")[0].split("=")[0].strip().lower()
            for requirement in PROJECT["project"]["dependencies"]
        ]
        assert names == ["cronsim", "python-slugify"]

    def test_home_assistant_has_what_the_engine_needs(self) -> None:
        """Test the manifest requires nothing: Home Assistant itself requires what the engine needs."""
        assert MANIFEST["requirements"] == []
        home_assistant = {
            Requirement(requirement).name: Requirement(requirement).specifier
            for requirement in requires("homeassistant") or []
        }
        for dependency in PROJECT["project"]["dependencies"]:
            needed = Requirement(dependency)
            pinned = next(iter(home_assistant[needed.name])).version
            assert needed.specifier.contains(pinned)

    def test_wheel_is_the_engine_package(self) -> None:
        """Test the wheel is built from src/haanim, which has py.typed."""
        assert PROJECT["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/haanim"]
        assert (REPO_ROOT / "src" / "haanim" / "py.typed").is_file()


def load_script(name: str) -> Any:
    """Load a script of the repository as a module."""
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPO_ROOT / "scripts" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestEnginePath:
    """The integration uses the engine bundled with it, else the installed package."""

    def test_a_checkout_has_no_bundled_engine(self) -> None:
        """Test the repository itself carries no copy of the engine: the source is src/haanim."""
        assert not engine_path.BUNDLED.exists()
        assert engine_path.BUNDLED == REPO_ROOT / "custom_components" / "haanim" / "bundled"
        assert "custom_components/haanim/bundled/" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    def test_without_a_bundled_engine_nothing_changes(self, tmp_path: Path) -> None:
        """Test the import path is left alone when there is no bundled engine."""
        path = ["a", "b"]
        assert engine_path.use_bundled_engine(tmp_path / "bundled", path) is False
        (tmp_path / "bundled" / "haanim").mkdir(parents=True)
        assert (
            engine_path.use_bundled_engine(tmp_path / "bundled", path) is False
        ), "a folder without a package"
        assert path == ["a", "b"]

    def test_a_bundled_engine_comes_first(self, tmp_path: Path) -> None:
        """Test the bundled engine is put before everything else, once."""
        bundled = tmp_path / "bundled"
        (bundled / "haanim").mkdir(parents=True)
        (bundled / "haanim" / "__init__.py").write_text("", encoding="utf-8")
        path = ["a", str(bundled), "b"]
        assert engine_path.use_bundled_engine(bundled, path) is True
        assert engine_path.use_bundled_engine(bundled, path) is True
        assert path == [str(bundled), "a", "b"]

    def test_the_engine_found_is_this_one(self) -> None:
        """Test the engine in use is found, and passes the check against the manifest."""
        assert engine_path.engine_version() == haanim.__version__
        engine_path.check_engine(
            REPO_ROOT / "custom_components" / "haanim" / "manifest.json", haanim.__version__
        )

    def test_no_engine(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test a missing engine is reported with what to do about it."""
        monkeypatch.setattr(engine_path.importlib.util, "find_spec", lambda name: None)
        assert engine_path.engine_version() is None
        with pytest.raises(ImportError, match="was not found. Install HAAnim from a release"):
            engine_path.check_engine(tmp_path / "manifest.json", None)

    def test_engine_of_another_version(self, tmp_path: Path) -> None:
        """Test an engine that is not the integration's version is refused, naming both versions."""
        manifest = tmp_path / "manifest.json"
        manifest.write_text('{"version": "9.9.9"}', encoding="utf-8")
        with pytest.raises(
            ImportError, match="is version 9.9.9, but the 'haanim' package found is version 0.0.1"
        ):
            engine_path.check_engine(manifest, "0.0.1")
        engine_path.check_engine(manifest, "9.9.9")


class TestRelease:
    """What scripts/build-integration.py builds is the integration with the engine in it."""

    @pytest.fixture(scope="class")
    def built(self, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
        """The release zip and the unpacked integration, built once."""
        out = tmp_path_factory.mktemp("release")
        script = load_script("build-integration")
        assert script.main(["--output", str(out / "haanim.zip"), "--folder", str(out / "unpacked")]) == 0
        return out / "haanim.zip", out / "unpacked" / "haanim"

    def test_zip_is_what_hacs_downloads(self, built: tuple[Path, Path]) -> None:
        """Test hacs.json names the zip, which has the integration at its top and the engine in bundled/."""
        archive, _ = built
        hacs = json.loads((REPO_ROOT / "hacs.json").read_text(encoding="utf-8"))
        assert (hacs["zip_release"], hacs["filename"]) == (True, archive.name)
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
        for wanted in (
            "manifest.json",
            "__init__.py",
            "engine_path.py",
            "services.yaml",
            "ui/haanim-card.js",
            "translations/en.json",
            "bundled/haanim/__init__.py",
            "bundled/haanim/py.typed",
            "bundled/haanim/engine/card.py",
        ):
            assert wanted in names, wanted
        assert names == sorted(names)
        assert not [name for name in names if "__pycache__" in name or name.endswith(".pyc")]

    def test_the_engine_in_it_is_the_source(self, built: tuple[Path, Path]) -> None:
        """Test every file of src/haanim is in the release unchanged, and nothing else."""
        _, folder = built
        source = REPO_ROOT / "src" / "haanim"

        def files(root: Path) -> dict[str, bytes]:
            return {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts
            }

        assert files(folder / "bundled" / "haanim") == files(source)

    def test_the_integration_in_it_is_the_source(self, built: tuple[Path, Path]) -> None:
        """Test the rest of the release is custom_components/haanim as it is."""
        _, folder = built
        integration = REPO_ROOT / "custom_components" / "haanim"
        for name in ("manifest.json", "__init__.py", "ui/haanim-render.js"):
            assert (folder / name).read_bytes() == (integration / name).read_bytes()

    def test_building_again_replaces_the_folder(self, built: tuple[Path, Path]) -> None:
        """Test a file left in the output folder from before is gone after building again."""
        archive, folder = built
        (folder / "stale.txt").write_text("old", encoding="utf-8")
        load_script("build-integration").build(archive, folder.parent)
        assert not (folder / "stale.txt").exists()

    def test_released_integration_uses_its_own_engine(self, built: tuple[Path, Path], tmp_path: Path) -> None:
        """Test the released integration imports the engine bundled with it, also where the package is installed."""
        _, folder = built
        config = tmp_path / "config"
        shutil.copytree(folder, config / "custom_components" / "haanim")
        (config / "custom_components" / "__init__.py").write_text("", encoding="utf-8")
        check = (
            "import sys; sys.path.insert(0, sys.argv[1])\n"
            "import custom_components.haanim, haanim\n"
            "print(custom_components.haanim.__file__); print(haanim.__file__)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", check, str(config)],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        integration, engine = result.stdout.strip().splitlines()[-2:]
        assert integration.startswith(str(config))
        assert engine == str(config / "custom_components" / "haanim" / "bundled" / "haanim" / "__init__.py")


class TestPublishing:
    """What HACS, Home Assistant and PyPI ask of the repository."""

    def test_hacs_json_has_only_what_hacs_knows(self) -> None:
        """Test hacs.json has no key the HACS validation refuses."""
        hacs = json.loads((REPO_ROOT / "hacs.json").read_text(encoding="utf-8"))
        assert set(hacs) == {"name", "content_in_root", "homeassistant", "zip_release", "filename"}

    def test_manifest_is_what_hassfest_accepts(self) -> None:
        """Test the manifest has what a custom integration must state, with its keys in hassfest's order."""
        for key in ("codeowners", "documentation", "integration_type", "issue_tracker", "version"):
            assert MANIFEST[key]
        assert list(MANIFEST) == ["domain", "name", *sorted(set(MANIFEST) - {"domain", "name"})]

    @pytest.mark.parametrize(("name", "size"), [("icon.png", 256), ("icon@2x.png", 512)])
    def test_brand_icon(self, name: str, size: int) -> None:
        """Test the integration brings its icon, a square PNG of the size Home Assistant asks for."""
        data = (REPO_ROOT / "custom_components" / "haanim" / "brand" / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert (int.from_bytes(data[16:20]), int.from_bytes(data[20:24])) == (size, size)

    def test_package_metadata(self) -> None:
        """Test the package names its author and its pages, and puts only itself in the source archive."""
        project = PROJECT["project"]
        assert project["authors"] == [{"name": "valsr"}]
        assert project["urls"]["Documentation"] == MANIFEST["documentation"]
        assert PROJECT["tool"]["hatch"]["build"]["targets"]["sdist"]["include"] == [
            "/src/haanim",
            "/README.md",
            "/LICENSE",
        ]

    def test_readme_links_work_outside_the_repository(self) -> None:
        """Test the README, which PyPI shows too, links by full addresses only."""
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert re.findall(r"\]\((?!https://|#)[^)]*\)", readme) == []
