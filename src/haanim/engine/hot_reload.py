"""Hot reloading: rescanning the automations folder and acting on what changed.

See "Hot Reloading" in the design. A change is acted on only once a following
scan finds no further change, so a file written in several steps is not loaded
half-written.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

from haanim.engine.automation_ids import RejectedFolder
from haanim.engine.discovery import DiscoveredAutomation, discover, watched_files
from haanim.interfaces import Clock, FileSystem

_LOGGER = logging.getLogger(__name__)

DEFAULT_RESCAN_INTERVAL = 10.0

# What a scan knows about an automation's watched files: modification time and size of each.
Fingerprint = dict[Path, tuple[datetime, int]]


async def fingerprint(files: FileSystem, folder: Path) -> Fingerprint:
    """Record the modification time and size of every watched file of an automation.

    Two fingerprints differ exactly when a watched file was added, removed, or
    changed in modification time or size. Files under ``assets`` are not watched.

    Args:
        files: The file system to inspect.
        folder: The automation's folder.

    Raises:
        OSError: If the folder or a file in it cannot be inspected, for
            instance because it is being changed right now.
    """
    return {
        path: (files.modified_time(path), files.size(path)) for path in await watched_files(files, folder)
    }


class ReloadTarget(Protocol):
    """The set of automations a hot reloader keeps in step with the files."""

    def folders(self) -> list[Path]:
        """Return the folder of every automation that is loaded or failed to load."""
        ...

    async def reload(self, found: DiscoveredAutomation) -> None:
        """Bring an automation in line with its files.

        Stops and unloads it if it is loaded, loads it, and starts it if it is
        enabled and loaded without error. Must not raise for a problem of the
        automation: that leaves the automation in the ``error`` state.
        """
        ...

    async def remove(self, folder: Path) -> None:
        """Stop and unload the automation of a folder that is gone."""
        ...

    def report_rejected(self, rejected: Sequence[RejectedFolder]) -> None:
        """Take note of the folders that are not loaded because of their name."""
        ...


class HotReloader:
    """Rescans the automations folder and reloads what changed and has settled."""

    def __init__(
        self,
        files: FileSystem,
        root: Path,
        clock: Clock,
        target: ReloadTarget,
        *,
        interval: float = DEFAULT_RESCAN_INTERVAL,
    ) -> None:
        """Initialize the reloader.

        Args:
            files: The file system to scan.
            root: The automations folder.
            clock: Paces the rescans.
            target: The automations to keep in step with the files.
            interval: Seconds between rescans.
        """
        self._files = files
        self._root = root
        self._clock = clock
        self._target = target
        self._interval = interval
        # The files of each automation as they were when it was last loaded or reloaded
        self._acted: dict[Path, Fingerprint] = {}
        # A change seen at the last scan, waiting for a scan that finds it unchanged
        self._pending: dict[Path, Fingerprint] = {}

    async def prime(self) -> None:
        """Take the current files of the target's automations as already acted on.

        Call this after the automations have been loaded for the first time,
        so that the first rescan does not reload them all.
        """
        self._pending.clear()
        self._acted = {}
        for folder in self._target.folders():
            try:
                self._acted[folder] = await fingerprint(self._files, folder)
            except OSError:
                # Unreadable right now: an empty record makes the next scans pick it up.
                self._acted[folder] = {}

    async def rescan(self) -> None:
        """Scan once: unload what is gone, and load or reload what changed and has settled."""
        discovery = await discover(self._files, self._root)
        self._target.report_rejected(discovery.rejected)
        current = {found.folder: found for found in discovery.automations}

        # Folders that are gone, renamed, or lost their ID to another folder
        for folder in [*self._acted]:
            if folder not in current:
                _LOGGER.info("Automation folder removed: %s", folder)
                del self._acted[folder]
                self._pending.pop(folder, None)
                await self._target.remove(folder)
        for folder in [*self._pending]:
            if folder not in current:
                del self._pending[folder]

        for folder, found in current.items():
            try:
                seen = await fingerprint(self._files, folder)
            except OSError as err:
                # Being written or removed right now; look again at the next scan.
                _LOGGER.debug("Cannot inspect %s yet: %s", folder, err)
                self._pending.pop(folder, None)
                continue

            if self._acted.get(folder) == seen:
                self._pending.pop(folder, None)
            elif self._pending.get(folder) == seen:
                # Changed, and the same as at the scan before: settled.
                del self._pending[folder]
                self._acted[folder] = seen
                _LOGGER.info("Automation files changed, reloading: %s", found.automation_id)
                await self._target.reload(found)
            else:
                self._pending[folder] = seen

    async def run(self) -> None:
        """Rescan at the rescan interval until cancelled.

        A scan that fails is logged and the next one is tried; hot reloading
        does not stop because one scan could not read the folder.
        """
        while True:
            await self._clock.sleep(self._interval)
            try:
                await self.rescan()
            except Exception:  # pylint: disable=broad-exception-caught
                _LOGGER.exception("Rescan of the automations folder failed")
