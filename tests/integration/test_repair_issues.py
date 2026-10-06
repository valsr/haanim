"""Tests for the repair issues of folders that are not loaded because of their name.

See "Automation Id", "Collisions and invalid names" in the design.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.haanim.automation_manager import AutomationManager
from custom_components.haanim.const import DOMAIN
from haanim.engine.discovery import ISSUE_EMPTY_ID, ISSUE_ID_COLLISION
from tests.integration.test_sensor import manager, root, write  # noqa: F401  pylint: disable=unused-import

COMPONENT = Path(__file__).parents[2] / "custom_components" / "haanim"

PLACEHOLDERS = {
    ISSUE_EMPTY_ID: {"folder"},
    ISSUE_ID_COLLISION: {"folder", "winner", "automation_id"},
}


@pytest.fixture
def root(tmp_path: Path) -> Path:  # noqa: F811
    """An automations folder with a nameless folder and two folders that give the same ID."""
    write(tmp_path, "---", "x = 1\n")
    write(tmp_path, "My Lights", "x = 1\n")
    write(tmp_path, "my_lights", "x = 1\n")
    write(tmp_path, "fine", "x = 1\n")
    return tmp_path


def issues(hass: HomeAssistant) -> dict[str, ir.IssueEntry]:
    """Return the HAAnim repair issues by issue ID."""
    return {
        issue_id: issue for (domain, issue_id), issue in ir.async_get(hass).issues.items() if domain == DOMAIN
    }


@pytest.mark.usefixtures("manager")
class TestIssues:
    """Rule: each folder that is not loaded because of its name is a repair issue."""

    async def test_issue_per_rejected_folder(self, hass: HomeAssistant) -> None:
        """Test the nameless folder and the collision's loser each have an issue; nothing else has."""
        assert sorted(issues(hass)) == ["rejected_folder_---", "rejected_folder_my_lights"]
        assert sorted(hass.states.async_entity_ids("sensor")) == [
            "sensor.haanim_fine",
            "sensor.haanim_my_lights",
        ]

    async def test_folder_without_id(self, hass: HomeAssistant) -> None:
        """Test the issue of a folder that gives no ID names the folder."""
        issue = issues(hass)["rejected_folder_---"]
        assert issue.translation_key == "folder_without_id"
        assert issue.translation_placeholders == {"folder": "---"}

    async def test_collision(self, hass: HomeAssistant) -> None:
        """Test the issue of a collision names the folder, the ID and the folder that won."""
        issue = issues(hass)["rejected_folder_my_lights"]
        assert issue.translation_key == "folder_id_collision"
        assert issue.translation_placeholders == {
            "folder": "my_lights",
            "automation_id": "my_lights",
            "winner": "My Lights",
        }

    async def test_owner_fixes_it_by_hand(self, hass: HomeAssistant) -> None:
        """Test the issues are warnings that cannot be fixed from the UI."""
        for issue in issues(hass).values():
            assert issue.is_fixable is False
            assert issue.severity is ir.IssueSeverity.WARNING

    async def test_cleared_when_renamed(self, hass: HomeAssistant, root: Path) -> None:  # noqa: F811
        """Test renaming the folders clears their issues at the next rescan and loads them."""
        (root / "---").rename(root / "named")
        (root / "my_lights").rename(root / "other_lights")

        await hass.services.async_call(DOMAIN, "reload", {}, blocking=True)
        await hass.async_block_till_done()

        assert issues(hass) == {}
        assert hass.states.get("sensor.haanim_named").state == "on"
        assert hass.states.get("sensor.haanim_other_lights").state == "on"

    async def test_cleared_when_removed(
        self, hass: HomeAssistant, manager: AutomationManager, root: Path  # noqa: F811
    ) -> None:
        """Test removing the winner of a collision clears the loser's issue and loads the loser."""
        for path in sorted((root / "My Lights").iterdir()):
            path.unlink()
        (root / "My Lights").rmdir()

        await hass.services.async_call(DOMAIN, "reload", {}, blocking=True)
        await hass.async_block_till_done()

        assert sorted(issues(hass)) == ["rejected_folder_---"]
        assert manager.automation_state("my_lights") == "on"

    async def test_raised_at_a_rescan(self, hass: HomeAssistant, root: Path) -> None:  # noqa: F811
        """Test a folder that appears later with a colliding name gets its issue at the rescan."""
        write(root, "FINE", "x = 1\n")
        await hass.services.async_call(DOMAIN, "reload", {}, blocking=True)
        await hass.async_block_till_done()

        issue = issues(hass)["rejected_folder_fine"]
        assert issue.translation_placeholders == {"folder": "fine", "automation_id": "fine", "winner": "FINE"}


class TestTranslations:
    """Every kind of issue has a text, and the text uses the placeholders the issue gives."""

    @pytest.mark.parametrize("filename", ["strings.json", "translations/en.json"])
    @pytest.mark.parametrize("key", sorted(PLACEHOLDERS))
    def test_text(self, filename: str, key: str) -> None:
        """Test title and description exist and only use placeholders the issue has."""
        texts = json.loads((COMPONENT / filename).read_text(encoding="utf-8"))["issues"]
        assert sorted(texts) == sorted(PLACEHOLDERS)
        used = set(re.findall(r"{(\w+)}", texts[key]["title"] + texts[key]["description"]))
        assert texts[key]["title"] and texts[key]["description"]
        assert used == PLACEHOLDERS[key]
