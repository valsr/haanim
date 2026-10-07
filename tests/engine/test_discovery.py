"""Tests for finding automations in the automations folder."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from haanim.engine.automation_ids import REASON_COLLISION, REASON_EMPTY, RejectedFolder
from haanim.engine.discovery import (
    ISSUE_EMPTY_ID,
    ISSUE_ID_COLLISION,
    DiscoveredAutomation,
    Discovery,
    FolderIssues,
    discover,
    last_modified,
    source_files,
    watched_files,
)
from haanim.engine.errors import AutomationSecurityError, AutomationSyntaxError, HAAnimError
from haanim.testing import FakeClock, FakeFileSystem, FakeIssueReporter, make_host
from tests.engine.helpers import automation_file, load_and_run, make_context

ROOT = Path("/config/haanim/automations")


def file_system(*paths: str, clock: FakeClock | None = None) -> FakeFileSystem:
    """Build an in-memory file system with empty files at the given paths below the root."""
    files = FakeFileSystem(clock)
    for path in paths:
        files.write(ROOT / path, "")
    return files


class TestDiscover:
    """A folder with a ``main.py`` is an automation."""

    async def test_folders_with_main(self) -> None:
        """Each folder that directly contains main.py is found, with its ID."""
        files = file_system("lights/main.py", "Heating/main.py")

        discovery = await discover(files, ROOT)

        assert discovery.automations == [
            DiscoveredAutomation("heating", ROOT / "Heating"),
            DiscoveredAutomation("lights", ROOT / "lights"),
        ]
        assert discovery.rejected == []
        assert discovery.automations[0].main == ROOT / "Heating" / "main.py"

    async def test_ascending_order_of_id(self) -> None:
        """Automations come in ascending order of ID, not of folder name."""
        files = file_system(
            "Zeta/main.py", "alpha/main.py", "Mid/main.py", "3d printer/main.py", "_beta/main.py"
        )

        discovery = await discover(files, ROOT)

        assert [found.automation_id for found in discovery.automations] == [
            "3d_printer",
            "alpha",
            "beta",
            "mid",
            "zeta",
        ]
        assert [found.folder.name for found in discovery.automations] == [
            "3d printer",
            "alpha",
            "_beta",
            "Mid",
            "Zeta",
        ]

    async def test_flat_files_are_not_automations(self) -> None:
        """A Python file directly in the automations folder is ignored."""
        files = file_system("lights.py", "main.py", "heating/main.py")

        discovery = await discover(files, ROOT)

        assert [found.automation_id for found in discovery.automations] == ["heating"]

    async def test_folder_without_main_is_ignored(self) -> None:
        """A folder is only an automation if main.py is directly in it."""
        files = file_system(
            "no_main/helper.py",
            "nested/inner/main.py",
            "only_metadata/metadata.json",
            "assets_only/assets/a.png",
        )

        assert await discover(files, ROOT) == Discovery()

    async def test_main_must_be_a_file_named_main_py(self) -> None:
        """Other spellings and a folder called main.py do not count."""
        files = file_system("upper/Main.py", "other/main.txt", "folder/main.py/x.py")

        assert (await discover(files, ROOT)).automations == []

    async def test_missing_automations_folder(self) -> None:
        """A folder that does not exist has no automations."""
        assert await discover(FakeFileSystem(), ROOT) == Discovery()

    async def test_empty_automations_folder(self) -> None:
        """A folder with nothing usable in it has no automations."""
        assert await discover(file_system("readme.txt"), ROOT) == Discovery()

    async def test_rejected_folders(self) -> None:
        """Folders that cannot be loaded because of their name are listed with the reason."""
        files = file_system("My Automation/main.py", "my-automation/main.py", "---/main.py", "lights/main.py")

        discovery = await discover(files, ROOT)

        assert [found.folder.name for found in discovery.automations] == ["lights", "My Automation"]
        assert discovery.rejected == [
            RejectedFolder("---", REASON_EMPTY),
            RejectedFolder("my-automation", REASON_COLLISION, "my_automation", "My Automation"),
        ]

    async def test_folder_without_main_does_not_collide(self) -> None:
        """Only folders that are automations take part in ID assignment."""
        files = file_system("Lights/readme.txt", "lights/main.py")

        discovery = await discover(files, ROOT)

        assert [found.folder.name for found in discovery.automations] == ["lights"]
        assert discovery.rejected == []

    async def test_other_folders_next_to_automations(self) -> None:
        """Folders such as storage or caches in the automations folder are ignored."""
        files = file_system(".storage/haanim/lights.json", "__pycache__/x.pyc", "lights/main.py")

        assert [found.automation_id for found in (await discover(files, ROOT)).automations] == ["lights"]


class TestSourceFiles:
    """The Python files of an automation."""

    async def test_main_first_then_sorted(self) -> None:
        """main.py comes first, the rest in path order."""
        files = file_system("auto/zeta.py", "auto/main.py", "auto/alpha.py")

        found = await source_files(files, ROOT / "auto")

        assert [path.name for path in found] == ["main.py", "alpha.py", "zeta.py"]

    async def test_sub_folders_are_searched(self) -> None:
        """Files in packages of the automation are included."""
        files = file_system(
            "auto/main.py", "auto/scenes/__init__.py", "auto/scenes/evening.py", "auto/a/b/c.py"
        )

        found = await source_files(files, ROOT / "auto")

        assert [path.relative_to(ROOT / "auto").as_posix() for path in found] == [
            "main.py",
            "a/b/c.py",
            "scenes/__init__.py",
            "scenes/evening.py",
        ]

    async def test_only_python_files(self) -> None:
        """Other files are not source files."""
        files = file_system(
            "auto/main.py", "auto/metadata.json", "auto/notes.txt", "auto/data.pyc", "auto/x.py.bak"
        )

        assert [path.name for path in await source_files(files, ROOT / "auto")] == ["main.py"]

    async def test_assets_and_caches_are_not_searched(self) -> None:
        """Nothing in assets, hidden folders or __pycache__ is automation code."""
        files = file_system(
            "auto/main.py",
            "auto/assets/script.py",
            "auto/assets/deep/more.py",
            "auto/__pycache__/main.py",
            "auto/.git/hook.py",
            "auto/lib/assets/kept.py",
        )

        found = await source_files(files, ROOT / "auto")

        assert [path.relative_to(ROOT / "auto").as_posix() for path in found] == [
            "main.py",
            "lib/assets/kept.py",
        ]

    async def test_watched_files_include_metadata(self) -> None:
        """A change to metadata.json also reloads the automation."""
        files = file_system("auto/main.py", "auto/helper.py", "auto/metadata.json", "auto/assets/a.png")

        watched = await watched_files(files, ROOT / "auto")

        assert [path.name for path in watched] == ["main.py", "helper.py", "metadata.json"]

    async def test_watched_files_without_metadata(self) -> None:
        """Without a metadata file only the sources are watched."""
        files = file_system("auto/main.py")

        assert [path.name for path in await watched_files(files, ROOT / "auto")] == ["main.py"]

    async def test_last_modified_is_the_latest_change(self) -> None:
        """The automation's modification time is that of its most recently changed file."""
        clock = FakeClock()
        files = file_system("auto/main.py", clock=clock)
        first = clock.now()
        assert await last_modified(files, ROOT / "auto") == first

        await clock.advance(seconds=60)
        files.write(ROOT / "auto" / "helper.py", "")
        assert await last_modified(files, ROOT / "auto") == first + timedelta(seconds=60)

        await clock.advance(seconds=60)
        files.write(ROOT / "auto" / "metadata.json", "{}")
        assert await last_modified(files, ROOT / "auto") == first + timedelta(seconds=120)

        await clock.advance(seconds=60)
        files.write(ROOT / "auto" / "assets" / "a.png", "")
        assert await last_modified(files, ROOT / "auto") == first + timedelta(seconds=120)

    async def test_last_modified_of_a_folder_without_files(self) -> None:
        """A folder with nothing to watch has no modification time."""
        files = file_system("auto/assets/a.png")

        assert await last_modified(files, ROOT / "auto") is None


