"""Demo: graphs.

Five graphs, from the simplest to the richest:

1. plain numbers, as bars: one value after the other;
2. ``(x, y)`` pairs over a number axis, with a fixed range and marks of its own;
3. values over time;
4. states (text, not numbers), which become a timeline;
5. the history Home Assistant recorded for entities, which the card then follows.

Hover over a graph to read a single value. The buttons add a sample to the
first graph, empty it, and switch how it is drawn.
"""

import math
from datetime import timedelta

from haanim import ActionEvent, IntervalEvent, action, haa, on_interval, startup

TEMPERATURE = "sensor.temperature"
FAN = "input_boolean.fan"  # a Toggle helper called "Fan"; any entity that is on or off will do
KEPT = 20
KINDS = ["bar", "line", "area"]

# 1. Plain numbers: the points are drawn one after the other
samples = haa.card.create_graph("samples", series={"Sample": []}, kind="bar", title="1. Your own numbers")

# 2. (x, y) pairs over a number axis; min and max fix the value axis, x_major and x_minor the marks
curve = haa.card.create_graph(
    "curve",
    series={"Target": [(0, 18), (6, 21), (9, 19), (17, 21.5), (22, 18), (24, 18)]},
    title="2. Pairs over a number axis: target by hour",
    unit="°C",
    min=15,
    max=25,
    x_major=6,
    x_minor=1,
)


def stored() -> list[float]:
    """The samples kept so far."""
    values: list[float] = haa.get_variable("samples", [])
    return values


def show_samples() -> None:
    """Draw the stored samples."""
    samples.set_series({"Sample": stored()})
    haa.set_message(f"{len(stored())} samples")


@startup
def build_card(event: ActionEvent) -> None:
    """Lay the card out."""
    card = haa.card
    card.add_element(card.create_text("intro", "## Graphs\nHover over a graph to read a value."))
    card.add_element(samples)
    buttons = card.layout.split_row(3)
    buttons.add_element(card.create_button("add", label="Add a sample", action="sample"))
    buttons.add_element(card.create_button("clear", label="Clear", action="clear"))
    buttons.add_element(card.create_button("kind", label="Bars / line / area", action="next_kind"))
    card.add_element(curve)

    # 3. Values over time: every x is a time. Here the last six hours, one value an hour.
    now = haa.now()
    hours = [now - timedelta(hours=back) for back in range(6, -1, -1)]
    power = [(moment, 300 + 200 * math.sin(index)) for index, moment in enumerate(hours)]
    card.add_element(
        card.create_graph("power", series={"Power": power}, kind="area", title="3. Over time", unit="W")
    )

    # 4. States: text instead of numbers. A state holds until the next point, and None is a gap.
    card.add_element(
        card.create_graph(
            "pump",
            series={
                "Pump": [(hours[0], "off"), (hours[2], "on"), (hours[3], "off"), (hours[5], "on")],
                "Mode": [(hours[0], "auto"), (hours[4], "manual"), (hours[6], "manual")],
            },
            title="4. States become a timeline",
        )
    )

    # 5. What Home Assistant recorded for entities; the graph follows them from then on. The
    # temperature is numbers, the fan is on or off: one graph has both.
    card.add_element(
        card.create_graph(
            "history",
            [TEMPERATURE, FAN],
            hours=1,
            kind="area",
            title="5. History of entities, last hour",
            x_major="00:15:00",
            x_minor="00:05:00",
        )
    )
    show_samples()


@action(description="Add a sample to the first graph")
def sample(event: ActionEvent) -> float:
    """Add ``value`` to the samples, or the next point of a wave if none is given; keep the last twenty."""
    count = int(haa.get_variable("taken", 0))
    value = float(event.data.get("value", round(20 + 5 * math.sin(count / 2), 1)))
    haa.set_variable("taken", count + 1)
    haa.set_variable("samples", [*stored(), value][-KEPT:])
    show_samples()
    return value


@action(description="Empty the first graph")
def clear(event: ActionEvent) -> None:
    """Forget the samples."""
    haa.set_variable("samples", [])
    haa.set_variable("taken", 0)
    show_samples()


@action(description="Draw the first graph as bars, a line or an area")
def next_kind(event: ActionEvent) -> str:
    """Switch to the next way of drawing numbers."""
    kind = KINDS[(KINDS.index(samples.kind) + 1) % len(KINDS)]
    samples.set_kind(kind)
    return kind


@on_interval("00:01:00")
async def every_minute(event: ActionEvent) -> None:
    """Add a sample every minute, so the graph moves on its own."""
    if isinstance(event, IntervalEvent):
        await haa.call("sample")
