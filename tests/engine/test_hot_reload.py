"""Tests for hot reloading with the fake clock and the in-memory file system."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.action_pool import ActionWorkerPool
from haanim.engine.automation_ids import REASON_COLLISION, RejectedFolder
from haanim.engine.automation_status import AutomationStatusManager
from haanim.engine.control import EnabledFlags
from haanim.engine.discovery import DiscoveredAutomation
from haanim.engine.hot_reload import DEFAULT_RESCAN_INTERVAL, HotReloader, fingerprint
from haanim.engine.lifecycle import Automation, AutomationState, NoTriggers
from haanim.testing import FakeClock, FakeFileSystem, FakeStorage, make_host
from tests.engine.helpers import make_context

ROOT = Path("/config/haanim/automations")
OFF, ON, ERROR = AutomationState.OFF, AutomationState.ON, AutomationState.ERROR

GOOD = "from haanim import action\n\nVERSION = {version}\n\n@action\ndef version():\n    return VERSION\n"


class RecordingTarget:
    """A reload target that only records what the reloader asks of it."""

    def __init__(self) -> None:
        self.loaded: dict[Path, str] = {}
        self.calls: list[tuple[str, str]] = []
        self.rejected: list[RejectedFolder] = []

    def folders(self) -> list[Path]:
        """Return the folders recorded as loaded."""
        return list(self.loaded)

    async def reload(self, found: DiscoveredAutomation) -> None:
        """Record a load or reload."""
        self.loaded[found.folder] = found.automation_id
        self.calls.append(("reload", found.folder.name))

    async def remove(self, folder: Path) -> None:
        """Record a removal."""
        self.loaded.pop(folder, None)
        self.calls.append(("remove", folder.name))

    def report_rejected(self, rejected: Sequence[RejectedFolder]) -> None:
        """Record the rejected folders of the latest scan."""
        self.rejected = list(rejected)


class Scans:
    """A reloader over an in-memory file system, with a recording target."""

    def __init__(self) -> None:
        self.clock = FakeClock()
        self.files = FakeFileSystem(self.clock)
        self.target = RecordingTarget()
        self.reloader = HotReloader(self.files, ROOT, self.clock, self.target)

    def write(self, path: str, content: str = "x = 1\n") -> None:
        """Write a file below the automations folder."""
        self.files.write(ROOT / path, content)

    async def loaded(self, *names: str) -> None:
        """Create automations and take them as loaded, as after the first load."""
        for name in names:
            self.write(f"{name}/main.py")
            self.target.loaded[ROOT / name] = name
        await self.reloader.prime()

    async def scan(self, times: int = 1) -> list[tuple[str, str]]:
        """Rescan, moving the clock on between scans, and return what the target was asked since."""
        before = len(self.target.calls)
        for _ in range(times):
            await self.clock.advance(seconds=1)
            await self.reloader.rescan()
        return self.target.calls[before:]


@pytest.fixture
def scans() -> Scans:
    """A reloader with a recording target."""
    return Scans()


class TestFingerprint:
    """What a scan records about an automation's files."""

    async def test_watched_files_only(self, scans: Scans) -> None:
        """Python files recursively and metadata.json; nothing under assets."""
        for path in (
            "a/main.py",
            "a/lib/helper.py",
            "a/metadata.json",
            "a/assets/pic.png",
            "a/assets/x.py",
            "a/notes.txt",
        ):
            scans.write(path)

        seen = await fingerprint(scans.files, ROOT / "a")

        assert sorted(path.relative_to(ROOT / "a").as_posix() for path in seen) == [
            "lib/helper.py",
            "main.py",
            "metadata.json",
        ]

    async def test_modification_time_and_size(self, scans: Scans) -> None:
        """Each file is recorded with its modification time and size in bytes."""
        scans.write("a/main.py", "héllo")

        seen = await fingerprint(scans.files, ROOT / "a")

        assert seen == {ROOT / "a" / "main.py": (scans.clock.now(), 6)}

    async def test_missing_folder(self, scans: Scans) -> None:
        """A folder that cannot be inspected raises, so the caller can look again later."""
        with pytest.raises(OSError):
            await fingerprint(scans.files, ROOT / "missing")


