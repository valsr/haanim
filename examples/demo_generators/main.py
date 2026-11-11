"""Demo: generators and async generators.

Generators work as in Python:

- ``wave()`` makes up a day of readings, one an hour. It is a generator: a
  reading is computed only when something asks for the next one.
- ``moving_average()`` takes any iterable and yields the average of the last
  few values, so generators chain into a pipeline.
- ``days()`` hands on the readings of several days with ``yield from``.
- ``sum``, ``max`` and generator expressions summarise the readings without a list.

``every_second()`` is an async generator: it awaits ``haa.sleep(1)`` between
readings of ``sensor.temperature``, and Home Assistant runs everything else
meanwhile. **Watch** consumes it with ``async for``; **Stop** makes that loop
``break``, after which the generator is closed with ``aclose()`` so its
``finally`` runs at once.
"""

import math

from haanim import ActionEvent, ActionMode, UnitOfTemperature, action, haa, startup

SENSOR = "sensor.temperature"
CELSIUS = UnitOfTemperature.CELSIUS
WARM = 20

watching = {"stop": False}
live = haa.card.create_value("live", label="Watching", value="-", unit=CELSIUS)


# --- Generators ---------------------------------------------------------------------


def wave(hours: int):
    """A made-up reading for each hour: cool at night, warm in the afternoon."""
    for hour in range(hours):
        yield round(18 + 4 * math.sin((hour % 24 - 9) * math.pi / 12), 1)


def moving_average(values, size: int):
    """The average of the last ``size`` values, for each value."""
    window: list[float] = []
    for value in values:
        window = [*window, value][-size:]
        yield round(sum(window) / len(window), 1)


def days(count: int):
    """The readings of ``count`` days, one day after the other."""
    for _ in range(count):
        yield from wave(24)


def day_table() -> list[list[object]]:
    """Hour, reading and three-hour average, from three generators walked side by side."""
    return [
        [f"{hour:02d}:00", reading, average]
        for hour, reading, average in zip(range(24), wave(24), moving_average(wave(24), 3))
    ]


def summary() -> str:
    """Summaries computed straight from generators: no list of readings is ever built."""
    peak = max(wave(24))
    warm = sum(1 for reading in wave(24) if reading > WARM)
    week = sum(days(7)) / (7 * 24)
    return f"Peak **{peak:g} °C**, warm for **{warm}** hours, mean over a week **{week:.1f} °C**."


# --- An async generator -------------------------------------------------------------


def temperature() -> float | None:
    """The temperature as a number; None while the sensor has none."""
    try:
        return float(haa.state(SENSOR))
    except (TypeError, ValueError):
        return None


async def every_second(seconds: int):
    """Read the temperature once a second; the event loop is free while it sleeps."""
    taken = 0
    try:
        for _ in range(seconds):
            await haa.sleep(1)
            taken += 1
            yield temperature()
    finally:
        haa.set_message(f"Watched for {taken} s")


@action(execution_mode=ActionMode.DROP, description="Read the temperature every second for a while")
async def watch(event: ActionEvent) -> list[float | None]:
    """Show each reading as it comes; stop early when Stop is pressed."""
    watching["stop"] = False
    readings = every_second(int(event.data.get("seconds", 10)))
    seen = []
    try:
        async for degrees in readings:
            live.set_value("-" if degrees is None else degrees)
            seen.append(degrees)
            if watching["stop"]:
                break
    finally:
        # As in Python, a loop that breaks leaves the generator open; close it so its finally runs now
        await readings.aclose()
    return seen


@action(description="Stop watching after the next reading")
def stop(event: ActionEvent) -> None:
    watching["stop"] = True


@startup
def build_card(event: ActionEvent) -> None:
    """Lay the card out."""
    card = haa.card
    card.add_element(card.create_text("intro", "## Generators\nA made-up day, computed lazily."))
    card.add_element(card.create_text("summary", summary()))
    card.add_element(
        card.create_table(
            "day",
            columns=["Hour", "Reading", "3-hour average"],
            units=["", CELSIUS, CELSIUS],
            rows=day_table(),
            title="One reading an hour",
        )
    )
    card.add_element(live)
    buttons = card.layout.split_row(2)
    buttons.add_element(card.create_button("watch", label="Watch for 10 s", action="watch"))
    buttons.add_element(card.create_button("stop", label="Stop", action="stop"))
