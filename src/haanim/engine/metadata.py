"""The ``metadata.json`` file of an automation.

See "Metadata" in the design. The file and every field in it are optional.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from haanim.engine.errors import AutomationMetadataError
from haanim.interfaces import FileSystem

METADATA_FILENAME = "metadata.json"
DEFAULT_VERSION = "1.0.0"

# The text fields of the file.
FIELDS = ("name", "description", "author", "version")
# The fields that widen the import allowlist for this automation.
ALLOW_ALL_IMPORTS = "allow_all_imports"
ADDITIONAL_IMPORTS = "additional_imports"


@dataclass(frozen=True)
class AutomationInfo:
    """What ``metadata.json`` says about an automation.

    Args:
        name: Display name. The folder name if the file gives none.
        description: Short description.
        author: Author shown in the GUI.
        version: Version string shown in the GUI.
        allow_all_imports: Whether the automation may import any module.
        additional_imports: Modules the automation may import in addition to
            the allowlist.
    """

    name: str
    description: str = ""
    author: str = ""
    version: str = DEFAULT_VERSION
    allow_all_imports: bool = False
    additional_imports: tuple[str, ...] = ()


def parse_metadata(text: str | None, folder_name: str) -> AutomationInfo:
    """Parse the contents of a ``metadata.json``.

    Fields the design does not define are ignored, so a file written for a
    later version still loads.

    Args:
        text: The contents of the file, or None if there is no file.
        folder_name: Name of the automation's folder, the default display name.

    Returns:
        The metadata, with defaults for everything the file does not give.

    Raises:
        AutomationMetadataError: If the text is not valid JSON, is not a JSON
            object, or a field has the wrong type.
    """
    if text is None:
        return AutomationInfo(name=folder_name)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise AutomationMetadataError(
            f"{METADATA_FILENAME}:{err.lineno}: not valid JSON: {err.msg}",
            lineno=err.lineno,
            col_offset=err.colno - 1,
        ) from err

    if not isinstance(data, dict):
        raise AutomationMetadataError(f"{METADATA_FILENAME}: must be a JSON object, not {_json_type(data)}")

    values: dict[str, str] = {}
    for name in FIELDS:
        if name not in data:
            continue
        value = data[name]
        if not isinstance(value, str):
            raise AutomationMetadataError(
                f"{METADATA_FILENAME}: field '{name}' must be a string, not {_json_type(value)}"
            )
        values[name] = value

    allow_all = data.get(ALLOW_ALL_IMPORTS, False)
    if not isinstance(allow_all, bool):
        raise AutomationMetadataError(
            f"{METADATA_FILENAME}: field '{ALLOW_ALL_IMPORTS}' must be a boolean, not {_json_type(allow_all)}"
        )

    additional = data.get(ADDITIONAL_IMPORTS, [])
    if not isinstance(additional, list):
        raise AutomationMetadataError(
            f"{METADATA_FILENAME}: field '{ADDITIONAL_IMPORTS}' must be an array of strings, "
            f"not {_json_type(additional)}"
        )
    for index, module in enumerate(additional):
        if not isinstance(module, str):
            raise AutomationMetadataError(
                f"{METADATA_FILENAME}: item {index} of field '{ADDITIONAL_IMPORTS}' must be a string, "
                f"not {_json_type(module)}"
            )

    return AutomationInfo(
        name=values.get("name", folder_name),
        description=values.get("description", ""),
        author=values.get("author", ""),
        version=values.get("version", DEFAULT_VERSION),
        allow_all_imports=allow_all,
        additional_imports=tuple(additional),
    )


def _json_type(value: object) -> str:
    """Name the JSON type of a parsed value, for error messages."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, list):
        return "an array"
    return "an object"


async def load_metadata(files: FileSystem, folder: Path) -> AutomationInfo:
    """Read the metadata of an automation's folder.

    Args:
        files: The file system to read from.
        folder: The automation's folder.

    Returns:
        The metadata; all defaults if the folder has no ``metadata.json``.

    Raises:
        AutomationMetadataError: If the file cannot be read or is not valid.
    """
    path = folder / METADATA_FILENAME
    if not files.exists(path):
        return parse_metadata(None, folder.name)

    try:
        text = await files.read_text(path)
    except (OSError, UnicodeDecodeError) as err:
        raise AutomationMetadataError(f"{METADATA_FILENAME}: cannot be read: {err}") from err
    return parse_metadata(text, folder.name)
