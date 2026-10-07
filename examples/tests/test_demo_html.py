"""Tests for the HTML demo: what HTML it puts on its card, and that text from outside is escaped."""

from __future__ import annotations

from pathlib import Path

import pytest

from haanim.testing import AutomationHarness

DEMO = Path(__file__).parents[1] / "demo_html"

STATES = {"sensor.temperature": "21.5", "input_boolean.fan": "on", "sun.sun": "<above>"}


async def test_card_is_built_at_startup() -> None:
    """The card has a heading and four elements of HTML."""
    async with AutomationHarness(DEMO, states=STATES) as automation:
        assert [(block["id"], block["type"]) for block in automation.card.blocks] == [
            ("intro", "text"),
            ("table", "html"),
            ("bars", "html"),
            ("links", "html"),
            ("details", "html"),
        ]
        assert automation.card.block("details")["html"].startswith("<details><summary>")


async def test_table_of_entities() -> None:
    """The table has a row per entity; one that is not there says so."""
    async with AutomationHarness(DEMO, states=STATES) as automation:
        table = automation.card.block("table")["html"]
        assert table.count("<tr>") == 5
        assert "<code>sensor.temperature</code>" in table
        assert 'font-weight: 500">21.5</td>' in table
        assert "<code>sensor.outdoor_temp</code>" in table
        assert "<em>not there</em>" in table
        assert "border-top: 3px solid #03a9f4" in table


async def test_text_from_outside_is_escaped() -> None:
    """A state and the note reach the page as text, whatever they contain."""
    async with AutomationHarness(DEMO, states=STATES) as automation:
        table = automation.card.block("table")["html"]
        assert "&lt;above&gt;" in table
        assert "<above>" not in table
        assert "&lt;b&gt;not bold&lt;/b&gt; &amp; &lt;script&gt;" in table
        assert "<script>" not in table

        assert (
            await automation.call("set_note", text='<img src=x onerror="alert(1)">')
            == '<img src=x onerror="alert(1)">'
        )
        table = automation.card.block("table")["html"]
        assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in table
        assert "<img" not in table


async def test_links_run_actions() -> None:
    """The swatches and the link carry the action they run, the swatches with their data."""
    async with AutomationHarness(DEMO, states=STATES) as automation:
        links = automation.card.block("links")["html"]
        assert links.count('data-haanim="run" data-action="pick"') == 4
        assert 'data-payload="{&quot;color&quot;: &quot;#4caf50&quot;}" title="Green"' in links
        assert 'data-haanim="run" data-action="refresh"' in links


async def test_pick_a_colour() -> None:
    """Picking a colour draws the table, the bars and the swatches with it, and it is kept."""
    async with AutomationHarness(DEMO, states=STATES) as automation:
        assert await automation.call("pick", color="#4caf50") == "#4caf50"
        assert "border-top: 3px solid #4caf50" in automation.card.block("table")["html"]
        assert automation.card.block("bars")["html"].count("background: #4caf50") == 5
        assert (
            "background: #4caf50; border: 2px solid var(--primary-text-color)"
            in automation.card.block("links")["html"]
        )
        assert automation.get_variable("color") == "#4caf50"


async def test_a_colour_that_is_none_is_refused() -> None:
    """The colour goes into a style, so only the colours of the swatches are taken."""
    async with AutomationHarness(DEMO, states=STATES) as automation:
        before = automation.card.block("table")["html"]
        with pytest.raises(ValueError, match="is not one of the colours"):
            await automation.call("pick", color="red; background: url(x)")
        assert automation.card.block("table")["html"] == before


async def test_refresh_reads_the_entities_again() -> None:
    """HTML does not follow entities: the action, and a trigger every half minute, draw it again."""
    async with AutomationHarness(DEMO, states=STATES, now="2025-01-06 12:00:00") as automation:
        automation.set_state("sensor.temperature", "30")
        assert "21.5</td>" in automation.card.block("table")["html"]
        (
            await automation.call("refresh")
            if hasattr(automation, "press_html")
            else await automation.call("refresh")
        )
        assert "30</td>" in automation.card.block("table")["html"]
        assert automation.message == "Drawn at 12:00:00"

        automation.set_state("sensor.temperature", "31")
        await automation.advance_time(seconds=31)
        assert "31</td>" in automation.card.block("table")["html"]
