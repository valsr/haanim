"""Demo: reading long-term statistics.

Home Assistant keeps hourly long-term statistics of every sensor that has a
``state_class``, for as long as it runs, while its history is purged after
ten days. ``haa.statistics()`` reads them, grouped by hour, day, week or month.

This demo reads those of ``sensor.temperature``: day by day for the last seven
days, or month by month for this year, with the lowest, mean and highest
temperature of each, in a table and a graph. The buttons switch between the two.

A sensor that counts (energy, water: ``total`` or ``total_increasing``) has
``state``, ``sum`` and ``change`` instead of ``min``, ``mean`` and ``max``.
``demo_entities`` imports statistics into a sensor of its own.
"""

from datetime import timedelta

from haanim import (
    ActionEvent,
    IntervalEvent,
    Period,
    StatisticsUnavailableError,
    UnitOfTemperature,
    action,
    haa,
    on_interval,
    startup,
)

SENSOR = "sensor.temperature"  # any sensor with a state_class of "measurement"
CELSIUS = UnitOfTemperature.CELSIUS
KEYS = ("min", "mean", "max")

table = haa.card.create_table(
    "statistics",
    columns=["Period", "Lowest", "Mean", "Highest"],
    units=["", CELSIUS, CELSIUS, CELSIUS],
    rows=[],
)
graph = haa.card.create_graph("trend", series={"Lowest": [], "Mean": [], "Highest": []}, unit=CELSIUS)


def views() -> dict[str, tuple[str, Period, object, str]]:
    """Each view: its title, its period, where it starts, and how a period's start is written."""
    today = haa.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "week": ("Last 7 days", Period.DAY, today - timedelta(days=6), "%a %d %b"),
        "year": ("This year, by month", Period.MONTH, today.replace(month=1, day=1), "%B"),
    }


async def show(view: str) -> int:
    """Read the statistics of a view and show them; return how many periods there are."""
    title, period, start, label = views()[view]
    haa.set_variable("view", view)
    table.set_title(title)
    graph.set_title(title)
    try:
        rows = await haa.statistics(SENSOR, start, period=period)
    except StatisticsUnavailableError:
        haa.set_message("Home Assistant keeps no statistics here: is the recorder on?")
        return 0
    if not rows:
        haa.set_message(f"No statistics of {SENSOR} yet: Home Assistant compiles them every hour")
    else:
        haa.set_message(f"{len(rows)} periods of {SENSOR}")

    # Rows have start and end (in UTC); show them in Home Assistant's time zone
    zone = haa.now().tzinfo
    table.set_rows(
        [
            [row["start"].astimezone(zone).strftime(label), *(round(row[key], 1) for key in KEYS)]
            for row in rows
        ]
    )
    graph.set_series(
        {
            "Lowest": [(row["start"], row["min"]) for row in rows],
            "Mean": [(row["start"], row["mean"]) for row in rows],
            "Highest": [(row["start"], row["max"]) for row in rows],
        }
    )
    return len(rows)


@startup
async def build_card(event: ActionEvent) -> None:
    """Lay the card out and show the last week."""
    card = haa.card
    card.add_element(card.create_text("intro", f"## Statistics\nWhat Home Assistant kept of `{SENSOR}`."))
    buttons = card.layout.split_row(2)
    buttons.add_element(card.create_button("week", label="Last 7 days", action="week"))
    buttons.add_element(card.create_button("year", label="This year", action="year"))
    card.add_element(table)
    card.add_element(graph)
    await show(haa.get_variable("view", "week"))


@action(description="Show the last seven days, day by day")
async def week(event: ActionEvent) -> int:
    return await show("week")


@action(description="Show this year, month by month")
async def year(event: ActionEvent) -> int:
    return await show("year")


@on_interval("01:00:00")
async def hourly(event: IntervalEvent) -> None:
    """Home Assistant adds an hour of statistics every hour: read them again."""
    await show(haa.get_variable("view", "week"))
