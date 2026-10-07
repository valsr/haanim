"""Finding the automations in the automations folder.

See "Automation" and "File Organization" in the design: an automation is a
folder with a ``main.py``; its ID comes from the folder name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from haanim.engine.automation_ids import REASON_COLLISION, RejectedFolder, assign_ids
from haanim.engine.metadata import METADATA_FILENAME
from haanim.interfaces import FileSystem, IssueReporter

MAIN_FILENAME = "main.py"
ASSETS_DIRNAME = "assets"

# Issue kinds reported for folders that are not loaded
ISSUE_EMPTY_ID = "folder_without_id"
ISSUE_ID_COLLISION = "folder_id_collision"
ISSUE_PREFIX = "rejected_folder_"


@dataclass(frozen=True)
class DiscoveredAutomation:
    """An automation found in the automations folder.

    Args:
        automation_id: The automation's ID.
        folder: The automation's folder.
    """

    automation_id: str
    folder: Path

    @property
    def main(self) -> Path:
        """The automation's entry point."""
        return self.folder / MAIN_FILENAME


@dataclass(frozen=True)
class Discovery:
    """The result of scanning the automations folder.

    Args:
        automations: The automations to load, in ascending order of ID.
        rejected: Folders that contain an automation but are not loaded
            because of their name.
    """

    automations: list[DiscoveredAutomation] = field(default_factory=list)
    rejected: list[RejectedFolder] = field(default_factory=list)


def has_main(files: FileSystem, folder: Path) -> bool:
    """Return whether a folder directly contains a ``main.py`` file.

    Args:
        files: The file system to inspect.
        folder: The folder.
    """
    main = folder / MAIN_FILENAME
    return files.exists(main) and not files.is_dir(main)


async def discover(files: FileSystem, root: Path) -> Discovery:
    """Scan the automations folder.

    A folder is an automation if it directly contains a ``main.py``. Files in
    the automations folder itself and folders without a ``main.py`` are
    ignored.

    Args:
        files: The file system to scan.
        root: The automations folder.

    Returns:
        What was found. Empty if the automations folder does not exist.
    """
    if not files.is_dir(root):
        return Discovery()

    folders = [
        path.name for path in await files.list_dir(root) if files.is_dir(path) and has_main(files, path)
    ]
    assignment = assign_ids(folders)
    automations = [DiscoveredAutomation(slug, root / folder) for slug, folder in assignment.loaded.items()]
    return Discovery(automations=automations, rejected=assignment.rejected)


async def source_files(files: FileSystem, folder: Path) -> list[Path]:
    """Return every Python file of an automation, ``main.py`` first.

    The folder is searched recursively. The ``assets`` folder and folders
    whose name starts with ``.`` or ``__`` (such as ``__pycache__``) are not
    searched: nothing in them is automation code.

    Args:
        files: The file system to search.
        folder: The automation's folder.
    """
    found: list[Path] = []
    pending = [folder]
    while pending:
        directory = pending.pop()
        for path in await files.list_dir(directory):
            if files.is_dir(path):
                skipped = path.name.startswith((".", "__")) or (
                    directory == folder and path.name == ASSETS_DIRNAME
                )
                if not skipped:
                    pending.append(path)
            elif path.suffix == ".py":
                found.append(path)

    main = folder / MAIN_FILENAME
    return sorted(found, key=lambda path: (path != main, path))


async def watched_files(files: FileSystem, folder: Path) -> list[Path]:
    """Return the files whose change means the automation has to be reloaded.

    Args:
        files: The file system to search.
        folder: The automation's folder.
    """
    watched = await source_files(files, folder)
    metadata = folder / METADATA_FILENAME
    if files.exists(metadata):
        watched.append(metadata)
    return watched


async def last_modified(files: FileSystem, folder: Path) -> datetime | None:
    """Return when the automation's code or metadata was last changed.

    Args:
        files: The file system to inspect.
        folder: The automation's folder.

    Returns:
        The latest modification time of its watched files, or None if it has none.
    """
    times = [files.modified_time(path) for path in await watched_files(files, folder)]
    return max(times, default=None)


class FolderIssues:
    """Keeps the reported issues in step with the folders that are not loaded.

    Each rejected folder has one issue, which is cleared once the folder is no
    longer rejected: renamed, removed, or the folder it collided with is gone.
    """

    def __init__(self, issues: IssueReporter) -> None:
        """Initialize with nothing reported.

        Args:
            issues: Where the issues are reported.
        """
        self._issues = issues
        self._reported: dict[str, RejectedFolder] = {}

    @staticmethod
    def issue_id(folder: str) -> str:
        """Return the ID of the issue for a folder."""
        return f"{ISSUE_PREFIX}{folder}"

    def update(self, rejected: list[RejectedFolder]) -> None:
        """Report the folders that are rejected now and clear the issues of those that no longer are.

        Args:
            rejected: The rejected folders of the latest scan.
        """
        current = {entry.folder: entry for entry in rejected}

        for folder in sorted(set(self._reported) - set(current)):
            self._issues.clear(self.issue_id(folder))

        for folder, entry in current.items():
            if self._reported.get(folder) == entry:
                continue
            if entry.reason == REASON_COLLISION:
                placeholders = {
                    "folder": folder,
                    "automation_id": entry.automation_id,
                    "winner": entry.winner or "",
                }
                self._issues.report(self.issue_id(folder), ISSUE_ID_COLLISION, placeholders)
            else:
                self._issues.report(self.issue_id(folder), ISSUE_EMPTY_ID, {"folder": folder})

        self._reported = current