class TestFolderIssues:
    """Rejected folders are reported, and the report is cleared when the cause is gone."""

    EMPTY = RejectedFolder("---", REASON_EMPTY)
    COLLISION = RejectedFolder("my-automation", REASON_COLLISION, "my_automation", "My Automation")

    def test_empty_id_is_reported(self) -> None:
        """A folder whose name gives no ID is reported, naming the folder."""
        reporter = FakeIssueReporter()

        FolderIssues(reporter).update([self.EMPTY])

        assert reporter.issues == {"rejected_folder_---": (ISSUE_EMPTY_ID, {"folder": "---"})}

    def test_collision_is_reported_with_the_winner(self) -> None:
        """A collision is reported, naming the folder, the ID and the folder that won."""
        reporter = FakeIssueReporter()

        FolderIssues(reporter).update([self.COLLISION])

        assert reporter.issues == {
            "rejected_folder_my-automation": (
                ISSUE_ID_COLLISION,
                {"folder": "my-automation", "automation_id": "my_automation", "winner": "My Automation"},
            )
        }

    def test_issue_is_cleared_when_the_folder_is_no_longer_rejected(self) -> None:
        """Renaming or removing the folder clears its issue."""
        reporter = FakeIssueReporter()
        issues = FolderIssues(reporter)
        issues.update([self.EMPTY, self.COLLISION])

        issues.update([self.EMPTY])

        assert list(reporter.issues) == ["rejected_folder_---"]
        assert reporter.history[-1] == ("clear", "rejected_folder_my-automation")

    def test_all_issues_cleared(self) -> None:
        """A scan with no rejected folders clears everything."""
        reporter = FakeIssueReporter()
        issues = FolderIssues(reporter)
        issues.update([self.EMPTY, self.COLLISION])

        issues.update([])

        assert reporter.issues == {}

    def test_unchanged_issue_is_not_reported_again(self) -> None:
        """Each periodic scan does not re-create an issue that is already raised."""
        reporter = FakeIssueReporter()
        issues = FolderIssues(reporter)

        issues.update([self.COLLISION])
        issues.update([self.COLLISION])
        issues.update([self.COLLISION])

        assert reporter.history == [("report", "rejected_folder_my-automation")]

    def test_changed_winner_updates_the_issue(self) -> None:
        """If another folder now wins the ID, the issue names the new winner."""
        reporter = FakeIssueReporter()
        issues = FolderIssues(reporter)
        issues.update([self.COLLISION])

        issues.update([RejectedFolder("my-automation", REASON_COLLISION, "my_automation", "MY AUTOMATION")])

        assert reporter.issues["rejected_folder_my-automation"][1]["winner"] == "MY AUTOMATION"
        assert len(reporter.history) == 2

    def test_nothing_to_clear_initially(self) -> None:
        """A first scan without rejected folders touches nothing."""
        reporter = FakeIssueReporter()

        FolderIssues(reporter).update([])

        assert reporter.history == []

    async def test_from_discovery_to_issues(self) -> None:
        """The rejected folders of a scan are passed to the reporter of the host."""
        host = make_host()
        files = file_system("My Automation/main.py", "my-automation/main.py", "---/main.py")
        issues = FolderIssues(host.issues)

        issues.update((await discover(files, ROOT)).rejected)
        assert sorted(host.issues.issues) == ["rejected_folder_---", "rejected_folder_my-automation"]  # type: ignore[attr-defined]

        files.delete(ROOT / "---" / "main.py")
        files.delete(ROOT / "My Automation" / "main.py")
        issues.update((await discover(files, ROOT)).rejected)
        assert host.issues.issues == {}  # type: ignore[attr-defined]


