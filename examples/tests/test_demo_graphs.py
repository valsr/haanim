"""Tests for the graphs demo: the graphs on its card, and how the first one changes."""

from __future__ import annotations

from pathlib import Path

from haanim.testing import AutomationHarness

DEMO = Path(__file__).parents[1] / "demo_graphs"


async def test_card_has_five_graphs() -> None:
    """The card has the five kinds of graph, in order."""
    async with AutomationHarness(DEMO) as automation:
        graphs = [block["id"] for block in automation.card.blocks if block["type"] == "graph"]
        assert graphs == ["samples", "curve", "power", "pump", "history"]
        assert automation.card.block("samples")["kind"] == "bar"
        assert automation.card.block("samples")["x"] == "index"
        assert automation.message == "0 samples"


async def test_pairs_times_and_states() -> None:
    """The second graph has a number axis, the third and fourth a time axis; the fourth draws states."""
    async with AutomationHarness(DEMO, now="2025-01-06 12:00:00") as automation:
        curve = automation.card.block("curve")
        assert (curve["x"], curve["min"], curve["max"], curve["x_major"], curve["x_minor"]) == (
            "number",
            15,
            25,
            6,
            1,
        )
        assert curve["series"]["Target"][1] == [6.0, 21.0]
        power = automation.card.block("power")
        assert power["x"] == "time"
        assert len(power["series"]["Power"]) == 7
        pump = automation.card.block("pump")
        assert [state for _, state in pump["series"]["Pump"]] == ["off", "on", "off", "on"]


async def test_history_of_entities() -> None:
    """The last graph asks for the recorded history of two entities over an hour."""
    async with AutomationHarness(DEMO) as automation:
        history = automation.card.block("history")
        assert history["entities"] == ["sensor.temperature", "input_boolean.fan"]
        assert (history["hours"], history["kind"]) == (1, "area")
        assert (history["x_major"], history["x_minor"]) == (900, 300)


async def test_samples_are_added_and_kept() -> None:
    """A sample is a value given, or the next point of a wave; the graph keeps the last twenty."""
    async with AutomationHarness(DEMO) as automation:
        assert await automation.call("sample", value=3) == 3.0
        assert await automation.press("add") == 20.0 + round(5 * 0.479425538604203, 1)
        assert [y for _, y in automation.card.block("samples")["series"]["Sample"]] == [3.0, 22.4]
        for value in range(30):
            await automation.call("sample", value=value)
        assert len(automation.card.block("samples")["series"]["Sample"]) == 20
        assert automation.get_variable("samples")[-1] == 29.0
        assert automation.message == "20 samples"


async def test_clear() -> None:
    """Clear empties the graph."""
    async with AutomationHarness(DEMO, variables={"samples": [1.0, 2.0], "taken": 2}) as automation:
        assert len(automation.card.block("samples")["series"]["Sample"]) == 2
        await automation.press("clear")
        assert automation.card.block("samples")["series"]["Sample"] == []
        assert automation.get_variable("taken") == 0


async def test_kind_goes_round() -> None:
    """The kind button draws the first graph as a line, an area, and bars again."""
    async with AutomationHarness(DEMO) as automation:
        assert [await automation.press("kind") for _ in range(3)] == ["line", "area", "bar"]
        assert automation.card.block("samples")["kind"] == "bar"


async def test_a_sample_every_minute() -> None:
    """The graph moves on its own: a sample a minute. Run by hand, the trigger function adds none."""
    async with AutomationHarness(DEMO) as automation:
        await automation.advance_time(minutes=3)
        assert len(automation.card.block("samples")["series"]["Sample"]) == 3
        await automation.call("every_minute")
        assert len(automation.card.block("samples")["series"]["Sample"]) == 3
