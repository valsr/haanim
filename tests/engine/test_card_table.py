"""Tests for the table element of cards: columns, rows of values, units and a title."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from haanim.engine.card import HAAnimCard
from haanim.engine.card_elements import MAX_TABLE_COLUMNS, MAX_TABLE_ROWS, TableElement
from haanim.testing import AutomationHarness, FakeCardSink
from tests.engine.test_card import card, sink  # noqa: F401  pylint: disable=unused-import

ROWS = [["Kitchen", 21.5, 40], ["Bedroom", 19.0, 45]]


def table(card: HAAnimCard, **arguments: Any) -> TableElement:  # noqa: F811
    arguments.setdefault("columns", ["Room", "Temperature", "Humidity"])
    arguments.setdefault("rows", ROWS)
    return card.create_table("rooms", **arguments)


def test_create(card: HAAnimCard) -> None:  # noqa: F811
    element = table(card, units=["", "°C", "%"], title="Climate")
    assert element.as_dict() == {
        "id": "rooms",
        "type": "table",
        "title": "Climate",
        "columns": ["Room", "Temperature", "Humidity"],
        "units": ["", "°C", "%"],
        "rows": [["Kitchen", 21.5, 40], ["Bedroom", 19.0, 45]],
    }
    assert (element.columns, element.units, element.title) == (
        ["Room", "Temperature", "Humidity"],
        ["", "°C", "%"],
        "Climate",
    )
    assert element.rows == ROWS


def test_defaults(card: HAAnimCard) -> None:  # noqa: F811
    element = card.create_table("log", columns=["When", "What"])
    assert element.content == {"title": None, "columns": ["When", "What"], "units": ["", ""], "rows": []}


def test_none_and_booleans_are_cells(card: HAAnimCard) -> None:  # noqa: F811
    element = card.create_table("t", columns=["A", "B"], rows=[[None, True]])
    assert element.rows == [[None, True]]


def test_rows_are_copies(card: HAAnimCard) -> None:  # noqa: F811
    rows = [["Kitchen", 1, 2]]
    element = table(card, rows=rows)
    rows[0][1] = 99
    element.rows[0][1] = 98
    assert element.rows == [["Kitchen", 1, 2]]


@pytest.mark.parametrize(
    "arguments, error, message",
    [
        ({"columns": []}, ValueError, "column"),
        ({"columns": ["A"] * (MAX_TABLE_COLUMNS + 1), "rows": []}, ValueError, "column"),
        ({"columns": ["A", 3]}, TypeError, "column"),
        ({"rows": [["Kitchen", 1]]}, ValueError, "row 0"),
        ({"rows": [["Kitchen", 1, 2], ["Bedroom", 1]]}, ValueError, "row 1"),
        ({"rows": [["Kitchen", [1], 2]]}, TypeError, "row 0"),
        ({"rows": [["Kitchen", float("nan"), 2]]}, ValueError, "finite"),
        ({"rows": [["x" * 10_001, 1, 2]]}, ValueError, "characters"),
        ({"rows": [["Kitchen", 1, 2]] * (MAX_TABLE_ROWS + 1)}, ValueError, "rows"),
        ({"units": ["", "°C"]}, ValueError, "units"),
        ({"rows": "Kitchen"}, TypeError, "rows"),
        ({"columns": "Room"}, TypeError, "columns must be a list"),
        ({"columns": 3}, TypeError, "columns must be a list"),
    ],
)
def test_invalid(
    card: HAAnimCard, arguments: dict[str, Any], error: type, message: str
) -> None:  # noqa: F811
    with pytest.raises(error, match=message):
        table(card, **arguments)


def test_add_row(card: HAAnimCard) -> None:  # noqa: F811
    element = table(card)
    element.add_row(["Office", 22.1, 38])
    assert element.rows[-1] == ["Office", 22.1, 38]
    with pytest.raises(ValueError, match="row 3"):
        element.add_row(["Hall", 1])
    assert len(element.rows) == 3


def test_add_row_with_limit_drops_the_oldest(card: HAAnimCard) -> None:  # noqa: F811
    element = card.create_table("log", columns=["N"])
    for n in range(5):
        element.add_row([n], limit=3)
    assert element.rows == [[2], [3], [4]]


@pytest.mark.parametrize("limit", [0, -1])
def test_add_row_with_a_limit_below_one_is_refused(card: HAAnimCard, limit: int) -> None:  # noqa: F811
    element = card.create_table("log", columns=["N"], rows=[[1]])
    with pytest.raises(ValueError, match="limit must be at least 1"):
        element.add_row([2], limit=limit)
    assert element.rows == [[1]], "nothing is added"


def test_add_row_beyond_the_maximum_is_refused(card: HAAnimCard) -> None:  # noqa: F811
    element = card.create_table("log", columns=["N"], rows=[[n] for n in range(MAX_TABLE_ROWS)])
    with pytest.raises(ValueError, match="rows"):
        element.add_row([1])


def test_set_rows_cell_clear(card: HAAnimCard) -> None:  # noqa: F811
    element = table(card)
    element.set_cell(0, 1, 21.8)
    assert element.rows[0] == ["Kitchen", 21.8, 40]
    with pytest.raises(IndexError):
        element.set_cell(5, 0, "x")
    with pytest.raises(IndexError):
        element.set_cell(0, 3, "x")
    element.set_rows([["Office", 1, 2]])
    assert element.rows == [["Office", 1, 2]]
    element.clear()
    assert element.rows == []
    assert element.columns == ["Room", "Temperature", "Humidity"]


def test_set_columns_and_title(card: HAAnimCard) -> None:  # noqa: F811
    element = card.create_table("t", columns=["A"], rows=[[1]])
    with pytest.raises(ValueError, match="row 0"):
        element.set_columns(["A", "B"])
    element.clear()
    element.set_columns(["A", "B"], units=["kWh", ""])
    assert (element.columns, element.units) == (["A", "B"], ["kWh", ""])
    element.set_title("Energy")
    assert element.title == "Energy"
    element.set_title(None)
    assert element.title is None


def test_a_change_reaches_the_card(card: HAAnimCard, sink: FakeCardSink) -> None:  # noqa: F811
    element = table(card)
    card.add_element(element)
    before = len(sink.updates)
    element.add_row(["Office", 22.1, 38])
    assert len(sink.updates) == before + 1
    assert sink.cards["climate"][0]["rows"][-1] == ["Office", 22.1, 38]


async def test_in_an_automation(tmp_path: Path) -> None:
    folder = tmp_path / "rooms"
    folder.mkdir()
    (folder / "main.py").write_text(
        "from haanim import action, haa, startup\n"
        "rooms = haa.card.create_table('rooms', columns=['Room', 'Temp'], units=['', '°C'])\n"
        "@startup\ndef build(event):\n    haa.card.add_element(rooms)\n"
        "@action\ndef record(event):\n    rooms.add_row([event.data['room'], event.data['temp']], limit=2)\n"
    )
    async with AutomationHarness(folder) as automation:
        for room, temp in [("Kitchen", 21), ("Bedroom", 19), ("Office", 22)]:
            await automation.call("record", room=room, temp=temp)
        assert automation.card.block("rooms")["rows"] == [["Bedroom", 19], ["Office", 22]]


def test_a_string_row_is_refused(card: HAAnimCard) -> None:  # noqa: F811
    with pytest.raises(TypeError, match="row 0"):
        card.create_table("t", columns=["A", "B", "C"], rows=["abc"])
    element = card.create_table("t", columns=["A", "B", "C"])
    with pytest.raises(TypeError, match="row 0"):
        element.add_row("abc")  # type: ignore[arg-type]


def test_later_changes_to_the_given_rows_do_not_leak_in(card: HAAnimCard) -> None:  # noqa: F811
    rows = [["Kitchen", 1, 2]]
    element = table(card, rows=rows)
    rows[0][1] = 99
    element.set_title("Climate")
    assert element.rows == [["Kitchen", 1, 2]]