class TestFolderAtLoad:
    """An automation is loaded from its folder."""

    async def test_id_and_entry_point(self, tmp_path: Path) -> None:
        """The ID is the slug of the folder name and main.py is run."""
        path = automation_file(tmp_path, "Café  Lights.v2")
        path.write_text("value = 1\n", encoding="utf-8")
        context = make_context(str(path))

        metadata = await load_and_run(context)

        assert context.automation_id == metadata.id == "cafe_lights_v2"
        assert metadata.path == str(path.parent)
        assert metadata.filename == "main.py"
        assert context.get_symbol("value") == 1

    async def test_explicit_id(self, tmp_path: Path) -> None:
        """The ID assigned by discovery is used as given."""
        path = automation_file(tmp_path, "lights")
        path.write_text("x = 1\n", encoding="utf-8")

        context = make_context(str(path), automation_id="assigned")

        assert context.automation_id == "assigned"

    def test_folder_name_without_id(self, tmp_path: Path) -> None:
        """A folder whose name gives no ID cannot be made into an automation."""
        with pytest.raises(HAAnimError, match="Folder name '---' gives no automation ID"):
            make_context(str(tmp_path / "---"))

    async def test_folder_without_main(self, tmp_path: Path) -> None:
        """A folder without main.py does not load."""
        (tmp_path / "lights").mkdir()

        with pytest.raises(HAAnimError, match="Automation has no main.py"):
            await load_and_run(make_context(str(tmp_path / "lights")))

    async def test_empty_main(self, tmp_path: Path) -> None:
        """An empty main.py is a valid automation with nothing in it."""
        path = automation_file(tmp_path, "lights")
        path.write_text("", encoding="utf-8")

        metadata = await load_and_run(make_context(str(path)))

        assert metadata.actions == []

    @pytest.mark.parametrize(
        ("helper", "error", "message"),
        [
            (
                "def gen():\n    yield 1\n",
                AutomationSyntaxError,
                r"^lib/helper.py:2: 'yield' is not supported",
            ),
            ("x = (\n", AutomationSyntaxError, r"^lib/helper.py:1: invalid syntax"),
            ("\nimport os\n", AutomationSecurityError, r"^lib/helper.py:2: import of module 'os'"),
            ("open('f')\n", AutomationSecurityError, r"^lib/helper.py:1: builtin 'open'"),
        ],
        ids=["unsupported", "syntax", "import", "builtin"],
    )
    async def test_every_file_is_checked_before_anything_runs(
        self, tmp_path: Path, helper: str, error: type[Exception], message: str
    ) -> None:
        """A problem in a file main.py never imports still fails the load, and main.py does not run."""
        path = automation_file(tmp_path, "lights")
        path.write_text("ran = True\n", encoding="utf-8")
        (path.parent / "lib").mkdir()
        (path.parent / "lib" / "helper.py").write_text(helper, encoding="utf-8")
        context = make_context(str(path))

        with pytest.raises(error, match=message):
            await load_and_run(context)

        assert context.get_symbol("ran") is None
        assert not context.is_loaded

    async def test_problems_of_all_files_in_one_error(self, tmp_path: Path) -> None:
        """One error lists the problems of the whole folder, main.py first."""
        path = automation_file(tmp_path, "lights")
        path.write_text("import os\n", encoding="utf-8")
        (path.parent / "helper.py").write_text("import sys\n", encoding="utf-8")

        with pytest.raises(AutomationSecurityError) as raised:
            await load_and_run(make_context(str(path)))

        assert str(raised.value).splitlines() == [
            "main.py:1: import of module 'os' is not allowed",
            "helper.py:1: import of module 'sys' is not allowed",
        ]

    async def test_assets_are_not_checked(self, tmp_path: Path) -> None:
        """A Python file in assets is data, not code of the automation."""
        path = automation_file(tmp_path, "lights")
        path.write_text("x = 1\n", encoding="utf-8")
        (path.parent / "assets").mkdir()
        (path.parent / "assets" / "example.py").write_text("this is not python (\n", encoding="utf-8")

        assert (await load_and_run(make_context(str(path)))).id == "lights"

    async def test_sub_package_import(self, tmp_path: Path) -> None:
        """Files in sub-folders are imported relative to the automation's folder."""
        path = automation_file(tmp_path, "lights")
        path.write_text("from .scenes.evening import LEVEL\n", encoding="utf-8")
        (path.parent / "scenes").mkdir()
        (path.parent / "scenes" / "__init__.py").write_text("", encoding="utf-8")
        (path.parent / "scenes" / "evening.py").write_text("LEVEL = 40\n", encoding="utf-8")
        context = make_context(str(path))

        await load_and_run(context)

        assert context.get_symbol("LEVEL") == 40

    async def test_modified_time_covers_every_watched_file(self, tmp_path: Path) -> None:
        """The loaded automation's modification time is its latest file change."""
        clock = FakeClock()
        files = FakeFileSystem(clock)
        files.write("/automations/lights/main.py", "x = 1\n")
        await clock.advance(seconds=30)
        files.write("/automations/lights/metadata.json", "{}")
        host = make_host(files=files, clock=clock)
        context = make_context("/automations/lights", host=host)

        metadata = await load_and_run(context)

        assert metadata.modified_at == clock.now()
        assert metadata.loaded_at == clock.now()
