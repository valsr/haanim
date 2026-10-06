"""Tests for the card content model: ``haa.card``.

See "GUI", "Card Content" in the design.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.assets import AssetStore
from haanim.engine.card import (
    CARD_PARTS,
    GRAPH_KINDS,
    MAX_BLOCKS,
    MAX_GRAPH_HOURS,
    MAX_GRAPH_POINTS,
    MAX_GRAPH_SERIES,
    MAX_TEXT_LENGTH,
    HAAnimCard,
)
from haanim.testing import FakeCardSink, FakeClock, FakeFileSystem
from tests.engine.test_lifecycle import World, world  # noqa: F401  pylint: disable=unused-import

FOLDER = Path("/automations/climate")


@pytest.fixture
def sink() -> FakeCardSink:
    """Where the card content goes."""
    return FakeCardSink()


@pytest.fixture
def card(sink: FakeCardSink) -> HAAnimCard:
    """The card of an automation with a logo asset and a reset_alerts action."""
    files = FakeFileSystem()
    files.write(FOLDER / "assets/logo.png", b"\x89PNG")
    files.write(FOLDER / "main.py", "x = 1")
    assets = AssetStore("climate", FOLDER, files)
    return HAAnimCard("climate", assets, lambda name: name in ("reset_alerts", "reset"), sink)


def fill(card: HAAnimCard) -> None:
    """Build the card of the design's example."""
    card.text("intro", "## Climate\nKeeps the house between **19** and **23** °C.")
    card.image("logo", asset="logo.png", alt="Climate logo")
    card.value("alerts", label="Alerts today", value=0)
    card.entity("temp", "sensor.temperature")
    card.button("reset", label="Reset counter", action="reset_alerts", confirm="Reset the counter?")


