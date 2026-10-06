"""Tests for the layout demo: its rows, and moving, removing and rebuilding."""

from __future__ import annotations

from pathlib import Path

from haanim.testing import AutomationHarness

DEMO = Path(__file__).parents[1] / "demo_layout"


async def test_rows() -> None:
    """The card has rows of 2, 3, 4 and 6 cells below its heading."""
    async with AutomationHarness(DEMO) as automation:
        layout = automation.card.layout
        assert [row["cells"] for row in layout[:5]] == [1, 2, 3, 4, 6]
        assert layout[1] == {"cells": 2, "elements": ["a", "b"]}
        assert layout[2]["elements"] == ["three_one", "three_two", "three_three"]
        assert automation.message == "34 elements in 14 rows"


async def test_a_full_row_ignores_further_elements() -> None:
    """The seventh element added to the row of six is not on the card, and nothing was raised."""
    async with AutomationHarness(DEMO) as automation:
        six = automation.card.layout[4]
        assert six["elements"] == [f"six_{index}" for index in range(6)]
        assert "six_extra" not in [block["id"] for block in automation.card.blocks]


async def test_rows_that_are_not_full() -> None:
    """A row can have fewer elements than cells."""
    async with AutomationHarness(DEMO) as automation:
        assert {"cells": 3, "elements": ["first", "marker"]} in automation.card.layout
        assert {"cells": 3, "elements": ["second"]} in automation.card.layout


async def test_table_made_of_rows() -> None:
    """The table is a heading row and a row per room, all of three cells."""
    async with AutomationHarness(DEMO) as automation:
        layout = automation.card.layout
        head = layout.index({"cells": 3, "elements": ["head_room", "head_temperature", "head_state"]})
        assert layout[head + 1] == {"cells": 3, "elements": ["room_0", "temperature_0", "state_0"]}
        assert layout[head + 2] == {"cells": 3, "elements": ["room_1", "temperature_1", "state_1"]}
        assert automation.card.block("head_room")["markdown"] == "**Room**"
        assert (automation.card.block("state_0")["text"], automation.card.block("state_0")["color"]) == (
            "Heating",
            "warning",
        )


async def test_move() -> None:
    """Adding the badge to the other row moves it; the card never has it twice."""
    async with AutomationHarness(DEMO) as automation:
        assert await automation.press("move") == "second"
        assert {"cells": 3, "elements": ["first"]} in automation.card.layout
        assert {"cells": 3, "elements": ["second", "marker"]} in automation.card.layout
        assert [block["id"] for block in automation.card.blocks].count("marker") == 1
        assert await automation.press("move") == "first"
        assert {"cells": 3, "elements": ["first", "marker"]} in automation.card.layout
        assert automation.message == "The badge is in the first row"


async def test_hide_and_show() -> None:
    """The note is taken off the card, and put back in a row of its own at the bottom."""
    async with AutomationHarness(DEMO) as automation:
        assert await automation.press("hide") is False
        assert "note" not in [block["id"] for block in automation.card.blocks]
        assert await automation.press("hide") is True
        assert automation.card.layout[-1] == {"cells": 1, "elements": ["note"]}
        assert automation.message == "The note is back, at the bottom"


async def test_rebuild_puts_everything_back() -> None:
    """After moving and hiding, building the card again gives the layout it started with."""
    async with AutomationHarness(DEMO) as automation:
        start = automation.card.layout
        await automation.press("move")
        await automation.press("hide")
        assert automation.card.layout != start
        assert await automation.press("rebuild") == 34
        assert automation.card.layout == start
        assert await automation.press("move") == "second", "the rows are the new ones"
