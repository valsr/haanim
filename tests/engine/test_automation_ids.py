"""Tests for deriving automation IDs from folder names."""

from __future__ import annotations

import dataclasses
import itertools
import re

import pytest

from haanim.engine.automation_ids import (
    REASON_COLLISION,
    REASON_EMPTY,
    IdAssignment,
    RejectedFolder,
    assign_ids,
    automation_id,
)

# The example table of the design's "Automation Id" section, row for row.
DESIGN_TABLE = [
    ("My Automation", "my_automation"),
    ("my-automation", "my_automation"),
    ("Café  Lights.v2", "cafe_lights_v2"),
    ("3d_printer", "3d_printer"),
    ("---", ""),
]

# Further names, each exercising one of the design's three rules.
FURTHER_NAMES = [
    # Letters are lowercased and accented letters are transliterated to ASCII
    ("LIGHTS", "lights"),
    ("Küche", "kuche"),
    ("Straße", "strasse"),
    ("naïve", "naive"),
    ("Ærø", "aero"),
    ("İstanbul", "istanbul"),
    ("Привет", "privet"),
    ("ＡＢＣ", "abc"),
    # Every run of characters other than a-z and 0-9 becomes a single underscore
    ("a b", "a_b"),
    ("a   b", "a_b"),
    ("a__b", "a_b"),
    ("a.b-c d", "a_b_c_d"),
    ("a+b", "a_b"),
    ("tab\there", "tab_here"),
    ("lights (old)", "lights_old"),
    # Leading and trailing underscores are removed
    ("_private", "private"),
    ("trailing_", "trailing"),
    ("  spaced  ", "spaced"),
    ("__init__", "init"),
    ("100%", "100"),
    # Names that are already IDs are unchanged
    ("lights", "lights"),
    ("a", "a"),
    ("1", "1"),
    ("living_room_2", "living_room_2"),
    # Names with nothing usable
    ("", ""),
    ("   ", ""),
    ("_", ""),
    ("...", ""),
]


class TestAutomationId:
    """The ID is the slug of the folder name."""

    @pytest.mark.parametrize(("folder", "expected"), DESIGN_TABLE)
    def test_design_table(self, folder: str, expected: str) -> None:
        """Every row of the design's table gives the ID the design states."""
        assert automation_id(folder) == expected

    @pytest.mark.parametrize(("folder", "expected"), FURTHER_NAMES)
    def test_rules(self, folder: str, expected: str) -> None:
        """Each rule of the design holds."""
        assert automation_id(folder) == expected

    @pytest.mark.parametrize(("folder", "expected"), DESIGN_TABLE + FURTHER_NAMES)
    def test_id_has_only_allowed_characters(self, folder: str, expected: str) -> None:
        """An ID is empty or made of a-z, 0-9 and single underscores between them."""
        slug = automation_id(folder)

        assert re.fullmatch(r"([a-z0-9]+(_[a-z0-9]+)*)?", slug)

    @pytest.mark.parametrize(("folder", "expected"), DESIGN_TABLE + FURTHER_NAMES)
    def test_id_of_an_id_is_itself(self, folder: str, expected: str) -> None:
        """Deriving an ID from an ID changes nothing."""
        assert automation_id(expected) == expected


