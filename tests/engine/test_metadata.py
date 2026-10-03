"""Tests for the ``metadata.json`` file of an automation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.errors import AutomationMetadataError, HAAnimError
from haanim.engine.metadata import (
    DEFAULT_VERSION,
    FIELDS,
    METADATA_FILENAME,
    AutomationInfo,
    load_metadata,
    parse_metadata,
)
from haanim.testing import FakeFileSystem
from tests.engine.helpers import automation_file, make_context

# The example file of the design's "Metadata" section.
DESIGN_EXAMPLE = """{
  "name": "My Automation",
  "description": "This is a sample automation.",
  "author": "Jane Doe",
  "version": "1.0.0"
}"""

# The default of each field, from the design's table. "name" defaults to the folder name.
DESIGN_DEFAULTS = {"name": "lights", "description": "", "author": "", "version": "1.0.0"}


class TestParseMetadata:
    """Parsing the contents of the file."""

    def test_design_example(self) -> None:
        """The file shown in the design parses to its four values."""
        assert parse_metadata(DESIGN_EXAMPLE, "lights") == AutomationInfo(
            name="My Automation",
            description="This is a sample automation.",
            author="Jane Doe",
            version="1.0.0",
        )

    def test_no_file(self) -> None:
        """Without a file every field takes its default."""
        assert parse_metadata(None, "lights") == AutomationInfo(**DESIGN_DEFAULTS)

    def test_empty_object(self) -> None:
        """A file with no fields gives the defaults."""
        assert parse_metadata("{}", "lights") == AutomationInfo(**DESIGN_DEFAULTS)

    def test_fields_are_the_designs(self) -> None:
        """The fields are exactly the four of the design's table."""
        assert set(FIELDS) == set(DESIGN_DEFAULTS)
        assert DEFAULT_VERSION == "1.0.0"

    @pytest.mark.parametrize("field", FIELDS)
    def test_each_default(self, field: str) -> None:
        """A missing field takes its default while the others keep their values."""
        given = {"name": "N", "description": "D", "author": "A", "version": "9"}
        del given[field]

        info = parse_metadata(json.dumps(given), "lights")

        assert getattr(info, field) == DESIGN_DEFAULTS[field]
        for other, value in given.items():
            assert getattr(info, other) == value

    @pytest.mark.parametrize("field", FIELDS)
    def test_each_field_alone(self, field: str) -> None:
        """A file with one field sets that field and defaults the rest."""
        info = parse_metadata(json.dumps({field: "given"}), "lights")

        assert getattr(info, field) == "given"
        for other in FIELDS:
            if other != field:
                assert getattr(info, other) == DESIGN_DEFAULTS[other]

    def test_name_defaults_to_the_folder_name_as_written(self) -> None:
        """The display name is the folder name, not the ID."""
        assert parse_metadata(None, "Café  Lights.v2").name == "Café  Lights.v2"

    def test_empty_strings_are_kept(self) -> None:
        """An empty string is a value, not a missing field."""
        info = parse_metadata('{"name": "", "version": ""}', "lights")

        assert (info.name, info.version) == ("", "")

    def test_unknown_fields_are_ignored(self) -> None:
        """Fields the design does not define do not stop the automation from loading."""
        info = parse_metadata('{"name": "N", "dependencies": ["x"], "icon": 5}', "lights")

        assert info == AutomationInfo(name="N")

    def test_unicode(self) -> None:
        """Non-ASCII text is kept."""
        assert parse_metadata('{"author": "Zoë Ångström"}', "lights").author == "Zoë Ångström"

    @pytest.mark.parametrize(
        ("field", "value", "kind"),
        [
            (field, value, kind)
            for field in FIELDS
            for value, kind in [
                (5, "a number"),
                (1.5, "a number"),
                (True, "a boolean"),
                (None, "null"),
                (["x"], "an array"),
                ({"x": 1}, "an object"),
            ]
        ],
    )
    def test_each_invalid_field(self, field: str, value: Any, kind: str) -> None:
        """A field that is not a string is a load error naming the field and what it is."""
        text = json.dumps({"name": "N", field: value})

        with pytest.raises(AutomationMetadataError) as raised:
            parse_metadata(text, "lights")

        assert str(raised.value) == f"metadata.json: field '{field}' must be a string, not {kind}"

    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("[]", "an array"),
            ('"text"', "a string"),
            ("5", "a number"),
            ("null", "null"),
            ("true", "a boolean"),
        ],
    )
    def test_not_an_object(self, text: str, kind: str) -> None:
        """A file whose top level is not an object is a load error."""
        with pytest.raises(
            AutomationMetadataError, match=f"^metadata.json: must be a JSON object, not {kind}$"
        ):
            parse_metadata(text, "lights")

    @pytest.mark.parametrize(
        ("text", "lineno"),
        [
            ("{", 1),
            ("", 1),
            ('{"name": "N",}', 1),
            ("{'name': 'N'}", 1),
            ('{\n  "name": "N"\n  "author": "A"\n}', 3),
            ("not json", 1),
        ],
        ids=["unclosed", "empty file", "trailing comma", "single quotes", "missing comma", "text"],
    )
    def test_invalid_json(self, text: str, lineno: int) -> None:
        """A file that is not valid JSON is a load error with the line."""
        with pytest.raises(AutomationMetadataError) as raised:
            parse_metadata(text, "lights")

        assert str(raised.value).startswith(f"metadata.json:{lineno}: not valid JSON: ")
        assert raised.value.lineno == lineno
        assert isinstance(raised.value.__cause__, json.JSONDecodeError)

    def test_error_is_a_haanim_error(self) -> None:
        """The error is handled like every other load error."""
        assert issubclass(AutomationMetadataError, HAAnimError)

    def test_info_is_immutable(self) -> None:
        """Metadata cannot be changed after it is read."""
        info = AutomationInfo(name="N")

        with pytest.raises(AttributeError):
            info.name = "M"  # type: ignore[misc]