class TestChangeDetection:
    """A file is changed if its modification time or size differs, or it was added or removed."""

    async def test_no_change_no_action(self, scans: Scans) -> None:
        """Scanning unchanged files does nothing, however often."""
        await scans.loaded("lights")

        assert await scans.scan(5) == []

    async def test_modification_time(self, scans: Scans) -> None:
        """A file rewritten with content of the same size is changed by its modification time."""
        await scans.loaded("lights")
        await scans.clock.advance(seconds=5)
        scans.write("lights/main.py", "x = 2\n")

        assert await scans.scan(2) == [("reload", "lights")]

    async def test_size(self, scans: Scans) -> None:
        """A file whose size differs is changed even if its modification time is the same."""
        await scans.loaded("lights")
        scans.write("lights/main.py", "x = 1  # longer\n")
        assert scans.files.modified_time(ROOT / "lights" / "main.py") == scans.clock.now()

        assert await scans.scan(2) == [("reload", "lights")]

    @pytest.mark.parametrize(
        "path",
        ["lights/helper.py", "lights/lib/deep/module.py", "lights/metadata.json"],
        ids=["python file", "nested python file", "metadata"],
    )
    async def test_file_added(self, scans: Scans, path: str) -> None:
        """A watched file that appears is a change."""
        await scans.loaded("lights")
        scans.write(path, "{}" if path.endswith(".json") else "x = 1\n")

        assert await scans.scan(2) == [("reload", "lights")]

    async def test_file_removed(self, scans: Scans) -> None:
        """A watched file that disappears is a change."""
        scans.write("lights/helper.py")
        await scans.loaded("lights")
        scans.files.delete(ROOT / "lights" / "helper.py")

        assert await scans.scan(2) == [("reload", "lights")]

    @pytest.mark.parametrize(
        "path",
        [
            "lights/assets/pic.png",
            "lights/assets/script.py",
            "lights/notes.txt",
            "lights/.git/x.py",
            "flat.py",
        ],
    )
    async def test_unwatched_files_are_ignored(self, scans: Scans, path: str) -> None:
        """Changes to assets and to files that are not watched do not reload anything."""
        await scans.loaded("lights")
        scans.write(path, "changed")
        await scans.clock.advance(seconds=5)
        scans.write(path, "changed again")

        assert await scans.scan(3) == []

    async def test_only_the_changed_automation_is_reloaded(self, scans: Scans) -> None:
        """The other automations are left running."""
        await scans.loaded("lights", "heating", "garden")
        await scans.clock.advance(seconds=5)
        scans.write("heating/main.py", "x = 2\n")

        assert await scans.scan(3) == [("reload", "heating")]

    async def test_reloaded_once_per_change(self, scans: Scans) -> None:
        """After a reload the new files are the baseline."""
        await scans.loaded("lights")
        await scans.clock.advance(seconds=5)
        scans.write("lights/main.py", "x = 2\n")

        assert await scans.scan(6) == [("reload", "lights")]

        await scans.clock.advance(seconds=5)
        scans.write("lights/main.py", "x = 3\n")
        assert await scans.scan(2) == [("reload", "lights")]