class TestBlocks:
    """The table of methods: each one shows a block of its type."""

    def test_text(self, card: HAAnimCard) -> None:
        """Test a text block holds its markdown."""
        card.text("intro", "## Climate")
        assert card.blocks == [{"id": "intro", "type": "text", "markdown": "## Climate"}]

    def test_image_from_asset(self, card: HAAnimCard) -> None:
        """Test an image from assets/ gets the asset's URL."""
        card.image("logo", asset="logo.png", alt="Climate logo")
        assert card.blocks == [
            {
                "id": "logo",
                "type": "image",
                "asset": "logo.png",
                "url": "/api/haanim/assets/climate/logo.png",
                "alt": "Climate logo",
            }
        ]

    def test_image_from_url(self, card: HAAnimCard) -> None:
        """Test an image from a URL keeps the URL; alt is empty by default."""
        card.image("pic", url="https://example.com/a.png")
        assert card.blocks == [{"id": "pic", "type": "image", "url": "https://example.com/a.png", "alt": ""}]

    @pytest.mark.parametrize("value", ["on", "", 0, 42, -1.5, True, False])
    def test_value(self, card: HAAnimCard, value: Any) -> None:
        """Test a value block holds a string, number or boolean, as it is."""
        card.value("alerts", label="Alerts today", value=value, unit="x")
        (block,) = card.blocks
        assert block == {
            "id": "alerts",
            "type": "value",
            "label": "Alerts today",
            "value": value,
            "unit": "x",
        }
        assert type(block["value"]) is type(value)

    def test_value_unit_is_optional(self, card: HAAnimCard) -> None:
        """Test the unit is empty by default."""
        card.value("alerts", "Alerts", 3)
        assert card.blocks[0]["unit"] == ""

    def test_entity(self, card: HAAnimCard) -> None:
        """Test an entity block holds the entity ID."""
        card.entity("temp", "sensor.temperature")
        assert card.blocks == [{"id": "temp", "type": "entity", "entity_id": "sensor.temperature"}]

    def test_icon_following_an_entity(self, card: HAAnimCard) -> None:
        """Test an icon with an entity follows it by default."""
        card.icon("fan", "fan.bedroom")
        assert card.blocks == [
            {
                "id": "fan",
                "type": "icon",
                "entity_id": "fan.bedroom",
                "icon": None,
                "label": None,
                "color": None,
                "spin": False,
                "follow_entity": True,
            }
        ]

    def test_icon_with_everything(self, card: HAAnimCard) -> None:
        """Test an icon keeps its icon, label, colour and spin."""
        card.icon("fan", "fan.bedroom", icon="mdi:fan", label="Fan", color="success", spin=True)
        block = card.blocks[0]
        assert (block["icon"], block["label"], block["color"], block["spin"]) == (
            "mdi:fan",
            "Fan",
            "success",
            True,
        )
        assert block["follow_entity"] is True

    def test_icon_not_following(self, card: HAAnimCard) -> None:
        """Test follow_entity=False keeps the entity but does not follow it."""
        card.icon("fan", "fan.bedroom", icon="mdi:fan", follow_entity=False)
        assert card.blocks[0]["follow_entity"] is False
        assert card.blocks[0]["entity_id"] == "fan.bedroom"

    def test_icon_without_an_entity(self, card: HAAnimCard) -> None:
        """Test an icon without an entity has nothing to follow."""
        card.icon("home", icon="mdi:home-outline", color="#03a9f4")
        assert card.blocks[0]["entity_id"] is None
        assert card.blocks[0]["follow_entity"] is False

    @pytest.mark.parametrize("icon", ["mdi:fan", "mdi:fan-off", "hass:water-percent", "mdi:numeric-1-box"])
    def test_icon_names(self, card: HAAnimCard, icon: str) -> None:
        """Test icons are named set:name."""
        card.icon("i", icon=icon)
        assert card.blocks[0]["icon"] == icon

    @pytest.mark.parametrize("color", ["primary", "red", "dark-orange", "#fff", "#03a9f4", "#03a9f480"])
    def test_icon_colors(self, card: HAAnimCard, color: str) -> None:
        """Test a colour is a name or a hex value."""
        card.icon("i", icon="mdi:fan", color=color)
        assert card.blocks[0]["color"] == color

    def test_graph_of_entities(self, card: HAAnimCard) -> None:
        """Test a history graph keeps its entities and time span; one entity can be given as text."""
        card.graph("temp", "sensor.temperature")
        assert card.blocks == [
            {
                "id": "temp",
                "type": "graph",
                "kind": "line",
                "title": None,
                "unit": None,
                "min": None,
                "max": None,
                "entities": ["sensor.temperature"],
                "hours": 24.0,
            }
        ]
        card.graph(
            "temp", ("sensor.indoor", "sensor.outdoor"), hours=6, kind="area", title="Temperatures", unit="°C"
        )
        block = card.blocks[0]
        assert block["entities"] == ["sensor.indoor", "sensor.outdoor"]
        assert (block["hours"], block["kind"], block["title"], block["unit"]) == (
            6.0,
            "area",
            "Temperatures",
            "°C",
        )

    def test_graph_of_plain_numbers(self, card: HAAnimCard) -> None:
        """Test numbers are drawn one after the other; None is a gap."""
        card.graph("g", series={"Alerts": [1, 2.5, None, 4], "Resets": (0, 1)}, kind="bar", min=0, max=10)
        block = card.blocks[0]
        assert block["series"] == {
            "Alerts": [[0.0, 1.0], [1.0, 2.5], [2.0, None], [3.0, 4.0]],
            "Resets": [[0.0, 0.0], [1.0, 1.0]],
        }
        assert (block["x"], block["kind"], block["min"], block["max"]) == ("index", "bar", 0.0, 10.0)
        assert "entities" not in block

    def test_graph_of_number_pairs(self, card: HAAnimCard) -> None:
        """Test (x, y) pairs keep their positions."""
        card.graph("g", series={"Curve": [(0, 0), (2.5, 6), [10, None]]})
        assert card.blocks[0]["series"] == {"Curve": [[0.0, 0.0], [2.5, 6.0], [10.0, None]]}
        assert card.blocks[0]["x"] == "number"

    def test_graph_over_time(self, card: HAAnimCard) -> None:
        """Test times are ISO text or aware datetimes, and become seconds since 1970."""
        noon = datetime(2025, 1, 6, 12, 0, tzinfo=timezone.utc)
        card.graph(
            "g",
            series={
                "Power": [(noon, 100), ("2025-01-06T13:00:00+00:00", 150), ("2025-01-06 15:00+01:00", 90)]
            },
        )
        block = card.blocks[0]
        assert block["x"] == "time"
        assert block["series"]["Power"] == [
            [noon.timestamp(), 100.0],
            [noon.timestamp() + 3600, 150.0],
            [noon.timestamp() + 7200, 90.0],
        ]

    def test_graph_of_states(self, card: HAAnimCard) -> None:
        """Test a series can be states instead of numbers, in each of the three forms; None is a gap."""
        noon = datetime(2025, 1, 6, 12, 0, tzinfo=timezone.utc)
        card.graph("modes", series={"Mode": ["heat", "heat", None, "off"]})
        card.graph("pump", series={"Pump": [(0, "on"), (6.5, "off")]})
        card.graph("door", series={"Door": [(noon, "open"), ("2025-01-06T12:05:00+00:00", "closed")]})
        modes, pump, door = card.blocks
        assert modes["series"] == {"Mode": [[0.0, "heat"], [1.0, "heat"], [2.0, None], [3.0, "off"]]}
        assert (modes["x"], pump["x"], door["x"]) == ("index", "number", "time")
        assert pump["series"] == {"Pump": [[0.0, "on"], [6.5, "off"]]}
        assert door["series"]["Door"][1] == [noon.timestamp() + 300, "closed"]

    def test_graph_of_numbers_and_states(self, card: HAAnimCard) -> None:
        """Test one graph can have a series of numbers and a series of states."""
        card.graph("g", series={"Temperature": [(0, 20.5), (1, 21)], "Heating": [(0, "off"), (1, "on")]})
        assert card.blocks[0]["series"]["Heating"] == [[0.0, "off"], [1.0, "on"]]
        assert card.blocks[0]["series"]["Temperature"] == [[0.0, 20.5], [1.0, 21.0]]

    def test_graph_values_are_json(self, card: HAAnimCard) -> None:
        """Test what a graph block carries is plain JSON, whatever was passed in."""
        card.graph("g", series={"A": [(datetime(2025, 1, 6, tzinfo=timezone.utc), 1)]})
        assert json.loads(json.dumps(card.blocks)) == card.blocks

    def test_empty_series_is_allowed(self, card: HAAnimCard) -> None:
        """Test a series can start without points."""
        card.graph("g", series={"A": []})
        assert card.blocks[0]["series"] == {"A": []}
        assert card.blocks[0]["x"] == "index"

    def test_graph_limits(self, card: HAAnimCard) -> None:
        """Test eight series of 500 points and thirty days of history are accepted."""
        card.graph(
            "g", series={f"S{index}": list(range(MAX_GRAPH_POINTS)) for index in range(MAX_GRAPH_SERIES)}
        )
        card.graph("h", [f"sensor.s{index}" for index in range(MAX_GRAPH_SERIES)], hours=MAX_GRAPH_HOURS)
        assert len(card.blocks[0]["series"]) == 8
        assert (MAX_GRAPH_SERIES, MAX_GRAPH_POINTS, MAX_GRAPH_HOURS, GRAPH_KINDS) == (
            8,
            500,
            720,
            ("line", "area", "bar"),
        )

    def test_graph_data_is_copied(self, card: HAAnimCard) -> None:
        """Test later changes to the list that was passed do not reach the card."""
        points = [1, 2]
        card.graph("g", series={"A": points})
        points.append(3)
        assert len(card.blocks[0]["series"]["A"]) == 2

    def test_button(self, card: HAAnimCard) -> None:
        """Test a button holds its label, action, confirmation and data."""
        card.button("reset", label="Reset", action="reset_alerts", confirm="Sure?", room="hall", level=2)
        assert card.blocks == [
            {
                "id": "reset",
                "type": "button",
                "label": "Reset",
                "action": "reset_alerts",
                "confirm": "Sure?",
                "data": {"room": "hall", "level": 2},
            }
        ]

    def test_button_defaults(self, card: HAAnimCard) -> None:
        """Test a button asks nothing and passes no data by default."""
        card.button("reset", "Reset", "reset_alerts")
        assert card.blocks[0]["confirm"] is None
        assert card.blocks[0]["data"] == {}

    def test_remove(self, card: HAAnimCard) -> None:
        """Test remove takes a block away and does nothing for an unknown ID."""
        fill(card)
        card.remove("logo")
        assert [block["id"] for block in card.blocks] == ["intro", "alerts", "temp", "reset"]
        card.remove("logo")
        card.remove("never")
        assert len(card.blocks) == 4

    def test_clear(self, card: HAAnimCard) -> None:
        """Test clear removes all blocks."""
        fill(card)
        card.clear()
        assert card.blocks == []

    def test_blocks_is_read_only(self, card: HAAnimCard) -> None:
        """Test changing what blocks returns does not change the card, and it cannot be assigned."""
        card.button("reset", "Reset", "reset_alerts", room="hall")
        blocks = card.blocks
        blocks[0]["label"] = "changed"
        blocks[0]["data"]["room"] = "changed"
        blocks.append({"id": "x"})
        assert card.blocks[0]["label"] == "Reset"
        assert card.blocks[0]["data"] == {"room": "hall"}
        assert len(card.blocks) == 1
        with pytest.raises(AttributeError):
            card.blocks = []  # type: ignore[misc]

    def test_button_data_is_copied(self, card: HAAnimCard) -> None:
        """Test later changes to what was passed as data do not reach the card."""
        rooms = ["hall"]
        card.button("reset", "Reset", "reset_alerts", rooms=rooms)
        rooms.append("kitchen")
        assert card.blocks[0]["data"] == {"rooms": ["hall"]}

    def test_repr(self, card: HAAnimCard) -> None:
        """Test the card describes itself."""
        fill(card)
        assert repr(card) == "<HAAnimCard climate: 5 blocks>"


