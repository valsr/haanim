"""Tests for the card content model: ``haa.card``.

See "GUI", "Card Content" in the design.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.assets import AssetStore
from haanim.engine.card import MAX_BLOCKS, MAX_TEXT_LENGTH, HAAnimCard
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

    @pytest.mark.parametrize("name", ["text", "image", "value", "entity", "button", "remove", "clear"])
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