class TestSettling:
    """A change is acted on only when a following scan finds no further change."""

    async def test_not_acted_on_at_the_scan_that_sees_it(self, scans: Scans) -> None:
        """The scan that first sees a change does nothing; the next one acts."""
        await scans.loaded("lights")
        await scans.clock.advance(seconds=5)
        scans.write("lights/main.py", "x = 2\n")

        assert await scans.scan() == []
        assert await scans.scan() == [("reload", "lights")]

    async def test_file_written_in_two_steps(self, scans: Scans) -> None:
        """A file still being written when the next scan comes is not loaded half-written."""
        await scans.loaded("lights")
        await scans.clock.advance(seconds=5)

        scans.write("lights/main.py", "def half(")
        assert await scans.scan() == []
        scans.write("lights/main.py", "def half():\n    pass\n")
        assert await scans.scan() == []
        assert await scans.scan() == [("reload", "lights")]

    async def test_keeps_waiting_while_changes_continue(self, scans: Scans) -> None:
        """As long as every scan sees a new change, nothing is reloaded."""
        await scans.loaded("lights")

        for step in range(6):
            scans.write("lights/main.py", f"x = {step}\n")
            assert await scans.scan() == []

        assert await scans.scan() == [("reload", "lights")]

    async def test_change_undone_before_settling(self, scans: Scans) -> None:
        """A file put back exactly as it was is not a change any more."""
        scans.write("lights/helper.py")
        await scans.loaded("lights")
        original = dict(scans.files._files)  # pylint: disable=protected-access

        scans.files.delete(ROOT / "lights" / "helper.py")
        assert await scans.scan() == []
        scans.files._files.update(original)  # pylint: disable=protected-access

        assert await scans.scan(3) == []

    async def test_settling_is_per_automation(self, scans: Scans) -> None:
        """One automation still being edited does not hold back another that has settled."""
        await scans.loaded("lights", "heating")
        await scans.clock.advance(seconds=5)
        scans.write("lights/main.py", "x = 2\n")
        scans.write("heating/main.py", "x = 2\n")
        assert await scans.scan() == []

        scans.write("heating/main.py", "x = 3\n")
        assert await scans.scan() == [("reload", "lights")]
        assert await scans.scan() == [("reload", "heating")]

    async def test_folder_that_cannot_be_inspected_is_looked_at_again(self, scans: Scans) -> None:
        """A scan that hits a folder in the middle of a change skips it and does not lose the change."""
        await scans.loaded("lights")
        await scans.clock.advance(seconds=5)
        scans.write("lights/main.py", "x = 2\n")
        size = scans.files.size

        def failing(path: Path) -> int:
            raise FileNotFoundError(str(path))

        scans.files.size = failing  # type: ignore[method-assign]
        assert await scans.scan(2) == []

        scans.files.size = size  # type: ignore[method-assign]
        assert await scans.scan() == []
        assert await scans.scan() == [("reload", "lights")]


class TestFolders:
    """Added, removed and renamed folders are handled at rescan."""

    async def test_folder_added(self, scans: Scans) -> None:
        """A new automation folder is loaded once its files have settled."""
        await scans.loaded("lights")
        scans.write("heating/main.py")

        assert await scans.scan() == []
        assert await scans.scan() == [("reload", "heating")]
        assert await scans.scan(3) == []

    async def test_folder_added_in_steps(self, scans: Scans) -> None:
        """A folder that is still being copied is not loaded until it is complete."""
        scans.write("heating/main.py")
        assert await scans.scan() == []
        scans.write("heating/helper.py")
        assert await scans.scan() == []

        assert await scans.scan() == [("reload", "heating")]

    async def test_folder_without_main_is_not_an_automation_yet(self, scans: Scans) -> None:
        """A folder becomes an automation when main.py arrives."""
        scans.write("heating/helper.py")
        assert await scans.scan(3) == []

        scans.write("heating/main.py")
        assert await scans.scan(2) == [("reload", "heating")]

    async def test_folder_removed(self, scans: Scans) -> None:
        """An automation whose folder is gone is removed at the next scan, without waiting."""
        await scans.loaded("lights", "heating")
        scans.files.delete(ROOT / "heating" / "main.py")

        assert await scans.scan() == [("remove", "heating")]
        assert await scans.scan(3) == []

    async def test_main_removed(self, scans: Scans) -> None:
        """A folder that loses its main.py is no longer an automation."""
        scans.write("lights/helper.py")
        await scans.loaded("lights")
        scans.files.delete(ROOT / "lights" / "main.py")

        assert await scans.scan() == [("remove", "lights")]

    async def test_folder_renamed(self, scans: Scans) -> None:
        """A renamed folder is the old automation removed and a new one loaded."""
        await scans.loaded("lights")
        scans.files.delete(ROOT / "lights" / "main.py")
        scans.write("lamps/main.py")

        assert await scans.scan() == [("remove", "lights")]
        assert await scans.scan() == [("reload", "lamps")]
        assert scans.target.loaded == {ROOT / "lamps": "lamps"}

    async def test_folder_removed_and_put_back(self, scans: Scans) -> None:
        """A folder moved away and back is unloaded and then loaded again."""
        await scans.loaded("lights")
        scans.files.delete(ROOT / "lights" / "main.py")
        assert await scans.scan() == [("remove", "lights")]

        scans.write("lights/main.py")
        assert await scans.scan(2) == [("reload", "lights")]

    async def test_new_folder_removed_before_it_settled(self, scans: Scans) -> None:
        """A folder that came and went between scans is never loaded."""
        scans.write("heating/main.py")
        assert await scans.scan() == []
        scans.files.delete(ROOT / "heating" / "main.py")

        assert await scans.scan(3) == []

    async def test_folder_that_takes_over_an_id(self, scans: Scans) -> None:
        """A new folder that sorts first takes the ID: the old one is removed and reported, the new one loaded."""
        await scans.loaded("lights")
        scans.write("Lights/main.py")

        assert await scans.scan() == [("remove", "lights")]
        assert scans.target.rejected == [RejectedFolder("lights", REASON_COLLISION, "lights", "Lights")]
        assert await scans.scan() == [("reload", "Lights")]

    async def test_rejected_folders_are_reported_at_every_scan(self, scans: Scans) -> None:
        """The target is told the rejected folders each time, so issues can be raised and cleared."""
        scans.write("---/main.py")
        await scans.scan()
        assert [entry.folder for entry in scans.target.rejected] == ["---"]

        scans.files.delete(ROOT / "---" / "main.py")
        await scans.scan()
        assert scans.target.rejected == []

    async def test_automations_folder_missing(self, scans: Scans) -> None:
        """Without an automations folder a scan finds nothing and removes what was loaded."""
        await scans.loaded("lights")
        scans.files.delete(ROOT / "lights" / "main.py")

        assert await scans.scan() == [("remove", "lights")]
        assert await scans.scan() == []


