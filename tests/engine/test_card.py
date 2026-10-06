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
from haanim.engine.card import CARD_PARTS, HAAnimCard
from haanim.engine.card_elements import (
    GRAPH_KINDS,
    MAX_BLOCKS,
    MAX_GRAPH_HOURS,
    MAX_GRAPH_POINTS,
    MAX_GRAPH_SERIES,
    MAX_ROW_CELLS,
    MAX_TEXT_LENGTH,
    ButtonElement,
    CardElement,
    CardLayout,
    CardRow,
    GraphElement,
    IconElement,
    ImageElement,
    TextElement,
    ValueElement,
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


class Put:
    """Creates an element of a kind and adds it to the card in one step: ``put(card).text("id", "...")``."""

    def __init__(self, card: HAAnimCard) -> None:
        self._card = card

    def __getattr__(self, kind: str) -> Any:
        def create_and_add(*args: Any, **kwargs: Any) -> Any:
            element = getattr(self._card, f"create_{kind}")(*args, **kwargs)
            self._card.add_element(element)
            return element

        return create_and_add


def put(card: HAAnimCard) -> Put:
    """Return a helper that creates elements and adds them to a card."""
    return Put(card)


def fill(card: HAAnimCard) -> None:
    """Build the card of the design's example."""
    put(card).text("intro", "## Climate\nKeeps the house between **19** and **23** °C.")
    put(card).image("logo", asset="logo.png", alt="Climate logo")
    put(card).value("alerts", label="Alerts today", value=0)
    put(card).entity("temp", "sensor.temperature")
    put(card).button("reset", label="Reset counter", action="reset_alerts", confirm="Reset the counter?")


class TestBlocks:
    """The table of methods: each one shows a block of its type."""

    def test_text(self, card: HAAnimCard) -> None:
        """Test a text block holds its markdown."""
        put(card).text("intro", "## Climate")
        assert card.blocks == [{"id": "intro", "type": "text", "markdown": "## Climate"}]

    def test_image_from_asset(self, card: HAAnimCard) -> None:
        """Test an image from assets/ gets the asset's URL."""
        put(card).image("logo", asset="logo.png", alt="Climate logo")
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
        put(card).image("pic", url="https://example.com/a.png")
        assert card.blocks == [{"id": "pic", "type": "image", "url": "https://example.com/a.png", "alt": ""}]

    @pytest.mark.parametrize("value", ["on", "", 0, 42, -1.5, True, False])
    def test_value(self, card: HAAnimCard, value: Any) -> None:
        """Test a value block holds a string, number or boolean, as it is."""
        put(card).value("alerts", label="Alerts today", value=value, unit="x")
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
        put(card).value("alerts", "Alerts", 3)
        assert card.blocks[0]["unit"] == ""

    def test_entity(self, card: HAAnimCard) -> None:
        """Test an entity block holds the entity ID."""
        put(card).entity("temp", "sensor.temperature")
        assert card.blocks == [{"id": "temp", "type": "entity", "entity_id": "sensor.temperature"}]

    def test_icon_following_an_entity(self, card: HAAnimCard) -> None:
        """Test an icon with an entity follows it by default."""
        put(card).icon("fan", "fan.bedroom")
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
        put(card).icon("fan", "fan.bedroom", icon="mdi:fan", label="Fan", color="success", spin=True)
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
        put(card).icon("fan", "fan.bedroom", icon="mdi:fan", follow_entity=False)
        assert card.blocks[0]["follow_entity"] is False
        assert card.blocks[0]["entity_id"] == "fan.bedroom"

    def test_icon_without_an_entity(self, card: HAAnimCard) -> None:
        """Test an icon without an entity has nothing to follow."""
        put(card).icon("home", icon="mdi:home-outline", color="#03a9f4")
        assert card.blocks[0]["entity_id"] is None
        assert card.blocks[0]["follow_entity"] is False

    @pytest.mark.parametrize("icon", ["mdi:fan", "mdi:fan-off", "hass:water-percent", "mdi:numeric-1-box"])
    def test_icon_names(self, card: HAAnimCard, icon: str) -> None:
        """Test icons are named set:name."""
        put(card).icon("i", icon=icon)
        assert card.blocks[0]["icon"] == icon

    @pytest.mark.parametrize("color", ["primary", "red", "dark-orange", "#fff", "#03a9f4", "#03a9f480"])
    def test_icon_colors(self, card: HAAnimCard, color: str) -> None:
        """Test a colour is a name or a hex value."""
        put(card).icon("i", icon="mdi:fan", color=color)
        assert card.blocks[0]["color"] == color

    def test_graph_of_entities(self, card: HAAnimCard) -> None:
        """Test a history graph keeps its entities and time span; one entity can be given as text."""
        put(card).graph("temp", "sensor.temperature")
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
                "x_major": None,
                "x_minor": None,
            }
        ]
        put(card).graph(
            "both", ("sensor.indoor", "sensor.outdoor"), hours=6, kind="area", title="Temperatures", unit="°C"
        )
        block = card.blocks[1]
        assert block["entities"] == ["sensor.indoor", "sensor.outdoor"]
        assert (block["hours"], block["kind"], block["title"], block["unit"]) == (
            6.0,
            "area",
            "Temperatures",
            "°C",
        )

    def test_graph_of_plain_numbers(self, card: HAAnimCard) -> None:
        """Test numbers are drawn one after the other; None is a gap."""
        put(card).graph(
            "g", series={"Alerts": [1, 2.5, None, 4], "Resets": (0, 1)}, kind="bar", min=0, max=10
        )
        block = card.blocks[0]
        assert block["series"] == {
            "Alerts": [[0.0, 1.0], [1.0, 2.5], [2.0, None], [3.0, 4.0]],
            "Resets": [[0.0, 0.0], [1.0, 1.0]],
        }
        assert (block["x"], block["kind"], block["min"], block["max"]) == ("index", "bar", 0.0, 10.0)
        assert "entities" not in block

    def test_graph_of_number_pairs(self, card: HAAnimCard) -> None:
        """Test (x, y) pairs keep their positions."""
        put(card).graph("g", series={"Curve": [(0, 0), (2.5, 6), [10, None]]})
        assert card.blocks[0]["series"] == {"Curve": [[0.0, 0.0], [2.5, 6.0], [10.0, None]]}
        assert card.blocks[0]["x"] == "number"

    def test_graph_over_time(self, card: HAAnimCard) -> None:
        """Test times are ISO text or aware datetimes, and become seconds since 1970."""
        noon = datetime(2025, 1, 6, 12, 0, tzinfo=timezone.utc)
        put(card).graph(
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
        put(card).graph("modes", series={"Mode": ["heat", "heat", None, "off"]})
        put(card).graph("pump", series={"Pump": [(0, "on"), (6.5, "off")]})
        put(card).graph("door", series={"Door": [(noon, "open"), ("2025-01-06T12:05:00+00:00", "closed")]})
        modes, pump, door = card.blocks
        assert modes["series"] == {"Mode": [[0.0, "heat"], [1.0, "heat"], [2.0, None], [3.0, "off"]]}
        assert (modes["x"], pump["x"], door["x"]) == ("index", "number", "time")
        assert pump["series"] == {"Pump": [[0.0, "on"], [6.5, "off"]]}
        assert door["series"]["Door"][1] == [noon.timestamp() + 300, "closed"]

    def test_graph_of_numbers_and_states(self, card: HAAnimCard) -> None:
        """Test one graph can have a series of numbers and a series of states."""
        put(card).graph("g", series={"Temperature": [(0, 20.5), (1, 21)], "Heating": [(0, "off"), (1, "on")]})
        assert card.blocks[0]["series"]["Heating"] == [[0.0, "off"], [1.0, "on"]]
        assert card.blocks[0]["series"]["Temperature"] == [[0.0, 20.5], [1.0, 21.0]]

    def test_graph_marks_on_a_time_axis(self, card: HAAnimCard) -> None:
        """Test on a time axis the distances between marks are durations, kept in seconds."""
        put(card).graph("h", "sensor.temperature", x_major="01:00:00", x_minor=900)
        put(card).graph("t", series={"A": [("2025-01-06T12:00:00+00:00", 1)]}, x_major=3600)
        history, own = card.blocks
        assert (history["x_major"], history["x_minor"]) == (3600.0, 900.0)
        assert (own["x_major"], own["x_minor"]) == (3600.0, None)

    def test_graph_marks_on_a_number_axis(self, card: HAAnimCard) -> None:
        """Test on other axes the distances are numbers; either can be given alone."""
        put(card).graph("g", series={"A": [1, 2, 3]}, x_major=10, x_minor=2.5)
        put(card).graph("m", series={"A": [(0, 1)]}, x_minor=0.5)
        assert (card.blocks[0]["x_major"], card.blocks[0]["x_minor"]) == (10.0, 2.5)
        assert (card.blocks[1]["x_major"], card.blocks[1]["x_minor"]) == (None, 0.5)

    def test_graph_values_are_json(self, card: HAAnimCard) -> None:
        """Test what a graph block carries is plain JSON, whatever was passed in."""
        put(card).graph("g", series={"A": [(datetime(2025, 1, 6, tzinfo=timezone.utc), 1)]})
        assert json.loads(json.dumps(card.blocks)) == card.blocks

    def test_empty_series_is_allowed(self, card: HAAnimCard) -> None:
        """Test a series can start without points."""
        put(card).graph("g", series={"A": []})
        assert card.blocks[0]["series"] == {"A": []}
        assert card.blocks[0]["x"] == "index"

    def test_graph_limits(self, card: HAAnimCard) -> None:
        """Test eight series of 500 points and thirty days of history are accepted."""
        put(card).graph(
            "g", series={f"S{index}": list(range(MAX_GRAPH_POINTS)) for index in range(MAX_GRAPH_SERIES)}
        )
        put(card).graph("h", [f"sensor.s{index}" for index in range(MAX_GRAPH_SERIES)], hours=MAX_GRAPH_HOURS)
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
        put(card).graph("g", series={"A": points})
        points.append(3)
        assert len(card.blocks[0]["series"]["A"]) == 2

    def test_button(self, card: HAAnimCard) -> None:
        """Test a button holds its label, action, confirmation and data."""
        put(card).button("reset", label="Reset", action="reset_alerts", confirm="Sure?", room="hall", level=2)
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
        put(card).button("reset", "Reset", "reset_alerts")
        assert card.blocks[0]["confirm"] is None
        assert card.blocks[0]["data"] == {}

    def test_remove(self, card: HAAnimCard) -> None:
        """Test remove_element takes an element away, by itself or by its ID, and does nothing if it is not there."""
        fill(card)
        logo = card.element("logo")
        card.remove_element("logo")
        assert [block["id"] for block in card.blocks] == ["intro", "alerts", "temp", "reset"]
        card.remove_element("logo")
        card.remove_element("never")
        assert logo is not None
        card.remove_element(logo)
        card.remove_element(card.elements[0])
        assert [block["id"] for block in card.blocks] == ["alerts", "temp", "reset"]

    def test_clear(self, card: HAAnimCard) -> None:
        """Test clear removes all elements."""
        fill(card)
        card.clear()
        assert card.blocks == []
        assert card.elements == []

    def test_blocks_is_read_only(self, card: HAAnimCard) -> None:
        """Test changing what blocks returns does not change the card, and it cannot be assigned."""
        put(card).button("reset", "Reset", "reset_alerts", room="hall")
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
        put(card).button("reset", "Reset", "reset_alerts", rooms=rooms)
        rooms.append("kitchen")
        assert card.blocks[0]["data"] == {"rooms": ["hall"]}

    def test_repr(self, card: HAAnimCard) -> None:
        """Test the card describes itself."""
        fill(card)
        assert repr(card) == "<HAAnimCard climate: 5 elements>"


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
        put(card).text("a", "text")
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
        put(card).text("a", "text")
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
        put(card).text("a", "content")
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
        put(card).text("a", "content")
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


class TestElements:
    """Rule: creating an element and adding it are two steps, and an element is changed through its setters."""

    def test_created_is_not_yet_shown(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test an element exists once created and is on the card only once added."""
        title = card.create_text("title", "## Demo")
        assert isinstance(title, TextElement)
        assert isinstance(title, CardElement)
        assert (title.id, title.type, title.text) == ("title", "text", "## Demo")
        assert card.blocks == []
        assert sink.updates == []
        card.add_element(title)
        assert card.blocks == [{"id": "title", "type": "text", "markdown": "## Demo"}]
        assert card.element("title") is title
        assert card.elements == [title]

    def test_each_kind_has_its_class(self, card: HAAnimCard) -> None:
        """Test every create method returns an element of its own class and type."""
        created = [
            card.create_text("a", "x"),
            card.create_image("b", url="https://example.com/a.png"),
            card.create_value("c", "L", 1),
            card.create_entity("d", "sensor.a"),
            card.create_icon("e", icon="mdi:fan"),
            card.create_graph("f", series={"A": [1]}),
            card.create_button("g", "Go", "reset"),
        ]
        assert [element.type for element in created] == [
            "text",
            "image",
            "value",
            "entity",
            "icon",
            "graph",
            "button",
        ]
        assert [type(element).__name__ for element in created] == [
            "TextElement",
            "ImageElement",
            "ValueElement",
            "EntityElement",
            "IconElement",
            "GraphElement",
            "ButtonElement",
        ]
        assert repr(created[0]) == "<TextElement 'a'>"

    def test_set_text(self, card: HAAnimCard) -> None:
        """Test a text is changed in place."""
        title = put(card).text("title", "## Demo")
        put(card).value("v", "L", 1)
        title.set_text("## Updated title")
        assert title.text == "## Updated title"
        assert card.blocks[0] == {"id": "title", "type": "text", "markdown": "## Updated title"}
        assert [block["id"] for block in card.blocks] == ["title", "v"]

    def test_set_value_label_unit(self, card: HAAnimCard) -> None:
        """Test each property of a value is changed on its own; the others stay."""
        count: ValueElement = put(card).value("count", label="Presses", value=0, unit="x")
        count.set_value(3)
        assert (count.label, count.value, count.unit) == ("Presses", 3, "x")
        count.set_label("Button presses")
        count.set_unit("")
        assert card.blocks == [
            {"id": "count", "type": "value", "label": "Button presses", "value": 3, "unit": ""}
        ]

    def test_image_setters(self, card: HAAnimCard) -> None:
        """Test an image can change its source between an asset and a URL, and its alt text."""
        image: ImageElement = put(card).image("i", url="https://example.com/a.png")
        assert (image.asset, image.url, image.alt) == (None, "https://example.com/a.png", "")
        image.set_asset("logo.png")
        assert (image.asset, image.url) == ("logo.png", "/api/haanim/assets/climate/logo.png")
        image.set_alt("Logo")
        image.set_url("https://example.com/b.png")
        assert card.blocks == [
            {"id": "i", "type": "image", "url": "https://example.com/b.png", "alt": "Logo"}
        ]

    def test_entity_setter(self, card: HAAnimCard) -> None:
        """Test an entity element can show another entity."""
        element = put(card).entity("e", "sensor.a")
        element.set_entity("sensor.b")
        assert element.entity_id == "sensor.b"
        assert card.blocks[0]["entity_id"] == "sensor.b"

    def test_icon_setters(self, card: HAAnimCard) -> None:
        """Test every property of an icon has a setter."""
        icon: IconElement = put(card).icon("fan", "fan.bedroom")
        icon.set_icon("mdi:fan")
        icon.set_label("Fan")
        icon.set_color("success")
        icon.set_spin(True)
        assert (icon.entity_id, icon.icon, icon.label, icon.color, icon.spin, icon.follow_entity) == (
            "fan.bedroom",
            "mdi:fan",
            "Fan",
            "success",
            True,
            True,
        )
        icon.set_follow_entity(False)
        assert card.blocks[0]["follow_entity"] is False
        icon.set_entity(None)
        icon.set_label(None)
        icon.set_color(None)
        assert (icon.entity_id, icon.label, icon.color) == (None, None, None)

    def test_graph_setters(self, card: HAAnimCard) -> None:
        """Test a graph's data and look are changed in place."""
        graph: GraphElement = put(card).graph("g", series={"A": [1, 2]})
        graph.set_series({"A": [1, 2, 3], "B": [0, 1]})
        assert graph.series == {"A": [[0.0, 1.0], [1.0, 2.0], [2.0, 3.0]], "B": [[0.0, 0.0], [1.0, 1.0]]}
        assert graph.entities is None
        graph.set_kind("bar")
        graph.set_title("Counts")
        graph.set_unit("x")
        graph.set_range(min=0, max=10)
        graph.set_marks(x_major=2, x_minor=1)
        block = card.blocks[0]
        assert (graph.kind, graph.title) == ("bar", "Counts")
        assert (block["unit"], block["min"], block["max"], block["x_major"], block["x_minor"]) == (
            "x",
            0.0,
            10.0,
            2.0,
            1.0,
        )

        graph.set_marks()
        graph.set_range()
        graph.set_entities(["sensor.a", "sensor.b"], hours=6)
        assert graph.entities == ["sensor.a", "sensor.b"]
        assert graph.series is None
        assert card.blocks[0]["hours"] == 6.0
        graph.set_hours(12)
        graph.set_entities("sensor.c")
        assert (card.blocks[0]["entities"], card.blocks[0]["hours"]) == (["sensor.c"], 12.0)
        graph.set_series({"A": [1]})
        assert "entities" not in card.blocks[0]

    def test_graph_series_is_a_copy(self, card: HAAnimCard) -> None:
        """Test changing what series returns does not change the graph."""
        graph = put(card).graph("g", series={"A": [1]})
        graph.series["A"].append([9, 9])
        assert graph.series == {"A": [[0.0, 1.0]]}

    def test_button_setters(self, card: HAAnimCard) -> None:
        """Test a button's label, action, confirmation and data are changed in place."""
        button: ButtonElement = put(card).button("b", "Reset", "reset_alerts", room="hall")
        button.set_label("Reset all")
        button.set_action("reset")
        button.set_confirm("Sure?")
        button.set_data(room="kitchen", level=2)
        assert (button.label, button.action, button.confirm, button.data) == (
            "Reset all",
            "reset",
            "Sure?",
            {"room": "kitchen", "level": 2},
        )
        button.set_confirm(None)
        button.set_data()
        assert card.blocks[0]["confirm"] is None
        assert card.blocks[0]["data"] == {}
        button.data["x"] = 1
        assert button.data == {}

    @pytest.mark.parametrize(
        ("change", "error", "message"),
        [
            (lambda e: e["text"].set_text("x" * 10_001), ValueError, "at most 10000 characters"),
            (lambda e: e["text"].set_text(5), TypeError, "markdown must be a string"),
            (lambda e: e["value"].set_value([1]), TypeError, "string, number or boolean"),
            (lambda e: e["value"].set_label(None), TypeError, "label must be a string"),
            (lambda e: e["image"].set_asset("none.png"), FileNotFoundError, "no asset"),
            (lambda e: e["image"].set_asset("../main.py"), ValueError, "outside assets/"),
            (lambda e: e["image"].set_url(""), ValueError, "url must not be empty"),
            (lambda e: e["entity"].set_entity("nodomain"), ValueError, "Invalid entity ID"),
            (lambda e: e["icon"].set_icon("fan"), ValueError, "an icon is named like"),
            (lambda e: e["icon"].set_color("red; x"), ValueError, "Invalid color"),
            (lambda e: e["icon"].set_spin("yes"), TypeError, "spin must be True or False"),
            (lambda e: e["plain_icon"].set_icon(None), ValueError, "needs an icon, or an entity to follow"),
            (lambda e: e["graph"].set_kind("pie"), ValueError, "a graph is one of"),
            (lambda e: e["graph"].set_series({"A": [1, "on"]}), ValueError, "mixes numbers and states"),
            (lambda e: e["graph"].set_series(None), ValueError, "exactly one of entities and series"),
            (lambda e: e["graph"].set_entities(None), ValueError, "exactly one of entities and series"),
            (lambda e: e["graph"].set_entities("nodomain"), ValueError, "Invalid entity ID"),
            (lambda e: e["graph"].set_range(min=5, max=1), ValueError, "must be less than max"),
            (lambda e: e["graph"].set_marks(x_major=-1), ValueError, "x_major must be more than 0"),
            (lambda e: e["button"].set_action("missing"), ValueError, "has no action 'missing'"),
            (lambda e: e["button"].set_data(when={1, 2}), TypeError, "JSON values"),
            (lambda e: e["button"].set_confirm(True), TypeError, "confirm must be a string"),
        ],
    )
    async def test_invalid_change_leaves_the_element(
        self, card: HAAnimCard, sink: FakeCardSink, change: Any, error: type[Exception], message: str
    ) -> None:
        """Test a setter that is given something invalid raises, changes nothing and sends nothing."""
        elements = {
            "text": put(card).text("text", "x"),
            "value": put(card).value("value", "L", 1),
            "image": put(card).image("image", asset="logo.png"),
            "entity": put(card).entity("entity", "sensor.a"),
            "icon": put(card).icon("icon", "fan.a"),
            "plain_icon": put(card).icon("plain_icon", icon="mdi:home"),
            "graph": put(card).graph("graph", series={"A": [1]}),
            "button": put(card).button("button", "Go", "reset"),
        }
        await FakeClock().advance()
        before = card.blocks
        sent = len(sink.updates)

        with pytest.raises(error, match=message):
            change(elements)

        assert card.blocks == before
        await FakeClock().advance()
        assert len(sink.updates) == sent

    def test_content_is_a_copy(self, card: HAAnimCard) -> None:
        """Test changing what content and as_dict return does not change the element."""
        button = put(card).button("b", "Go", "reset", room="hall")
        button.content["label"] = "changed"
        button.as_dict()["data"]["room"] = "changed"
        assert button.content == {"label": "Go", "action": "reset", "confirm": None, "data": {"room": "hall"}}

    def test_element_off_the_card_can_be_changed(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test an element that is not on the card keeps its changes for when it is added."""
        count = card.create_value("count", "Presses", 0)
        count.set_value(5)
        card.add_element(count)
        assert card.blocks[0]["value"] == 5

    def test_invalid_id(self, card: HAAnimCard) -> None:
        """Test an element needs an ID that is text."""
        with pytest.raises(ValueError, match="id must not be empty"):
            card.create_text("", "x")
        with pytest.raises(TypeError, match="id must be a string"):
            card.create_text(1, "x")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="id must be a string"):
            card.element(1)  # type: ignore[arg-type]


class TestLayout:
    """Rule: the layout is rows from the top; a row can be split into cells of equal width."""

    def test_layout_is_a_property(self, card: HAAnimCard) -> None:
        """Test the card has one layout, which starts empty."""
        assert isinstance(card.layout, CardLayout)
        assert card.layout is card.layout
        assert card.layout.rows == []
        assert card.layout.as_list() == []
        assert repr(card.layout) == "<CardLayout 0 rows, 0 elements>"

    def test_add_element_gives_a_row_of_its_own(self, card: HAAnimCard) -> None:
        """Test card.add_element is the layout's, and each element gets a full row."""
        a, b = card.create_text("a", "A"), card.create_text("b", "B")
        assert card.add_element(a) is card.layout
        card.layout.add_element(b)
        assert card.layout.as_list() == [{"cells": 1, "elements": ["a"]}, {"cells": 1, "elements": ["b"]}]
        assert [row.cells for row in card.layout.rows] == [1, 1]
        assert card.layout.elements == [a, b]

    def test_split_row(self, card: HAAnimCard) -> None:
        """Test a split row takes elements from the left, chained, and the next element goes below it."""
        buttons = [card.create_button(f"b{index}", f"B{index}", "reset") for index in range(3)]
        row = card.layout.split_row(3)
        assert isinstance(row, CardRow)
        assert row.add_element(buttons[0]).add_element(buttons[1]).add_element(buttons[2]) is row
        image = card.create_image("logo", asset="logo.png")
        card.layout.add_element(image)

        assert card.layout.as_list() == [
            {"cells": 3, "elements": ["b0", "b1", "b2"]},
            {"cells": 1, "elements": ["logo"]},
        ]
        assert (row.cells, row.is_full, row.elements) == (3, True, buttons)
        assert [block["id"] for block in card.blocks] == ["b0", "b1", "b2", "logo"]
        assert repr(row) == "<CardRow 3/3>"

    async def test_extra_elements_are_ignored(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test a full row ignores further elements: no error, and they are not on the card."""
        row = card.layout.split_row(2)
        a, b, c = (card.create_text(name, name) for name in "abc")
        row.add_element(a).add_element(b)
        await FakeClock().advance()
        assert row.add_element(c) is row
        assert row.elements == [a, b]
        assert card.element("c") is None
        await FakeClock().advance()
        assert len(sink.updates) == 1

    def test_fewer_elements_leave_cells_empty(self, card: HAAnimCard) -> None:
        """Test a row keeps its number of cells with fewer elements."""
        row = card.layout.split_row(3)
        row.add_element(card.create_text("a", "A"))
        assert card.layout.as_list() == [{"cells": 3, "elements": ["a"]}]
        assert row.is_full is False

    def test_empty_split_row_is_not_drawn_but_stays(self, card: HAAnimCard) -> None:
        """Test a row without elements is not sent to the card, and can still be filled."""
        row = card.layout.split_row(2)
        put(card).text("below", "x")
        assert card.layout.as_list() == [{"cells": 1, "elements": ["below"]}]
        row.add_element(card.create_text("late", "y"))
        assert card.layout.as_list() == [
            {"cells": 2, "elements": ["late"]},
            {"cells": 1, "elements": ["below"]},
        ]

    @pytest.mark.parametrize("cells", [1, 2, MAX_ROW_CELLS])
    def test_cells(self, card: HAAnimCard, cells: int) -> None:
        """Test a row has one to six cells."""
        assert card.layout.split_row(cells).cells == cells
        assert MAX_ROW_CELLS == 6

    @pytest.mark.parametrize(
        ("cells", "error"),
        [
            (0, ValueError),
            (7, ValueError),
            (-1, ValueError),
            (2.0, TypeError),
            ("3", TypeError),
            (True, TypeError),
        ],
    )
    def test_invalid_cells(self, card: HAAnimCard, cells: Any, error: type[Exception]) -> None:
        """Test another number of cells raises and adds no row."""
        with pytest.raises(error):
            card.layout.split_row(cells)
        assert card.layout.rows == []

    def test_adding_twice_moves(self, card: HAAnimCard) -> None:
        """Test an element that is added again moves to the new place."""
        a, b, c = (put(card).text(name, name) for name in "abc")
        card.add_element(a)
        assert [block["id"] for block in card.blocks] == ["b", "c", "a"]
        row = card.layout.split_row(2)
        row.add_element(b).add_element(a)
        assert card.layout.as_list() == [
            {"cells": 1, "elements": ["c"]},
            {"cells": 2, "elements": ["b", "a"]},
        ]
        assert len(card.blocks) == 3
        row.add_element(b)
        assert row.elements == [a, b], "within a row too"

    async def test_adding_where_it_already_is_changes_nothing(
        self, card: HAAnimCard, sink: FakeCardSink
    ) -> None:
        """Test adding the last element of a row to that row again is not a change."""
        row = card.layout.split_row(2)
        a = card.create_text("a", "A")
        row.add_element(a)
        await FakeClock().advance()
        row.add_element(a)
        await FakeClock().advance()
        assert len(sink.updates) == 1

    def test_full_row_does_not_take_an_element_from_elsewhere(self, card: HAAnimCard) -> None:
        """Test an element stays where it is when the row it is added to is full."""
        row = card.layout.split_row(1)
        row.add_element(card.create_text("a", "A"))
        b = put(card).text("b", "B")
        row.add_element(b)
        assert card.layout.as_list() == [{"cells": 1, "elements": ["a"]}, {"cells": 1, "elements": ["b"]}]

    def test_same_id_twice(self, card: HAAnimCard) -> None:
        """Test two elements with one ID cannot both be on the card."""
        put(card).text("a", "first")
        other = card.create_text("a", "second")
        with pytest.raises(ValueError, match="The card already has an element 'a'"):
            card.add_element(other)
        with pytest.raises(ValueError, match="already has an element 'a'"):
            card.layout.split_row(2).add_element(other)
        assert card.blocks == [{"id": "a", "type": "text", "markdown": "first"}]
        assert card.layout.as_list() == [{"cells": 1, "elements": ["a"]}]

    def test_only_elements_of_this_card(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test what is added has to be an element, and one this card created."""
        files = FakeFileSystem()
        other = HAAnimCard("other", AssetStore("other", None, files), lambda name: True, sink)
        with pytest.raises(ValueError, match="Element 'x' belongs to another card"):
            card.add_element(other.create_text("x", "X"))
        with pytest.raises(TypeError, match="Only elements can be added to a card, not str"):
            card.add_element("x")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="takes an element or its ID, not int"):
            card.remove_element(5)  # type: ignore[arg-type]
        assert card.layout.rows == []

    def test_remove_from_a_split_row(self, card: HAAnimCard) -> None:
        """Test removing an element frees its cell; the row stays, a row of one cell goes."""
        row = card.layout.split_row(2)
        a, b = card.create_text("a", "A"), card.create_text("b", "B")
        row.add_element(a).add_element(b)
        single = put(card).text("c", "C")
        card.layout.remove_element(a)
        card.layout.remove_element(single)
        assert card.layout.as_list() == [{"cells": 2, "elements": ["b"]}]
        assert card.layout.rows == [row]
        row.add_element(a)
        assert row.elements == [b, a]

    def test_removed_element_can_be_added_again(self, card: HAAnimCard) -> None:
        """Test an element that was taken off the card goes last when it is added again."""
        fill(card)
        intro = card.element("intro")
        assert intro is not None
        card.remove_element(intro)
        card.add_element(intro)
        assert [block["id"] for block in card.blocks][-1] == "intro"

    def test_clear_removes_rows_too(self, card: HAAnimCard) -> None:
        """Test clearing the layout forgets the rows; a row from before is no longer part of it."""
        row = card.layout.split_row(2)
        row.add_element(card.create_text("a", "A"))
        card.layout.clear()
        assert card.layout.rows == []
        assert card.blocks == []

    def test_element_lookup(self, card: HAAnimCard) -> None:
        """Test an element on the card is found by its ID."""
        a = put(card).text("a", "A")
        assert card.layout.element("a") is a
        assert card.element("a") is a
        assert card.element("missing") is None

    def test_order_is_row_by_row(self, card: HAAnimCard) -> None:
        """Test blocks are in the order of the layout."""
        fill(card)
        assert [block["id"] for block in card.blocks] == ["intro", "logo", "alerts", "temp", "reset"]

    async def test_layout_is_sent_with_the_content(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test the sink gets the rows together with the blocks, in one update."""
        row = card.layout.split_row(2)
        row.add_element(card.create_text("a", "A")).add_element(card.create_text("b", "B"))
        put(card).text("c", "C")
        await FakeClock().advance()
        assert len(sink.updates) == 1
        assert sink.layouts["climate"] == [
            {"cells": 2, "elements": ["a", "b"]},
            {"cells": 1, "elements": ["c"]},
        ]
        assert sink.contents["climate"]["blocks"] == card.blocks

    async def test_close_empties_the_layout(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test a stopped automation's card has no rows, and the sink is told."""
        old = card.layout
        old.split_row(2).add_element(card.create_text("a", "A"))
        await FakeClock().advance()
        card.close()
        assert card.layout is not old
        assert card.layout.rows == []
        assert sink.layouts["climate"] == []


INVALID: list[tuple[str, Any, type[Exception], str]] = [
    (
        "text too long",
        lambda c: c.create_text("t", "x" * (MAX_TEXT_LENGTH + 1)),
        ValueError,
        "at most 10000 characters",
    ),
    ("text not a string", lambda c: c.create_text("t", 5), TypeError, "markdown must be a string"),
    ("empty id", lambda c: c.create_text("", "x"), ValueError, "id must not be empty"),
    ("blank id", lambda c: c.create_text("  ", "x"), ValueError, "id must not be empty"),
    ("id not a string", lambda c: c.create_text(1, "x"), TypeError, "id must be a string"),
    ("image without source", lambda c: c.create_image("i"), ValueError, "exactly one of asset and url"),
    (
        "image with both",
        lambda c: c.create_image("i", asset="logo.png", url="https://x/y.png"),
        ValueError,
        "exactly one of asset and url",
    ),
    ("image asset missing", lambda c: c.create_image("i", asset="none.png"), FileNotFoundError, "no asset"),
    ("image asset outside", lambda c: c.create_image("i", asset="../main.py"), ValueError, "outside assets/"),
    ("image empty url", lambda c: c.create_image("i", url=""), ValueError, "url must not be empty"),
    ("image url not a string", lambda c: c.create_image("i", url=5), TypeError, "url must be a string"),
    (
        "image alt not a string",
        lambda c: c.create_image("i", url="https://x", alt=None),
        TypeError,
        "alt must be",
    ),
    (
        "value is a list",
        lambda c: c.create_value("v", "L", [1]),
        TypeError,
        "string, number or boolean, not list",
    ),
    ("value is None", lambda c: c.create_value("v", "L", None), TypeError, "not NoneType"),
    ("value is a dict", lambda c: c.create_value("v", "L", {}), TypeError, "not dict"),
    ("value is nan", lambda c: c.create_value("v", "L", float("nan")), ValueError, "finite number"),
    ("value label not a string", lambda c: c.create_value("v", 1, 1), TypeError, "label must be a string"),
    (
        "value unit not a string",
        lambda c: c.create_value("v", "L", 1, unit=1),
        TypeError,
        "unit must be a string",
    ),
    ("entity without domain", lambda c: c.create_entity("e", "temperature"), ValueError, "Invalid entity ID"),
    ("entity with two dots", lambda c: c.create_entity("e", "sensor.a.b"), ValueError, "Invalid entity ID"),
    ("entity empty name", lambda c: c.create_entity("e", "sensor."), ValueError, "Invalid entity ID"),
    ("entity not a string", lambda c: c.create_entity("e", None), TypeError, "entity_id must be a string"),
    (
        "button unknown action",
        lambda c: c.create_button("b", "Go", "nothing"),
        ValueError,
        "Automation 'climate' has no action 'nothing'",
    ),
    (
        "icon without icon or entity",
        lambda c: c.create_icon("i"),
        ValueError,
        "needs an icon, or an entity to follow",
    ),
    (
        "icon not following without icon",
        lambda c: c.create_icon("i", "fan.a", follow_entity=False),
        ValueError,
        "needs an icon, or an entity to follow",
    ),
    (
        "icon name without set",
        lambda c: c.create_icon("i", icon="fan"),
        ValueError,
        "an icon is named like 'mdi:fan'",
    ),
    ("icon name with markup", lambda c: c.create_icon("i", icon='mdi:fan"><b'), ValueError, "Invalid icon"),
    ("icon name in capitals", lambda c: c.create_icon("i", icon="MDI:Fan"), ValueError, "Invalid icon"),
    ("icon not a string", lambda c: c.create_icon("i", icon=5), TypeError, "icon must be a string"),
    (
        "icon color with css",
        lambda c: c.create_icon("i", icon="mdi:fan", color="red; x: y"),
        ValueError,
        "Invalid color",
    ),
    (
        "icon color function",
        lambda c: c.create_icon("i", icon="mdi:fan", color="rgb(1,2,3)"),
        ValueError,
        "Invalid color",
    ),
    (
        "icon color not a string",
        lambda c: c.create_icon("i", icon="mdi:fan", color=3),
        TypeError,
        "color must be",
    ),
    ("icon entity invalid", lambda c: c.create_icon("i", "fan"), ValueError, "Invalid entity ID"),
    (
        "icon label not a string",
        lambda c: c.create_icon("i", icon="mdi:fan", label=1),
        TypeError,
        "label must be",
    ),
    (
        "icon spin not a bool",
        lambda c: c.create_icon("i", icon="mdi:fan", spin="yes"),
        TypeError,
        "spin must be True",
    ),
    (
        "icon follow not a bool",
        lambda c: c.create_icon("i", "fan.a", follow_entity=1),
        TypeError,
        "follow_entity must be True or False",
    ),
    ("graph without data", lambda c: c.create_graph("g"), ValueError, "exactly one of entities and series"),
    (
        "graph with both",
        lambda c: c.create_graph("g", "sensor.a", {"A": [1]}),
        ValueError,
        "exactly one of entities and series",
    ),
    (
        "graph kind",
        lambda c: c.create_graph("g", "sensor.a", kind="pie"),
        ValueError,
        "a graph is one of line, area, bar",
    ),
    (
        "graph title not a string",
        lambda c: c.create_graph("g", "sensor.a", title=1),
        TypeError,
        "title must be",
    ),
    ("graph unit not a string", lambda c: c.create_graph("g", "sensor.a", unit=1), TypeError, "unit must be"),
    (
        "graph min not a number",
        lambda c: c.create_graph("g", "sensor.a", min="0"),
        TypeError,
        "min must be a number",
    ),
    (
        "graph max is nan",
        lambda c: c.create_graph("g", "sensor.a", max=float("nan")),
        ValueError,
        "max must be a finite",
    ),
    (
        "graph min above max",
        lambda c: c.create_graph("g", "sensor.a", min=5, max=5),
        ValueError,
        "must be less than max",
    ),
    (
        "graph hours zero",
        lambda c: c.create_graph("g", "sensor.a", hours=0),
        ValueError,
        "hours must be more than 0",
    ),
    ("graph hours too many", lambda c: c.create_graph("g", "sensor.a", hours=721), ValueError, "at most 720"),
    (
        "graph hours not a number",
        lambda c: c.create_graph("g", "sensor.a", hours="24"),
        TypeError,
        "hours must be",
    ),
    (
        "graph hours a bool",
        lambda c: c.create_graph("g", "sensor.a", hours=True),
        TypeError,
        "hours must be a number",
    ),
    ("graph no entities", lambda c: c.create_graph("g", []), ValueError, "1 to 8 entities, not 0"),
    (
        "graph too many entities",
        lambda c: c.create_graph("g", [f"sensor.s{i}" for i in range(9)]),
        ValueError,
        "1 to 8 entities, not 9",
    ),
    (
        "graph entity invalid",
        lambda c: c.create_graph("g", ["sensor.a", "nodomain"]),
        ValueError,
        "Invalid entity ID",
    ),
    (
        "graph entity twice",
        lambda c: c.create_graph("g", ["sensor.a", "sensor.a"]),
        ValueError,
        "each entity once",
    ),
    (
        "graph entities a dict",
        lambda c: c.create_graph("g", {"sensor.a": 1}),
        TypeError,
        "entities must be an entity ID",
    ),
    ("graph entities a number", lambda c: c.create_graph("g", 5), TypeError, "entities must be an entity ID"),
    (
        "graph series a list",
        lambda c: c.create_graph("g", series=[1, 2]),
        TypeError,
        "series must be a dictionary",
    ),
    ("graph no series", lambda c: c.create_graph("g", series={}), ValueError, "1 to 8 series, not 0"),
    (
        "graph too many series",
        lambda c: c.create_graph("g", series={f"S{i}": [1] for i in range(9)}),
        ValueError,
        "1 to 8 series, not 9",
    ),
    (
        "graph series name empty",
        lambda c: c.create_graph("g", series={"": [1]}),
        ValueError,
        "series name must not be empty",
    ),
    (
        "graph series name a number",
        lambda c: c.create_graph("g", series={1: [1]}),
        TypeError,
        "series name must be",
    ),
    (
        "graph points a string",
        lambda c: c.create_graph("g", series={"A": "123"}),
        TypeError,
        "points must be a list",
    ),
    (
        "graph points a number",
        lambda c: c.create_graph("g", series={"A": 5}),
        TypeError,
        "points must be a list",
    ),
    (
        "graph too many points",
        lambda c: c.create_graph("g", series={"A": list(range(501))}),
        ValueError,
        "has 501 points; a series has at most 500",
    ),
    (
        "graph numbers and states in one series",
        lambda c: c.create_graph("g", series={"A": [1, "on"]}),
        ValueError,
        "series 'A' mixes numbers and states",
    ),
    (
        "graph state empty",
        lambda c: c.create_graph("g", series={"A": ["on", " "]}),
        ValueError,
        "series 'A', point 1",
    ),
    (
        "graph state too long",
        lambda c: c.create_graph("g", series={"A": ["x" * 41]}),
        ValueError,
        "1 to 40 characters",
    ),
    (
        "graph value a list",
        lambda c: c.create_graph("g", series={"A": [(0, [1])]}),
        TypeError,
        "series 'A', point 0",
    ),
    (
        "graph value infinite",
        lambda c: c.create_graph("g", series={"A": [float("inf")]}),
        ValueError,
        "finite number",
    ),
    (
        "graph value a bool",
        lambda c: c.create_graph("g", series={"A": [True]}),
        TypeError,
        "must be a number, not bool",
    ),
    (
        "graph triple",
        lambda c: c.create_graph("g", series={"A": [(1, 2, 3)]}),
        ValueError,
        "a value or an \\(x, y\\) pair",
    ),
    (
        "graph time not iso",
        lambda c: c.create_graph("g", series={"A": [("noon", 1)]}),
        ValueError,
        "not a time in ISO",
    ),
    (
        "graph time without zone",
        lambda c: c.create_graph("g", series={"A": [("2025-01-06 12:00", 1)]}),
        ValueError,
        "has no time zone",
    ),
    (
        "graph naive datetime",
        lambda c: c.create_graph("g", series={"A": [(datetime(2025, 1, 6), 1)]}),
        ValueError,
        "has no time zone",
    ),
    (
        "graph mixed positions",
        lambda c: c.create_graph("g", series={"A": [1, 2], "B": [(0, 1)]}),
        ValueError,
        "these are mixed: index, number",
    ),
    (
        "graph numbers and times",
        lambda c: c.create_graph("g", series={"A": [(0, 1), ("2025-01-06T12:00:00+00:00", 1)]}),
        ValueError,
        "these are mixed: number, time",
    ),
    (
        "graph major zero",
        lambda c: c.create_graph("g", series={"A": [1]}, x_major=0),
        ValueError,
        "x_major must be more",
    ),
    (
        "graph minor negative",
        lambda c: c.create_graph("g", series={"A": [1]}, x_minor=-1),
        ValueError,
        "x_minor must be",
    ),
    (
        "graph major a duration on a number axis",
        lambda c: c.create_graph("g", series={"A": [1]}, x_major="01:00:00"),
        TypeError,
        "x_major must be a number",
    ),
    (
        "graph minor not below major",
        lambda c: c.create_graph("g", series={"A": [1]}, x_major=5, x_minor=5),
        ValueError,
        "x_minor \\(5\\) must be less than x_major \\(5\\)",
    ),
    (
        "graph major not a duration",
        lambda c: c.create_graph("g", "sensor.a", x_major="an hour"),
        ValueError,
        "x_major is a duration on a time axis",
    ),
    (
        "graph minor duration zero",
        lambda c: c.create_graph("g", "sensor.a", x_minor=0),
        ValueError,
        "x_minor is a duration on a time axis",
    ),
    (
        "graph minor duration above major",
        lambda c: c.create_graph("g", "sensor.a", x_major="00:30:00", x_minor="01:00:00"),
        ValueError,
        "x_minor \\(3600\\) must be less than x_major \\(1800\\)",
    ),
    (
        "button label not a string",
        lambda c: c.create_button("b", 1, "reset"),
        TypeError,
        "label must be a string",
    ),
    (
        "button action not a string",
        lambda c: c.create_button("b", "Go", None),
        TypeError,
        "action must be a string",
    ),
    (
        "button confirm not a string",
        lambda c: c.create_button("b", "Go", "reset", confirm=True),
        TypeError,
        "confirm",
    ),
    (
        "button data not JSON",
        lambda c: c.create_button("b", "Go", "reset", when={1, 2}),
        TypeError,
        "JSON values",
    ),
    ("remove not an element", lambda c: c.remove_element(5), TypeError, "takes an element or its ID"),
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

    def test_invalid_change_keeps_the_old_value(self, card: HAAnimCard) -> None:
        """Test a failed change leaves the element that was there."""
        alerts = put(card).value("alerts", "Alerts", 1)
        with pytest.raises(TypeError):
            alerts.set_value([2])
        assert card.blocks[0]["value"] == 1

    def test_text_at_the_limit(self, card: HAAnimCard) -> None:
        """Test a text element of exactly 10 000 characters is accepted."""
        put(card).text("t", "x" * MAX_TEXT_LENGTH)
        assert len(card.blocks[0]["markdown"]) == 10_000

    def test_element_limit(self, card: HAAnimCard) -> None:
        """Test the 51st element raises ValueError and the card keeps its 50."""
        for index in range(MAX_BLOCKS):
            put(card).value(f"v{index}", "L", index)
        with pytest.raises(ValueError, match="at most 50 elements"):
            put(card).text("one_more", "x")
        with pytest.raises(ValueError, match="at most 50 elements"):
            card.layout.split_row(2).add_element(card.create_text("in_a_row", "x"))
        assert len(card.blocks) == 50
        assert "one_more" not in [block["id"] for block in card.blocks]

    def test_change_and_move_at_the_limit(self, card: HAAnimCard) -> None:
        """Test a full card still accepts changing and moving an element, and a new one after a removal."""
        elements = [put(card).value(f"v{index}", "L", index) for index in range(MAX_BLOCKS)]
        elements[7].set_value("changed")
        card.add_element(elements[0])
        assert card.blocks[6]["value"] == "changed"
        assert card.blocks[-1]["id"] == "v0"
        card.remove_element("v1")
        put(card).text("one_more", "x")
        assert len(card.blocks) == 50

    def test_limits_are_the_designs(self) -> None:
        """Test the limits are 50 blocks and 10 000 characters."""
        assert (MAX_BLOCKS, MAX_TEXT_LENGTH) == (50, 10_000)


class TestSynchronous:
    """Rule: all card methods return immediately and are not awaited."""

    @pytest.mark.parametrize(
        "name",
        [
            "create_text",
            "create_image",
            "create_value",
            "create_entity",
            "create_icon",
            "create_graph",
            "create_button",
            "add_element",
            "remove_element",
            "clear",
        ],
    )
    def test_methods_are_plain_functions(self, name: str) -> None:
        """Test no card method is a coroutine function."""
        assert not inspect.iscoroutinefunction(getattr(HAAnimCard, name))

    @pytest.mark.parametrize(
        "cls", [CardLayout, CardRow, TextElement, ValueElement, GraphElement, ButtonElement]
    )
    def test_layout_and_elements_are_synchronous(self, cls: type) -> None:
        """Test no method of the layout, a row or an element is a coroutine function."""
        for name in dir(cls):
            if not name.startswith("_"):
                assert not inspect.iscoroutinefunction(getattr(cls, name)), name


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
        put(card).text("a", "one")
        await FakeClock().advance()
        put(card).text("b", "two")
        put(card).text("c", "three")
        await FakeClock().advance()
        assert [len(blocks) for _, blocks in sink.updates] == [1, 3]

    async def test_no_update_without_a_change(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test setting what is already so, removing nothing and clearing nothing send nothing."""
        text = put(card).text("a", "one")
        await FakeClock().advance()
        text.set_text("one")
        card.remove_element("missing")
        card.create_text("unused", "never added").set_text("still not shown")
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

    async def test_change_and_removal_are_sent(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test a changed and a removed element each lead to an update."""
        fill(card)
        await FakeClock().advance()
        alerts = card.element("alerts")
        assert isinstance(alerts, ValueElement)
        alerts.set_value(1)
        await FakeClock().advance()
        card.remove_element("logo")
        await FakeClock().advance()
        assert [len(blocks) for _, blocks in sink.updates] == [5, 5, 4]
        assert sink.updates[1][1][2]["value"] == 1

    async def test_several_setters_are_one_update(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test setters called one after the other, on one element or several, are sent together."""
        a, b = put(card).value("a", "A", 0), put(card).value("b", "B", 0)
        await FakeClock().advance()
        a.set_value(1)
        a.set_label("Changed")
        b.set_value(2)
        await FakeClock().advance()
        assert len(sink.updates) == 2
        assert [block["value"] for block in sink.updates[1][1]] == [1, 2]

    async def test_the_update_is_a_copy(self, card: HAAnimCard, sink: FakeCardSink) -> None:
        """Test what the sink got does not change when the card does."""
        text = put(card).text("a", "one")
        await FakeClock().advance()
        text.set_text("two")
        assert sink.updates[0][1][0]["markdown"] == "one"

    def test_without_an_event_loop_the_update_is_immediate(
        self, card: HAAnimCard, sink: FakeCardSink
    ) -> None:
        """Test a change made outside the event loop is sent at once."""
        put(card).text("a", "one")
        assert len(sink.updates) == 1

    async def test_no_sink(self) -> None:
        """Test a card nobody shows works the same."""
        card = HAAnimCard("climate", AssetStore("climate", None, FakeFileSystem()), lambda name: True)
        put(card).text("a", "one")
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

alerts = haa.card.create_value("alerts", label="Alerts today", value=0)
step = haa.card.create_text("step", "not started")

@action(aliases=["reset"])
def reset_alerts(event):
    alerts.set_value(0)
    return event.data

@startup
def build_card(event):
    haa.card.add_element(haa.card.create_text("intro", "## Climate"))
    haa.card.add_element(alerts)
    row = haa.card.layout.split_row(2)
    row.add_element(haa.card.create_entity("temp", "sensor.temperature"))
    row.add_element(
        haa.card.create_button("reset", label="Reset counter", action="reset_alerts", confirm="Reset the counter?")
    )

@action
def alert(event):
    alerts.set_value(1)
    alerts.set_value(2)
    alerts.set_value(3)
    return [block["id"] for block in haa.card.blocks]

@action
def bad_button(event):
    haa.card.add_element(haa.card.create_button("nope", label="Nope", action="missing"))

@action
def alias_button(event):
    haa.card.add_element(haa.card.create_button("alias", label="Alias", action="reset"))

@action
async def two_steps(event):
    haa.card.add_element(step)
    step.set_text("one")
    await haa.sleep(1)
    step.set_text("two")

@action
def typed(event):
    from haanim import CardElement, CardLayout, CardRow, ValueElement
    return [isinstance(alerts, ValueElement), isinstance(alerts, CardElement),
            isinstance(haa.card.layout, CardLayout), isinstance(haa.card.layout.rows[-1], CardRow)]
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
        await world.started(
            "other", "from haanim import haa\nhaa.card.add_element(haa.card.create_text('only', 'mine'))\n"
        )
        await world.clock.advance()
        assert [block["id"] for block in world.host.cards.cards["other"]] == ["only"]
        assert len(world.host.cards.cards["climate"]) == 4

    async def test_layout_from_an_automation(self, world: World) -> None:
        """Test the rows an automation makes reach the host, and the classes can be imported for type hints."""
        automation = await world.started("climate", SOURCE)
        await world.clock.advance()
        assert world.host.cards.layouts["climate"] == [
            {"cells": 1, "elements": ["intro"]},
            {"cells": 1, "elements": ["alerts"]},
            {"cells": 2, "elements": ["temp", "reset"]},
        ]
        assert await automation.call_action("typed") == [True, True, True, True]

    async def test_elements_made_at_module_level_survive_into_actions(self, world: World) -> None:
        """Test an element kept in a module variable is the one on the card, start after start."""
        automation = await world.started("climate", SOURCE)
        await automation.call_action("alert")
        await automation.stop()
        assert await automation.start()
        await world.clock.advance()
        assert world.host.cards.cards["climate"][1]["value"] == 0
        await automation.call_action("alert")
        await world.clock.advance()
        assert world.host.cards.cards["climate"][1]["value"] == 3
