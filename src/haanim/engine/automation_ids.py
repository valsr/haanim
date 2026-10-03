"""Automation IDs: derived from folder names, with collisions resolved.

See "Automation Id" in the design. Everything here is a pure function of the
folder names; nothing touches the file system or the host.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from slugify import slugify

REASON_EMPTY = "empty"
REASON_COLLISION = "collision"


def automation_id(folder_name: str) -> str:
    """Return the automation ID for a folder name.

    The ID is the slug of the name, as Home Assistant's ``slugify`` produces it
    (the same library with the same settings): lowercased, accented and
    non-Latin letters transliterated to ASCII, every run of characters other
    than ``a-z`` and ``0-9`` replaced by one underscore, and leading and
    trailing underscores removed.

    Unlike Home Assistant's function, a name with nothing usable in it gives an
    empty string rather than ``"unknown"``; such a folder is not loaded.

    Args:
        folder_name: Name of the automation's folder.
    """
    return slugify(folder_name, separator="_")


@dataclass(frozen=True)
class RejectedFolder:
    """A folder that is not loaded because of its name.

    Args:
        folder: Name of the folder.
        reason: ``REASON_EMPTY`` if the name gives no ID, ``REASON_COLLISION``
            if another folder with the same ID is loaded instead.
        automation_id: The ID the name gives. Empty for ``REASON_EMPTY``.
        winner: For a collision, the folder that is loaded under the ID.
    """

    folder: str
    reason: str
    automation_id: str = ""
    winner: str | None = None


@dataclass(frozen=True)
class IdAssignment:
    """Which folders are loaded under which ID, and which are not loaded.

    Args:
        loaded: Folder name by automation ID, in ascending order of ID, which
            is the order automations are loaded and started in.
        rejected: The folders that are not loaded, in ascending order of name.
    """

    loaded: dict[str, str] = field(default_factory=dict)
    rejected: list[RejectedFolder] = field(default_factory=list)


def assign_ids(folder_names: Iterable[str]) -> IdAssignment:
    """Derive the automation IDs of a set of folders and resolve collisions.

    When several folders give the same ID, the one whose name sorts first by
    Unicode code point is loaded. A folder whose name gives an empty ID is not
    loaded. The result does not depend on the order of the input.

    Args:
        folder_names: Names of the folders that contain an automation.
    """
    winners: dict[str, str] = {}
    rejected: list[RejectedFolder] = []

    # Python compares strings by code point, which is the order the design asks for.
    for folder in sorted(set(folder_names)):
        slug = automation_id(folder)
        if not slug:
            rejected.append(RejectedFolder(folder, REASON_EMPTY))
        elif slug in winners:
            rejected.append(RejectedFolder(folder, REASON_COLLISION, slug, winners[slug]))
        else:
            winners[slug] = folder

    return IdAssignment(loaded=dict(sorted(winners.items())), rejected=rejected)