class TestPrime:
    """Priming takes the files as they are as already loaded."""

    async def test_no_reload_after_priming(self, scans: Scans) -> None:
        """What was loaded before hot reloading started is not loaded again."""
        scans.write("lights/main.py")
        scans.target.loaded[ROOT / "lights"] = "lights"

        await scans.reloader.prime()

        assert await scans.scan(3) == []

    async def test_without_priming_everything_is_new(self, scans: Scans) -> None:
        """A reloader that was not primed loads what it finds, after settling."""
        scans.write("lights/main.py")

        assert await scans.scan(2) == [("reload", "lights")]

    async def test_priming_an_automation_whose_folder_is_unreadable(self, scans: Scans) -> None:
        """An automation that cannot be inspected when priming is picked up by the scans that follow."""
        scans.target.loaded[ROOT / "gone"] = "gone"

        await scans.reloader.prime()

        assert await scans.scan() == [("remove", "gone")]


class TestRun:
    """Rescans happen at the rescan interval, on the clock."""

    async def test_default_interval(self) -> None:
        """The design's default is 10 seconds."""
        assert DEFAULT_RESCAN_INTERVAL == 10

    async def test_rescans_at_the_interval(self, scans: Scans) -> None:
        """A change is picked up at the first scan after it and acted on at the one after that."""
        await scans.loaded("lights")
        running = asyncio.create_task(scans.reloader.run())
        await scans.clock.advance(seconds=3)
        scans.write("lights/main.py", "x = 2\n")

        await scans.clock.advance(seconds=6)
        assert scans.target.calls == []
        await scans.clock.advance(seconds=1)
        assert scans.target.calls == []
        await scans.clock.advance(seconds=10)
        assert scans.target.calls == [("reload", "lights")]

        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running

    async def test_custom_interval(self, scans: Scans) -> None:
        """The interval is the integration's option."""
        reloader = HotReloader(scans.files, ROOT, scans.clock, scans.target, interval=2)
        scans.write("lights/main.py")
        running = asyncio.create_task(reloader.run())

        await scans.clock.advance(seconds=3)
        assert scans.target.calls == []
        await scans.clock.advance(seconds=1)
        assert scans.target.calls == [("reload", "lights")]

        running.cancel()

    async def test_failed_scan_does_not_stop_hot_reloading(
        self, scans: Scans, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A scan that raises is logged and the next scan runs."""
        await scans.loaded("lights")
        original = scans.target.reload
        failures = [RuntimeError("target broke")]

        async def flaky(found: DiscoveredAutomation) -> None:
            if failures:
                raise failures.pop()
            await original(found)

        scans.target.reload = flaky  # type: ignore[method-assign]
        running = asyncio.create_task(scans.reloader.run())
        scans.write("lights/main.py", "x = 2  # changed\n")
        await scans.clock.advance(seconds=20)
        assert "Rescan of the automations folder failed" in caplog.text

        scans.write("lights/main.py", "x = 3  # changed again\n")
        await scans.clock.advance(seconds=20)
        assert scans.target.calls == [("reload", "lights")]

        running.cancel()


class Automations:
    """A reload target over real automations: what the integration's manager does, without Home Assistant."""

    def __init__(self, tmp_path: Path) -> None:
        self.clock = FakeClock()
        self.files = FakeFileSystem(self.clock)
        self.host = make_host(files=self.files, clock=self.clock)
        self.pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=self.clock)
        self.flags = EnabledFlags(FakeStorage())
        self.storage_path = str(tmp_path)
        self.automations: dict[Path, Automation] = {}
        self.reloader = HotReloader(self.files, ROOT, self.clock, self)

    def folders(self) -> list[Path]:
        """Return the folders of all automations."""
        return list(self.automations)

    async def reload(self, found: DiscoveredAutomation) -> None:
        """Stop and unload the old version, load the new one, start it if enabled."""
        old = self.automations.pop(found.folder, None)
        if old is not None:
            await old.unload()
        context = make_context(
            str(found.folder),
            host=self.host,
            automation_id=found.automation_id,
            storage_path=self.storage_path,
        )
        automation = Automation(context, pool=self.pool, triggers=NoTriggers())
        self.automations[found.folder] = automation
        if await automation.load() and self.flags.is_enabled(found.automation_id):
            await automation.start()

    async def remove(self, folder: Path) -> None:
        """Stop and unload an automation."""
        await self.automations.pop(folder).unload()

    def report_rejected(self, rejected: Sequence[RejectedFolder]) -> None:
        """Ignore rejected folders."""

    def write(self, name: str, source: str, filename: str = "main.py") -> None:
        """Write a file of an automation."""
        self.files.write(ROOT / name / filename, source)

    async def scan(self, times: int = 2) -> None:
        """Rescan, a second apart."""
        for _ in range(times):
            await self.clock.advance(seconds=1)
            await self.reloader.rescan()

    def get(self, name: str) -> Automation:
        """Return the automation of a folder."""
        return self.automations[ROOT / name]

    async def version(self, name: str) -> Any:
        """Call the automation's ``version`` action."""
        return await self.get(name).call_action("version")


