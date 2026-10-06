"""Demo: raw HTML on a card.

``haa.card.create_html()`` puts HTML of the automation's own on the card as it
is. That is for what the other elements cannot do: a real table, inline
styles, bars, anything HTML and CSS can draw. Home Assistant's theme
variables (``var(--primary-color)``) work in it.

Unlike everything else on a card, HTML is not sanitised. Every text the
automation did not write itself goes through ``html.escape()`` first: here
the entity states and the note, which is deliberately full of markup.

An element with ``data-haanim="run"`` runs an action when it is clicked, so
HTML can have its own buttons and links: the colour swatches and the Refresh
link below.
"""

import html
import json

from haanim import ActionEvent, IntervalEvent, action, haa, on_interval, startup

ENTITIES = ["sensor.temperature", "sensor.outdoor_temp", "input_boolean.fan", "sun.sun"]
COLORS = {"Blue": "#03a9f4", "Green": "#4caf50", "Orange": "#ff9800", "Purple": "#9c27b0"}
DEFAULT_NOTE = "<b>not bold</b> & <script>alert('no')</script>"

table = haa.card.create_html("table", "")
bars = haa.card.create_html("bars", "")
links = haa.card.create_html("links", "")


def color() -> str:
    """The colour picked with the swatches."""
    return str(haa.get_variable("color", COLORS["Blue"]))


def table_html() -> str:
    """A table of entities and their states. States are text from outside: they are escaped."""
    cell = "padding: 4px 8px; border-bottom: 1px solid var(--divider-color)"
    lines = []
    for entity_id in ENTITIES:
        state = haa.state(entity_id)
        shown = html.escape(state) if state is not None else "<em>not there</em>"
        lines.append(f'<tr><td style="{cell}"><code>{html.escape(entity_id)}</code></td>')
        lines.append(f'<td style="{cell}; text-align: right; font-weight: 500">{shown}</td></tr>')
    note = html.escape(str(haa.get_variable("note", DEFAULT_NOTE)))
    return (
        f'<table style="width: 100%; border-collapse: collapse; border-top: 3px solid {color()}">'
        f'<tr><th style="{cell}; text-align: left">Entity</th><th style="{cell}; text-align: right">State</th></tr>'
        f"{''.join(lines)}</table>"
        f'<p style="color: var(--secondary-text-color); font-size: 0.9em">Escaped note: {note}</p>'
    )


def bars_html() -> str:
    """Bars drawn with nothing but styled boxes."""
    values = {"Mon": 3, "Tue": 7, "Wed": 5, "Thu": 9, "Fri": 4}
    columns = []
    for day, value in values.items():
        columns.append(
            '<div style="flex: 1; text-align: center">'
            f'<div style="height: {value * 8}px; background: {color()}; border-radius: 4px 4px 0 0"></div>'
            f"<small>{day}</small></div>"
        )
    return (
        f'<div style="display: flex; gap: 6px; align-items: flex-end; height: 96px">{"".join(columns)}</div>'
    )


def links_html() -> str:
    """Swatches and a link that run actions: ``data-payload`` is the data of the call, as JSON."""
    swatches = []
    for name, value in COLORS.items():
        payload = html.escape(json.dumps({"color": value}))
        ring = "2px solid var(--primary-text-color)" if value == color() else "2px solid transparent"
        swatches.append(
            f'<span data-haanim="run" data-action="pick" data-payload="{payload}" title="{name}" '
            f'style="display: inline-block; width: 24px; height: 24px; border-radius: 50%; cursor: pointer; '
            f'background: {value}; border: {ring}"></span>'
        )
    return (
        f'<div style="display: flex; gap: 8px; align-items: center">{"".join(swatches)}'
        '<a data-haanim="run" data-action="refresh" style="margin-left: auto; cursor: pointer; '
        'color: var(--primary-color)">Refresh</a></div>'
    )


def draw() -> None:
    """Build the HTML again and put it on the card."""
    table.set_html(table_html())
    bars.set_html(bars_html())
    links.set_html(links_html())


@startup
def build_card(event: ActionEvent) -> None:
    """Lay the card out."""
    card = haa.card
    card.add_element(card.create_text("intro", "## HTML\nA table, bars and links, all written as HTML:"))
    card.add_element(table)
    card.add_element(bars)
    card.add_element(links)
    card.add_element(
        card.create_html(
            "details",
            "<details><summary>Anything HTML can do</summary>"
            '<p>A <kbd>details</kbd> element, <mark>marked</mark> text, <span style="font-size: 1.4em">sizes</span>, '
            '<span style="color: var(--error-color)">theme colours</span>.</p></details>',
        )
    )
    draw()


@action(description="Read the entities again and draw the HTML")
def refresh(event: ActionEvent) -> None:
    """Draw the HTML again with the states as they are now."""
    draw()
    haa.set_message(f"Drawn at {haa.now().strftime('%H:%M:%S')}")


@action(description="Pick the colour of the table and the bars")
def pick(event: ActionEvent) -> str:
    """Set the colour to ``color``, one of the swatches; anything else is refused."""
    picked = str(event.data.get("color", ""))
    if picked not in COLORS.values():
        raise ValueError(f"{picked!r} is not one of the colours")
    haa.set_variable("color", picked)
    draw()
    return picked


@action(description="Set the note under the table; it is escaped, whatever it contains")
def set_note(event: ActionEvent) -> str:
    """Store ``text`` as the note. It is shown as text, never as markup."""
    note = str(event.data.get("text", DEFAULT_NOTE))
    haa.set_variable("note", note)
    draw()
    return note


@on_interval("00:00:30")
def keep_fresh(event: ActionEvent) -> None:
    """HTML does not follow entities by itself, so the automation draws it again now and then."""
    if isinstance(event, IntervalEvent):
        draw()