class TestTitle:
    """Rule: the automation can give its card a title, and change it at any time."""

    def test_no_title_by_default(self, card: HAAnimCard) -> None:
        """Test a card has no title of its own: it shows the automation's name."""
        assert card.title is None

    async def test_set_title(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test the title is kept and sent with the content."""
        card.set_title("Climate: 3 alerts")
        await FakeClock().advance()
        assert card.title == "Climate: 3 alerts"
        assert sink.titles["climate"] == "Climate: 3 alerts"
        assert len(sink.updates) == 1

    async def test_title_changes_with_blocks_are_one_update(
        self, card: HAAnimCard, sink: FakeCardSink
    ) -> None:
        """Test a title and blocks set in a row are sent together."""
        card.set_title("One")
        card.text("a", "text")
        card.set_title("Two")
        await FakeClock().advance()
        assert len(sink.updates) == 1
        assert sink.titles["climate"] == "Two"

    async def test_same_title_sends_nothing(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test setting the title it already has is not a change."""
        card.set_title("One")
        await FakeClock().advance()
        card.set_title("One")
        await FakeClock().advance()
        assert len(sink.updates) == 1

    async def test_none_goes_back_to_the_name(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test None removes the title."""
        card.set_title("One")
        card.set_title(None)
        await FakeClock().advance()
        assert card.title is None
        assert sink.titles.get("climate") is None

    @pytest.mark.parametrize(
        ("title", "error", "message"),
        [
            ("", ValueError, "title must not be empty"),
            ("   ", ValueError, "title must not be empty"),
            ("x" * 101, ValueError, "at most 100 characters, not 101"),
            (5, TypeError, "title must be a string, not int"),
        ],
    )
    def test_invalid_title_leaves_the_title(
        self, card: HAAnimCard, title: Any, error: type[Exception], message: str
    ) -> None:
        """Test an invalid title raises and the card keeps the title it had."""
        card.set_title("Kept")
        with pytest.raises(error, match=message):
            card.set_title(title)
        assert card.title == "Kept"

    def test_title_at_the_limit(self, card: HAAnimCard) -> None:
        """Test a title of exactly 100 characters is accepted."""
        card.set_title("x" * 100)
        assert len(card.title or "") == 100

    def test_clear_keeps_the_title(self, card: HAAnimCard) -> None:
        """Test clearing the blocks does not touch the title."""
        card.set_title("Kept")
        card.text("a", "text")
        card.clear()
        assert card.title == "Kept"

    async def test_close_takes_the_title_away(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test a stopped automation's card has neither content nor title, and the sink is told."""
        card.set_title("Gone soon")
        await FakeClock().advance()
        card.close()
        assert card.title is None
        assert sink.titles["climate"] is None
        assert len(sink.updates) == 2

    def test_set_title_is_synchronous(self) -> None:
        """Test set_title is a plain function."""
        assert not inspect.iscoroutinefunction(HAAnimCard.set_title)


ALL_SHOWN = {"title": True, "state": True, "message": True, "actions": True, "log": True}


class TestConfigure:
    """Rule: the automation can hide and show the fixed parts of its card."""

    def test_everything_is_shown_by_default(self, card: HAAnimCard) -> None:
        """Test a card shows its five fixed parts until told otherwise."""
        assert card.options == ALL_SHOWN
        assert tuple(card.options) == CARD_PARTS

    @pytest.mark.parametrize("part", CARD_PARTS)
    async def test_hide_one_part(self, card: HAAnimCard, sink: FakeCardSink, part: str) -> None:
        """Test hiding a part hides only that part, and the frontend is told."""
        card.configure(**{part: False})
        await FakeClock().advance()
        assert card.options == {**ALL_SHOWN, part: False}
        assert sink.options["climate"] == {**ALL_SHOWN, part: False}
        assert len(sink.updates) == 1

    def test_parts_not_named_keep_their_setting(self, card: HAAnimCard) -> None:
        """Test a later call changes only what it names; None leaves a part as it is."""
        card.configure(title=False, log=False)
        card.configure(state=False, log=None)
        assert card.options == {
            "title": False,
            "state": False,
            "message": True,
            "actions": True,
            "log": False,
        }
        card.configure(title=True)
        assert card.options["title"] is True
        assert card.options["log"] is False

    def test_bare_box(self, card: HAAnimCard) -> None:
        """Test all five parts can be hidden, leaving the content."""
        card.text("a", "content")
        card.configure(title=False, state=False, message=False, actions=False, log=False)
        assert not any(card.options.values())
        assert len(card.blocks) == 1

    async def test_no_change_sends_nothing(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test configuring what is already so, or nothing, is not a change."""
        card.configure(log=False)
        await FakeClock().advance()
        card.configure(log=False)
        card.configure(title=True)
        card.configure()
        await FakeClock().advance()
        assert len(sink.updates) == 1

    async def test_configure_with_other_changes_is_one_update(
        self, card: HAAnimCard, sink: FakeCardSink
    ) -> None:
        """Test options, title and blocks set in a row are sent together."""
        card.configure(actions=False)
        card.set_title("Bare")
        card.text("a", "content")
        await FakeClock().advance()
        assert len(sink.updates) == 1
        assert sink.options["climate"]["actions"] is False
        assert sink.titles["climate"] == "Bare"

    @pytest.mark.parametrize("value", [0, 1, "no", "false", [], object()])
    def test_invalid_value_changes_nothing(self, card: HAAnimCard, value: Any) -> None:
        """Test a value that is not True, False or None raises, and no part changes, also the valid ones."""
        with pytest.raises(TypeError, match="state must be True or False"):
            card.configure(title=False, state=value)
        assert card.options == ALL_SHOWN

    def test_only_keywords(self, card: HAAnimCard) -> None:
        """Test the parts have to be named."""
        with pytest.raises(TypeError):
            card.configure(False)  # type: ignore[misc]
        with pytest.raises(TypeError):
            card.configure(footer=False)  # type: ignore[call-arg]

    def test_options_is_a_copy(self, card: HAAnimCard) -> None:
        """Test changing what options returns does not change the card."""
        card.options["title"] = False
        assert card.options["title"] is True

    def test_clear_keeps_the_options(self, card: HAAnimCard) -> None:
        """Test clearing the blocks does not show hidden parts again."""
        card.configure(log=False)
        card.clear()
        assert card.options["log"] is False

    async def test_close_shows_everything_again(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test a stopped automation's card is back to the default, and the sink is told."""
        card.configure(title=False)
        await FakeClock().advance()
        card.close()
        assert card.options == ALL_SHOWN
        assert sink.options["climate"] == ALL_SHOWN
        assert len(sink.updates) == 2

    def test_configure_is_synchronous(self) -> None:
        """Test configure is a plain function."""
        assert not inspect.iscoroutinefunction(HAAnimCard.configure)


class TestOrder:
    """Rule: an existing ID is replaced in place; a new ID is appended."""

    def test_blocks_are_in_the_order_they_were_added(self, card: HAAnimCard) -> None:
        """Test new IDs are appended."""
        fill(card)
        assert [block["id"] for block in card.blocks] == ["intro", "logo", "alerts", "temp", "reset"]

    def test_replace_in_place(self, card: HAAnimCard) -> None:
        """Test setting an existing ID keeps its position."""
        fill(card)
        card.value("alerts", label="Alerts today", value=7)
        assert [block["id"] for block in card.blocks] == ["intro", "logo", "alerts", "temp", "reset"]
        assert card.blocks[2]["value"] == 7

    def test_replace_with_another_type(self, card: HAAnimCard) -> None:
        """Test a block can be replaced by a block of another type, in the same place."""
        fill(card)
        card.text("logo", "no logo")
        assert card.blocks[1] == {"id": "logo", "type": "text", "markdown": "no logo"}
        assert len(card.blocks) == 5

    def test_removed_and_set_again_goes_last(self, card: HAAnimCard) -> None:
        """Test an ID that was removed is a new ID."""
        fill(card)
        card.remove("intro")
        card.text("intro", "again")
        assert [block["id"] for block in card.blocks][-1] == "intro"


INVALID: list[tuple[str, Any, type[Exception], str]] = [
    (
        "text too long",
        lambda c: c.text("t", "x" * (MAX_TEXT_LENGTH + 1)),
        ValueError,
        "at most 10000 characters",
    ),
    ("text not a string", lambda c: c.text("t", 5), TypeError, "markdown must be a string"),
    ("empty id", lambda c: c.text("", "x"), ValueError, "id must not be empty"),
    ("blank id", lambda c: c.text("  ", "x"), ValueError, "id must not be empty"),
    ("id not a string", lambda c: c.text(1, "x"), TypeError, "id must be a string"),
    ("image without source", lambda c: c.image("i"), ValueError, "exactly one of asset and url"),
    (
        "image with both",
        lambda c: c.image("i", asset="logo.png", url="https://x/y.png"),
        ValueError,
        "exactly one of asset and url",
    ),
    ("image asset missing", lambda c: c.image("i", asset="none.png"), FileNotFoundError, "no asset"),
    ("image asset outside", lambda c: c.image("i", asset="../main.py"), ValueError, "outside assets/"),
    ("image empty url", lambda c: c.image("i", url=""), ValueError, "url must not be empty"),
    ("image url not a string", lambda c: c.image("i", url=5), TypeError, "url must be a string"),
    ("image alt not a string", lambda c: c.image("i", url="https://x", alt=None), TypeError, "alt must be"),
    ("value is a list", lambda c: c.value("v", "L", [1]), TypeError, "string, number or boolean, not list"),
    ("value is None", lambda c: c.value("v", "L", None), TypeError, "not NoneType"),
    ("value is a dict", lambda c: c.value("v", "L", {}), TypeError, "not dict"),
    ("value is nan", lambda c: c.value("v", "L", float("nan")), ValueError, "finite number"),
    ("value label not a string", lambda c: c.value("v", 1, 1), TypeError, "label must be a string"),
    ("value unit not a string", lambda c: c.value("v", "L", 1, unit=1), TypeError, "unit must be a string"),
    ("entity without domain", lambda c: c.entity("e", "temperature"), ValueError, "Invalid entity ID"),
    ("entity with two dots", lambda c: c.entity("e", "sensor.a.b"), ValueError, "Invalid entity ID"),
    ("entity empty name", lambda c: c.entity("e", "sensor."), ValueError, "Invalid entity ID"),
    ("entity not a string", lambda c: c.entity("e", None), TypeError, "entity_id must be a string"),
    (
        "button unknown action",
        lambda c: c.button("b", "Go", "nothing"),
        ValueError,
        "Automation 'climate' has no action 'nothing'",
    ),
    (
        "icon without icon or entity",
        lambda c: c.icon("i"),
        ValueError,
        "needs an icon, or an entity to follow",
    ),
    (
        "icon not following without icon",
        lambda c: c.icon("i", "fan.a", follow_entity=False),
        ValueError,
        "needs an icon, or an entity to follow",
    ),
    (
        "icon name without set",
        lambda c: c.icon("i", icon="fan"),
        ValueError,
        "an icon is named like 'mdi:fan'",
    ),
    ("icon name with markup", lambda c: c.icon("i", icon='mdi:fan"><b'), ValueError, "Invalid icon"),
    ("icon name in capitals", lambda c: c.icon("i", icon="MDI:Fan"), ValueError, "Invalid icon"),
    ("icon not a string", lambda c: c.icon("i", icon=5), TypeError, "icon must be a string"),
    (
        "icon color with css",
        lambda c: c.icon("i", icon="mdi:fan", color="red; x: y"),
        ValueError,
        "Invalid color",
    ),
    (
        "icon color function",
        lambda c: c.icon("i", icon="mdi:fan", color="rgb(1,2,3)"),
        ValueError,
        "Invalid color",
    ),
    ("icon color not a string", lambda c: c.icon("i", icon="mdi:fan", color=3), TypeError, "color must be"),
    ("icon entity invalid", lambda c: c.icon("i", "fan"), ValueError, "Invalid entity ID"),
    ("icon label not a string", lambda c: c.icon("i", icon="mdi:fan", label=1), TypeError, "label must be"),
    (
        "icon spin not a bool",
        lambda c: c.icon("i", icon="mdi:fan", spin="yes"),
        TypeError,
        "spin must be True",
    ),
    (
        "icon follow not a bool",
        lambda c: c.icon("i", "fan.a", follow_entity=1),
        TypeError,
        "follow_entity must be True or False",
    ),
    ("graph without data", lambda c: c.graph("g"), ValueError, "exactly one of entities and series"),
    (
        "graph with both",
        lambda c: c.graph("g", "sensor.a", {"A": [1]}),
        ValueError,
        "exactly one of entities and series",
    ),
    (
        "graph kind",
        lambda c: c.graph("g", "sensor.a", kind="pie"),
        ValueError,
        "a graph is one of line, area, bar",
    ),
    ("graph title not a string", lambda c: c.graph("g", "sensor.a", title=1), TypeError, "title must be"),
    ("graph unit not a string", lambda c: c.graph("g", "sensor.a", unit=1), TypeError, "unit must be"),
    (
        "graph min not a number",
        lambda c: c.graph("g", "sensor.a", min="0"),
        TypeError,
        "min must be a number",
    ),
    (
        "graph max is nan",
        lambda c: c.graph("g", "sensor.a", max=float("nan")),
        ValueError,
        "max must be a finite",
    ),
    (
        "graph min above max",
        lambda c: c.graph("g", "sensor.a", min=5, max=5),
        ValueError,
        "must be less than max",
    ),
    (
        "graph hours zero",
        lambda c: c.graph("g", "sensor.a", hours=0),
        ValueError,
        "hours must be more than 0",
    ),
    ("graph hours too many", lambda c: c.graph("g", "sensor.a", hours=721), ValueError, "at most 720"),
    ("graph hours not a number", lambda c: c.graph("g", "sensor.a", hours="24"), TypeError, "hours must be"),
    (
        "graph hours a bool",
        lambda c: c.graph("g", "sensor.a", hours=True),
        TypeError,
        "hours must be a number",
    ),
    ("graph no entities", lambda c: c.graph("g", []), ValueError, "1 to 8 entities, not 0"),
    (
        "graph too many entities",
        lambda c: c.graph("g", [f"sensor.s{i}" for i in range(9)]),
        ValueError,
        "1 to 8 entities, not 9",
    ),
    (
        "graph entity invalid",
        lambda c: c.graph("g", ["sensor.a", "nodomain"]),
        ValueError,
        "Invalid entity ID",
    ),
    ("graph entity twice", lambda c: c.graph("g", ["sensor.a", "sensor.a"]), ValueError, "each entity once"),
    (
        "graph entities a dict",
        lambda c: c.graph("g", {"sensor.a": 1}),
        TypeError,
        "entities must be an entity ID",
    ),
    ("graph entities a number", lambda c: c.graph("g", 5), TypeError, "entities must be an entity ID"),
    ("graph series a list", lambda c: c.graph("g", series=[1, 2]), TypeError, "series must be a dictionary"),
    ("graph no series", lambda c: c.graph("g", series={}), ValueError, "1 to 8 series, not 0"),
    (
        "graph too many series",
        lambda c: c.graph("g", series={f"S{i}": [1] for i in range(9)}),
        ValueError,
        "1 to 8 series, not 9",
    ),
    (
        "graph series name empty",
        lambda c: c.graph("g", series={"": [1]}),
        ValueError,
        "series name must not be empty",
    ),
    ("graph series name a number", lambda c: c.graph("g", series={1: [1]}), TypeError, "series name must be"),
    (
        "graph points a string",
        lambda c: c.graph("g", series={"A": "123"}),
        TypeError,
        "points must be a list",
    ),
    ("graph points a number", lambda c: c.graph("g", series={"A": 5}), TypeError, "points must be a list"),
    (
        "graph too many points",
        lambda c: c.graph("g", series={"A": list(range(501))}),
        ValueError,
        "has 501 points; a series has at most 500",
    ),
    (
        "graph numbers and states in one series",
        lambda c: c.graph("g", series={"A": [1, "on"]}),
        ValueError,
        "series 'A' mixes numbers and states",
    ),
    (
        "graph state empty",
        lambda c: c.graph("g", series={"A": ["on", " "]}),
        ValueError,
        "series 'A', point 1",
    ),
    (
        "graph state too long",
        lambda c: c.graph("g", series={"A": ["x" * 41]}),
        ValueError,
        "1 to 40 characters",
    ),
    (
        "graph value a list",
        lambda c: c.graph("g", series={"A": [(0, [1])]}),
        TypeError,
        "series 'A', point 0",
    ),
    (
        "graph value infinite",
        lambda c: c.graph("g", series={"A": [float("inf")]}),
        ValueError,
        "finite number",
    ),
    (
        "graph value a bool",
        lambda c: c.graph("g", series={"A": [True]}),
        TypeError,
        "must be a number, not bool",
    ),
    (
        "graph triple",
        lambda c: c.graph("g", series={"A": [(1, 2, 3)]}),
        ValueError,
        "a value or an \\(x, y\\) pair",
    ),
    (
        "graph time not iso",
        lambda c: c.graph("g", series={"A": [("noon", 1)]}),
        ValueError,
        "not a time in ISO",
    ),
    (
        "graph time without zone",
        lambda c: c.graph("g", series={"A": [("2025-01-06 12:00", 1)]}),
        ValueError,
        "has no time zone",
    ),
    (
        "graph naive datetime",
        lambda c: c.graph("g", series={"A": [(datetime(2025, 1, 6), 1)]}),
        ValueError,
        "has no time zone",
    ),
    (
        "graph mixed positions",
        lambda c: c.graph("g", series={"A": [1, 2], "B": [(0, 1)]}),
        ValueError,
        "these are mixed: index, number",
    ),
    (
        "graph numbers and times",
        lambda c: c.graph("g", series={"A": [(0, 1), ("2025-01-06T12:00:00+00:00", 1)]}),
        ValueError,
        "these are mixed: number, time",
    ),
    ("button label not a string", lambda c: c.button("b", 1, "reset"), TypeError, "label must be a string"),
    ("button action not a string", lambda c: c.button("b", "Go", None), TypeError, "action must be a string"),
    (
        "button confirm not a string",
        lambda c: c.button("b", "Go", "reset", confirm=True),
        TypeError,
        "confirm",
    ),
    ("button data not JSON", lambda c: c.button("b", "Go", "reset", when={1, 2}), TypeError, "JSON values"),
    ("remove id not a string", lambda c: c.remove(None), TypeError, "id must be a string"),
]


class TestValidation:
    """Rule: an invalid block raises and leaves the card unchanged."""

    @pytest.mark.parametrize(
        ("call", "error", "message"), [row[1:] for row in INVALID], ids=[r[0] for r in INVALID]
    )
    async def test_invalid_leaves_card_unchanged(
        self, card: HAAnimCard, sink: FakeCardSink, call: Any, error: type[Exception], message: str
    ) -> None:
        """Test each validation error is raised, nothing changes and nothing is sent."""
        fill(card)
        await FakeClock().advance()
        before = card.blocks
        sent = len(sink.updates)

        with pytest.raises(error, match=message):
            call(card)

        assert card.blocks == before
        await FakeClock().advance()
        assert len(sink.updates) == sent

    def test_invalid_replacement_keeps_the_old_block(self, card: HAAnimCard) -> None:
        """Test a failed replace leaves the block that was there."""
        card.value("alerts", "Alerts", 1)
        with pytest.raises(TypeError):
            card.value("alerts", "Alerts", [2])
        assert card.blocks[0]["value"] == 1

    def test_text_at_the_limit(self, card: HAAnimCard) -> None:
        """Test a text block of exactly 10 000 characters is accepted."""
        card.text("t", "x" * MAX_TEXT_LENGTH)
        assert len(card.blocks[0]["markdown"]) == 10_000

    def test_block_limit(self, card: HAAnimCard) -> None:
        """Test the 51st block raises ValueError and the card keeps its 50."""
        for index in range(MAX_BLOCKS):
            card.value(f"v{index}", "L", index)
        with pytest.raises(ValueError, match="at most 50 blocks"):
            card.text("one_more", "x")
        assert len(card.blocks) == 50
        assert "one_more" not in [block["id"] for block in card.blocks]

    def test_replace_at_the_block_limit(self, card: HAAnimCard) -> None:
        """Test a full card still accepts replacing a block, and a new one after a removal."""
        for index in range(MAX_BLOCKS):
            card.value(f"v{index}", "L", index)
        card.value("v7", "L", "replaced")
        assert card.blocks[7]["value"] == "replaced"
        card.remove("v0")
        card.text("one_more", "x")
        assert len(card.blocks) == 50

    def test_limits_are_the_designs(self) -> None:
        """Test the limits are 50 blocks and 10 000 characters."""
        assert (MAX_BLOCKS, MAX_TEXT_LENGTH) == (50, 10_000)


class TestSynchronous:
    """Rule: all card methods return immediately and are not awaited."""

    @pytest.mark.parametrize(
        "name", ["text", "image", "value", "entity", "icon", "button", "remove", "clear"]
    )
    def test_methods_are_plain_functions(self, name: str) -> None:
        """Test no card method is a coroutine function."""
        assert not inspect.iscoroutinefunction(getattr(HAAnimCard, name))


class TestUpdates:
    """Rule: changes without an await or checkpoint between them are sent as one update."""

    async def test_changes_are_sent_as_one_update(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test five changes in a row give one update with all five blocks."""
        fill(card)
        assert sink.updates == []
        await FakeClock().advance()
        assert len(sink.updates) == 1
        assert sink.updates[0] == ("climate", card.blocks)
        assert len(sink.cards["climate"]) == 5

    async def test_an_await_separates_updates(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test changes on both sides of an await are two updates."""
        card.text("a", "one")
        await FakeClock().advance()
        card.text("b", "two")
        card.text("c", "three")
        await FakeClock().advance()
        assert [len(blocks) for _, blocks in sink.updates] == [1, 3]

    async def test_no_update_without_a_change(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test setting the same block again, removing nothing and clearing nothing send nothing."""
        card.text("a", "one")
        await FakeClock().advance()
        card.text("a", "one")
        card.remove("missing")
        await FakeClock().advance()
        assert len(sink.updates) == 1

        card.clear()
        await FakeClock().advance()
        card.clear()
        await FakeClock().advance()
        assert [blocks for _, blocks in sink.updates] == [
            [{"id": "a", "type": "text", "markdown": "one"}],
            [],
        ]

    async def test_remove_and_replace_are_sent(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test a replaced and a removed block each lead to an update."""
        fill(card)
        await FakeClock().advance()
        card.value("alerts", "Alerts today", 1)
        await FakeClock().advance()
        card.remove("logo")
        await FakeClock().advance()
        assert [len(blocks) for _, blocks in sink.updates] == [5, 5, 4]
        assert sink.updates[1][1][2]["value"] == 1

    async def test_the_update_is_a_copy(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test what the sink got does not change when the card does."""
        card.text("a", "one")
        await FakeClock().advance()
        card.text("a", "two")
        assert sink.updates[0][1][0]["markdown"] == "one"

    def test_without_an_event_loop_the_update_is_immediate(
        self, card: HAAnimCard, sink: FakeCardSink
    ) -> None:
        """Test a change made outside the event loop is sent at once."""
        card.text("a", "one")
        assert len(sink.updates) == 1

    async def test_no_sink(self) -> None:
        """Test a card nobody shows works the same."""
        card = HAAnimCard("climate", AssetStore("climate", None, FakeFileSystem()), lambda name: True)
        card.text("a", "one")
        card.close()
        assert card.blocks == []

    async def test_close_sends_the_empty_card_at_once(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test closing empties the card and tells the sink without waiting, once."""
        fill(card)
        card.close()
        assert sink.updates == [("climate", [])]
        await FakeClock().advance()
        assert len(sink.updates) == 1

    async def test_close_of_an_empty_card_sends_nothing(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test closing a card that never had content is silent."""
        card.close()
        assert sink.updates == []


SOURCE = """
from haanim import haa, action, startup, shutdown

@action(aliases=["reset"])
def reset_alerts(event):
    haa.card.value("alerts", label="Alerts today", value=0)
    return event.data

@startup
def build_card(event):
    haa.card.text("intro", "## Climate")
    haa.card.value("alerts", label="Alerts today", value=0)
    haa.card.entity("temp", "sensor.temperature")
    haa.card.button("reset", label="Reset counter", action="reset_alerts", confirm="Reset the counter?")

@action
def alert(event):
    haa.card.value("alerts", label="Alerts today", value=1)
    haa.card.value("alerts", label="Alerts today", value=2)
    haa.card.value("alerts", label="Alerts today", value=3)
    return [block["id"] for block in haa.card.blocks]

@action
def bad_button(event):
    haa.card.button("nope", label="Nope", action="missing")

@action
def alias_button(event):
    haa.card.button("alias", label="Alias", action="reset")

@action
async def two_steps(event):
    haa.card.text("step", "one")
    await haa.sleep(1)
    haa.card.text("step", "two")
"""


class TestInAnAutomation:
    """The design's example and the lifetime rules, run by the interpreter."""

    async def test_card_built_in_startup(self, world: World) -> None:
        """Test @startup fills the card and the host gets it as one update."""
        await world.started("climate", SOURCE)
        await world.clock.advance()
        assert [block["id"] for block in world.host.cards.cards["climate"]] == [
            "intro",
            "alerts",
            "temp",
            "reset",
        ]
        assert len(world.host.cards.updates) == 1

    async def test_replace_from_an_action(self, world: World) -> None:
        """Test an action replaces a block in place; changes in a row are one update."""
        automation = await world.started("climate", SOURCE)
        await world.clock.advance()
        assert await automation.call_action("alert") == ["intro", "alerts", "temp", "reset"]
        await world.clock.advance()
        assert world.host.cards.cards["climate"][1]["value"] == 3
        assert len(world.host.cards.updates) == 2

    async def test_await_in_an_action_separates_updates(self, world: World) -> None:
        """Test changes before and after a sleep are separate updates."""
        automation = await world.started("climate", SOURCE)
        await world.clock.advance()
        call = world.clock
        task = asyncio.ensure_future(automation.call_action("two_steps"))
        await call.advance()
        assert world.host.cards.cards["climate"][-1]["markdown"] == "one"
        await call.advance(seconds=1)
        await task
        await call.advance()
        assert world.host.cards.cards["climate"][-1]["markdown"] == "two"

    async def test_button_action_must_exist(self, world: World) -> None:
        """Test a button naming a missing action is a ValueError and adds nothing."""
        automation = await world.started("climate", SOURCE)
        with pytest.raises(ValueError, match="Automation 'climate' has no action 'missing'"):
            await automation.call_action("bad_button")
        assert "nope" not in [block["id"] for block in automation.context._haa.card.blocks]

    async def test_button_can_name_an_alias(self, world: World) -> None:
        """Test a button can name an action by one of its aliases."""
        automation = await world.started("climate", SOURCE)
        await automation.call_action("alias_button")
        assert automation.context._haa.card.blocks[-1]["action"] == "reset"

    async def test_cleared_on_stop(self, world: World) -> None:
        """Test stopping empties the card and tells the host."""
        automation = await world.started("climate", SOURCE)
        await world.clock.advance()
        await automation.stop()
        assert world.host.cards.cards["climate"] == []

    async def test_not_kept_across_restart(self, world: World) -> None:
        """Test a restarted automation has only what its @startup builds."""
        automation = await world.started("climate", SOURCE)
        await automation.call_action("alias_button")
        await automation.stop()
        assert await automation.start()
        await world.clock.advance()
        assert [block["id"] for block in world.host.cards.cards["climate"]] == [
            "intro",
            "alerts",
            "temp",
            "reset",
        ]

    async def test_cards_are_per_automation(self, world: World) -> None:
        """Test each automation has its own card."""
        await world.started("climate", SOURCE)
        await world.started("other", "from haanim import haa\nhaa.card.text('only', 'mine')\n")
        await world.clock.advance()
        assert [block["id"] for block in world.host.cards.cards["other"]] == ["only"]
        assert len(world.host.cards.cards["climate"]) == 4