@pytest.fixture
async def automations(tmp_path: Path) -> Automations:
    """Real automations kept in step with an in-memory file system."""
    target = Automations(tmp_path)
    target.write("lights", GOOD.format(version=1))
    await target.scan()
    return target


class TestReloadSequence:
    """Stop, unload, load, start: the automation always describes the files on disk."""

    async def test_new_version_replaces_the_old(self, automations: Automations) -> None:
        """After a reload the automation runs the new code."""
        assert await automations.version("lights") == 1
        old = automations.get("lights")

        automations.write("lights", GOOD.format(version=2))
        await automations.scan()

        assert automations.get("lights").state is ON
        assert await automations.version("lights") == 2
        assert old.state is AutomationState.UNAVAILABLE

    async def test_old_version_is_stopped_first(self, automations: Automations) -> None:
        """The old version's @shutdown runs before the new version's @startup."""
        source = (
            "from haanim import startup, shutdown, haa\n\n@startup\nasync def on_start():\n"
            "    await haa.set_variable('order', haa.get_variable('order', '') + ' start{v}')\n\n"
            "@shutdown\nasync def on_stop():\n    await haa.set_variable('order', haa.get_variable('order', '') + ' stop{v}')\n\n"
            "from haanim import action\n\n@action\ndef order():\n    return haa.get_variable('order')\n"
        )
        automations.write("heating", source.format(v=1))
        await automations.scan()
        automations.write("heating", source.format(v=2))
        await automations.scan()

        assert await automations.get("heating").call_action("order") == " start1 stop1 start2"

    async def test_module_variables_are_not_carried_over(self, automations: Automations) -> None:
        """A reload starts from a fresh namespace."""
        source = "from haanim import action\ncount = 0\n\n@action\ndef bump():\n    global count\n    count += 1\n    return count\n"
        automations.write("counter", source)
        await automations.scan()
        assert await automations.get("counter").call_action("bump") == 1
        assert await automations.get("counter").call_action("bump") == 2

        automations.write("counter", source + "# edited\n")
        await automations.scan()

        assert await automations.get("counter").call_action("bump") == 1

    async def test_storage_and_enabled_flag_are_unaffected(self, automations: Automations) -> None:
        """Persistent storage survives a reload, and a disabled automation stays stopped."""
        source = (
            "from haanim import action, haa\n\n@action\nasync def remember():\n    await haa.set_variable('kept', 'yes')\n\n"
            "@action\ndef recall():\n    return haa.get_variable('kept')\n"
        )
        automations.write("memory", source)
        await automations.scan()
        await automations.get("memory").call_action("remember")

        automations.write("memory", source + "# edited\n")
        await automations.scan()
        assert await automations.get("memory").call_action("recall") == "yes"

        await automations.get("memory").stop()
        await automations.flags.set_enabled("memory", False)
        automations.write("memory", source + "# edited again\n")
        await automations.scan()
        assert automations.get("memory").state is OFF

    @pytest.mark.parametrize(
        ("broken", "message"),
        [
            ("def broken(:\n", "main.py:1: invalid syntax"),
            ("import os\n", "main.py:1: import of module 'os' is not allowed"),
            ("raise KeyError('boom')\n", "AutomationRuntimeError: Runtime error: 'boom'"),
            (
                "from haanim import startup\n\n@startup\ndef s():\n    raise KeyError('x')\n",
                "@startup failed: KeyError: 'x'",
            ),
        ],
        ids=["syntax", "import", "main raises", "startup raises"],
    )
    async def test_broken_new_version(self, automations: Automations, broken: str, message: str) -> None:
        """If the new files fail to load or start, the automation is in error and the old version is not restored."""
        old = automations.get("lights")

        automations.write("lights", broken)
        await automations.scan()

        current = automations.get("lights")
        assert current.state is ERROR
        assert (current.message or "").startswith(message)
        assert old.state is AutomationState.UNAVAILABLE
        assert not old.context.is_executed

    async def test_fixing_the_files_triggers_another_reload(self, automations: Automations) -> None:
        """An automation in error is loaded and started again when its files change."""
        automations.write("lights", "def broken(:\n")
        await automations.scan()
        assert automations.get("lights").state is ERROR

        await automations.scan(3)
        assert automations.get("lights").state is ERROR

        automations.write("lights", GOOD.format(version=3))
        await automations.scan()
        assert automations.get("lights").state is ON
        assert await automations.version("lights") == 3

    async def test_change_in_an_imported_file(self, automations: Automations) -> None:
        """Editing a file main.py imports reloads the automation."""
        automations.write(
            "split",
            "from haanim import action\nfrom .values import VALUE\n\n@action\ndef version():\n    return VALUE\n",
        )
        automations.write("split", "VALUE = 1\n", "values.py")
        await automations.scan()
        assert await automations.version("split") == 1

        automations.write("split", "VALUE = 22\n", "values.py")
        await automations.scan()

        assert await automations.version("split") == 22

    async def test_metadata_change(self, automations: Automations) -> None:
        """Editing metadata.json reloads the automation with the new metadata."""
        automations.write("lights", '{"name": "Hall lights"}', "metadata.json")
        await automations.scan()

        metadata = automations.get("lights").context.get_metadata()
        assert metadata is not None and metadata.name == "Hall lights"

    async def test_half_written_file_is_never_loaded(self, automations: Automations) -> None:
        """An editor writing in two steps does not put the automation into error in between."""
        automations.write("lights", "from haanim import action\n\n@action\ndef version(")
        await automations.scan(times=1)
        assert automations.get("lights").state is ON
        assert await automations.version("lights") == 1

        automations.write("lights", GOOD.format(version=2))
        await automations.scan(times=1)
        assert await automations.version("lights") == 1

        await automations.scan(times=1)
        assert await automations.version("lights") == 2

    async def test_folder_removed(self, automations: Automations) -> None:
        """The automation of a removed folder is stopped and unloaded."""
        old = automations.get("lights")
        automations.files.delete(ROOT / "lights" / "main.py")

        await automations.scan(times=1)

        assert automations.automations == {}
        assert old.state is AutomationState.UNAVAILABLE

    async def test_folder_renamed_gets_a_new_id(self, automations: Automations) -> None:
        """Renaming a folder so that its ID changes creates a new automation."""
        automations.files.delete(ROOT / "lights" / "main.py")
        automations.write("lamps", GOOD.format(version=1))

        await automations.scan(times=3)

        assert [automation.automation_id for automation in automations.automations.values()] == ["lamps"]
        assert automations.get("lamps").state is ON