class TestLoadMetadata:
    """Reading the file from an automation's folder."""

    async def test_missing_file(self) -> None:
        """A folder without the file gives the defaults."""
        files = FakeFileSystem()
        files.write("/automations/lights/main.py", "")

        assert await load_metadata(files, Path("/automations/lights")) == AutomationInfo(**DESIGN_DEFAULTS)

    async def test_reads_the_file(self) -> None:
        """The file in the folder is read."""
        files = FakeFileSystem()
        files.write(f"/automations/lights/{METADATA_FILENAME}", DESIGN_EXAMPLE)

        info = await load_metadata(files, Path("/automations/lights"))

        assert info.name == "My Automation"
        assert info.author == "Jane Doe"

    async def test_invalid_file(self) -> None:
        """An invalid file raises."""
        files = FakeFileSystem()
        files.write("/automations/lights/metadata.json", '{"version": 2}')

        with pytest.raises(AutomationMetadataError, match="field 'version' must be a string"):
            await load_metadata(files, Path("/automations/lights"))

    async def test_unreadable_file(self) -> None:
        """A file that cannot be read is a load error, not an OSError."""
        files = FakeFileSystem()
        files.write("/automations/lights/metadata.json", "{}")
        files.make_unreadable("/automations/lights/metadata.json")

        with pytest.raises(AutomationMetadataError, match="^metadata.json: cannot be read: "):
            await load_metadata(files, Path("/automations/lights"))


class TestMetadataAtLoad:
    """The metadata is part of loading an automation."""

    async def test_metadata_is_in_the_loaded_automation(self, tmp_path: Path) -> None:
        """A loaded automation carries the values of its file."""
        path = automation_file(tmp_path, "lights")
        path.write_text("x = 1\n", encoding="utf-8")
        (path.parent / "metadata.json").write_text(DESIGN_EXAMPLE, encoding="utf-8")

        metadata = await make_context(str(path)).load()

        assert metadata.id == "lights"
        assert (metadata.name, metadata.description, metadata.author, metadata.version) == (
            "My Automation",
            "This is a sample automation.",
            "Jane Doe",
            "1.0.0",
        )

    async def test_defaults_without_a_file(self, tmp_path: Path) -> None:
        """Without the file a loaded automation has the defaults."""
        path = automation_file(tmp_path, "Garden Pump")
        path.write_text("x = 1\n", encoding="utf-8")

        metadata = await make_context(str(path)).load()

        assert metadata.id == "garden_pump"
        assert (metadata.name, metadata.description, metadata.author, metadata.version) == (
            "Garden Pump",
            "",
            "",
            "1.0.0",
        )

    @pytest.mark.parametrize(
        "text", ["{", '{"author": 5}', "[]"], ids=["invalid json", "wrong type", "not an object"]
    )
    async def test_invalid_metadata_is_a_load_error_and_nothing_runs(self, tmp_path: Path, text: str) -> None:
        """An invalid file fails the load before any code of the automation runs."""
        path = automation_file(tmp_path, "lights")
        path.write_text("ran = True\n", encoding="utf-8")
        (path.parent / "metadata.json").write_text(text, encoding="utf-8")
        context = make_context(str(path))

        with pytest.raises(AutomationMetadataError, match="^metadata.json"):
            await context.load()

        assert context.get_symbol("ran") is None
        assert not context.is_loaded