class TestAssignIds:
    """Collisions and invalid names."""

    def test_design_table_as_a_set(self) -> None:
        """The design's five folders together: one collision, one empty name."""
        result = assign_ids(folder for folder, _ in DESIGN_TABLE)

        assert result.loaded == {
            "3d_printer": "3d_printer",
            "cafe_lights_v2": "Café  Lights.v2",
            "my_automation": "My Automation",
        }
        assert result.rejected == [
            RejectedFolder("---", REASON_EMPTY),
            RejectedFolder("my-automation", REASON_COLLISION, "my_automation", "My Automation"),
        ]

    def test_no_folders(self) -> None:
        """Nothing in, nothing out."""
        assert assign_ids([]) == IdAssignment(loaded={}, rejected=[])

    def test_distinct_folders_are_all_loaded(self) -> None:
        """Folders with different IDs do not affect each other."""
        result = assign_ids(["lights", "Heating", "garden pump"])

        assert result.loaded == {"garden_pump": "garden pump", "heating": "Heating", "lights": "lights"}
        assert result.rejected == []

    def test_loaded_is_in_ascending_order_of_id(self) -> None:
        """The loaded mapping iterates in the order automations are loaded in."""
        result = assign_ids(["Zeta", "alpha", "Mid", "3d"])

        assert list(result.loaded) == ["3d", "alpha", "mid", "zeta"]

    @pytest.mark.parametrize(
        ("folders", "winner"),
        [
            (["my-automation", "My Automation"], "My Automation"),
            (["lights", "Lights"], "Lights"),
            (["lights", "LIGHTS", "Lights"], "LIGHTS"),
            (["a_b", "a b", "a-b", "a.b"], "a b"),
            (["cafe", "café"], "cafe"),
            (["Z", "a", "A", "z"], "A"),
            (["lights_", "lights"], "lights"),
        ],
        ids=[
            "design example",
            "case",
            "three way",
            "separators",
            "accent",
            "upper before lower",
            "prefix first",
        ],
    )
    def test_first_by_code_point_wins(self, folders: list[str], winner: str) -> None:
        """Of the folders with one ID, the name that sorts first by code point is loaded."""
        same_id = [folder for folder in folders if automation_id(folder) == automation_id(winner)]

        result = assign_ids(folders)

        assert winner == min(same_id)
        assert result.loaded[automation_id(winner)] == winner
        losers = [rejected for rejected in result.rejected if rejected.automation_id == automation_id(winner)]
        assert sorted(rejected.folder for rejected in losers) == sorted(set(same_id) - {winner})
        assert all(rejected.reason == REASON_COLLISION and rejected.winner == winner for rejected in losers)

    def test_code_point_order_not_alphabetical(self) -> None:
        """Uppercase sorts before lowercase, and a space before a hyphen: code points, not locale."""
        assert assign_ids(["b-c", "b c"]).loaded == {"b_c": "b c"}
        assert assign_ids(["éclair", "Eclair", "eclair"]).loaded == {"eclair": "Eclair"}

    def test_rejected_names_the_winner_and_the_id(self) -> None:
        """A rejected collision says which ID it wanted and which folder has it."""
        (rejected,) = assign_ids(["Lights", "lights"]).rejected

        assert rejected == RejectedFolder(
            folder="lights", reason=REASON_COLLISION, automation_id="lights", winner="Lights"
        )

    @pytest.mark.parametrize("folder", ["---", "", "   ", "_", "..."])
    def test_empty_slug_is_rejected(self, folder: str) -> None:
        """A folder whose name gives no ID is not loaded and has no winner."""
        result = assign_ids([folder, "lights"])

        assert result.loaded == {"lights": "lights"}
        assert result.rejected == [RejectedFolder(folder, REASON_EMPTY, automation_id="", winner=None)]

    def test_several_empty_names_do_not_collide(self) -> None:
        """Empty names are each rejected as empty, not as collisions with each other."""
        result = assign_ids(["---", "...", "_"])

        assert result.loaded == {}
        assert [(rejected.folder, rejected.reason) for rejected in result.rejected] == [
            ("---", REASON_EMPTY),
            ("...", REASON_EMPTY),
            ("_", REASON_EMPTY),
        ]

    def test_rejected_is_in_ascending_order_of_name(self) -> None:
        """Rejected folders are listed in a stable order."""
        result = assign_ids(["b b", "b-b", "a-a", "a a", "---"])

        assert [rejected.folder for rejected in result.rejected] == ["---", "a-a", "b-b"]

    def test_result_does_not_depend_on_input_order(self) -> None:
        """Any order of the same folders gives the same assignment."""
        folders = ["My Automation", "my-automation", "---", "lights", "Lights"]
        expected = assign_ids(folders)

        for permutation in itertools.permutations(folders):
            assert assign_ids(permutation) == expected

    def test_duplicate_names_count_once(self) -> None:
        """The same folder name given twice is one folder, not a collision with itself."""
        result = assign_ids(["lights", "lights"])

        assert result.loaded == {"lights": "lights"}
        assert result.rejected == []

    def test_accepts_any_iterable(self) -> None:
        """Folder names can come from a generator or a set."""
        assert assign_ids({"lights"}).loaded == {"lights": "lights"}
        assert assign_ids(name for name in ("lights",)).loaded == {"lights": "lights"}

    def test_every_folder_is_accounted_for(self) -> None:
        """Each folder is either loaded or rejected, never both and never dropped."""
        folders = [folder for folder, _ in DESIGN_TABLE + FURTHER_NAMES]

        result = assign_ids(folders)

        loaded = set(result.loaded.values())
        rejected = {entry.folder for entry in result.rejected}
        assert loaded | rejected == set(folders)
        assert not loaded & rejected
        assert all(automation_id(folder) == slug for slug, folder in result.loaded.items())

    def test_results_are_immutable_records(self) -> None:
        """The records cannot be changed by a caller."""
        rejected = RejectedFolder("x", REASON_EMPTY)

        with pytest.raises(dataclasses.FrozenInstanceError):
            rejected.folder = "y"  # type: ignore[misc]
