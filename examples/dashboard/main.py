"""A card that shows everything `haa.card` can do.

Elements are created with ``haa.card.create_*()``, placed with the layout, and
changed in place with their setters. The card has a title that changes with
what the automation does, a heading, a logo from the automation's assets, a
counter that is kept across restarts next to an uptime, a progress bar towards
a goal next to a dial that follows an entity, a row of badges, two graphs
(numbers the automation keeps itself, and the history of entities), the live
state of an entity, the live picture of a camera, a row of icons that follow entities, and a row of three buttons, one of
which strips the card to a bare box and back. Add it to a dashboard with::

    type: custom:haanim-card
    automation_id: dashboard

The counter also counts every ``dashboard_count`` event (fire one from
Developer tools, with ``step`` in its data if you like), and starts again from
zero every midnight.
"""

from haanim import (
    ActionEvent,
    ActionMode,
    CronEvent,
    EventTriggerEvent,
    IntervalEvent,
    action,
    haa,
    on_cron,
    on_event,
    on_interval,
    startup,
)

ENTITY = "sun.sun"
TEMPERATURE = "sensor.temperature"
HISTORY = 20
GOAL = 10  # the progress bar is full at this many presses
CAMERA = "camera.demo"  # any camera; while there is none, the card shows the image's alt text
FAN = "input_boolean.fan"  # a Toggle helper called "Fan"; any entity that is on or off will do


# Elements are created once and changed in place afterwards. They are created here, each time the
# automation starts, and put on the card in build_card.
counter = haa.card.create_value("count", label="Button presses", value=0)
running = haa.card.create_value("uptime", label="Running for", value=0, unit="min")
# A gauge shows a number within a range: here as a progress bar, how far the count is towards the goal
progress = haa.card.create_gauge("goal", 0, max=GOAL, label=f"Towards {GOAL} presses")
# A badge is a short text in a coloured pill
level = haa.card.create_badge("level", "Not started", color="disabled")
# A graph of the automation's own numbers: the count after each of the last changes
presses = haa.card.create_graph("presses", series={"Count": []}, kind="bar", title="Recent counts")


def show_count() -> int:
    """Put the stored count on the card and in its title, and return it."""
    count = int(haa.get_variable("count", 0))
    counter.set_value(count)
    progress.set_value(count)
    if count >= GOAL:
        level.set_text("Goal reached")
        level.set_icon("mdi:trophy")
        level.set_color("success")
    else:
        level.set_text("Counting" if count else "Not started")
        level.set_icon(None)
        level.set_color("primary" if count else "disabled")
    presses.set_series({"Count": haa.get_variable("history", [])})
    # The title of the card follows the count
    haa.card.set_title(f"Dashboard demo: {count} pressed" if count else "Dashboard demo")
    return count


def remember(count: int) -> None:
    """Store the count, and keep the last twenty for the graph."""
    haa.set_variable("count", count)
    haa.set_variable("history", [*haa.get_variable("history", []), count][-HISTORY:])


@startup
def build_card(event: ActionEvent) -> None:
    """Lay the card out. Card content is not kept across restarts, so it is built here."""
    card = haa.card
    layout = card.layout

    # An element added to the card, or to the layout, gets a row of its own
    card.add_element(
        card.create_text("intro", "## Dashboard demo\nA card filled by an automation with **`haa.card`**.")
    )
    # An image can be given a size, a place in its row and a caption
    layout.add_element(
        card.create_image(
            "logo", asset="logo.svg", alt="HAAnim logo", width=96, align="center", caption="Drawn by the card"
        )
    )

    # A row split into cells puts elements side by side
    layout.split_row(2).add_element(counter).add_element(running)

    # Gauges: the automation's own number as a progress bar, and an entity's state on a dial
    gauges = layout.split_row(2)
    gauges.add_element(progress)
    gauges.add_element(card.create_gauge("dial", entity_id=TEMPERATURE, min=10, max=35, kind="dial"))

    # Badges: one the automation sets, and one that shows the state of an entity
    badges = layout.split_row(3)
    badges.add_element(level)
    badges.add_element(card.create_badge("fan_state", entity_id=FAN, icon="mdi:fan", color="accent"))

    layout.add_element(presses)
    layout.add_element(card.create_entity("sun", ENTITY))

    # The live picture of a camera, fetched again every five seconds; a click opens the camera's dialog
    layout.add_element(
        card.create_image(
            "camera", entity_id=CAMERA, refresh=5, alt="No camera", width="100%", caption="camera.demo, live"
        )
    )

    # A graph of what Home Assistant recorded for entities; it follows them from then on. The
    # temperature is numbers and is drawn as an area; the fan is on or off and becomes a timeline.
    # Hover over it to read a single value. The time axis is labelled every quarter of an hour, with a
    # small mark every five minutes; without x_major and x_minor the card picks round distances itself.
    layout.add_element(
        card.create_graph(
            "temperature",
            [TEMPERATURE, FAN],
            hours=1,
            kind="area",
            title="Temperature and fan, last hour",
            x_major="00:15:00",
            x_minor="00:05:00",
        )
    )

    # Icons follow their entity: lit and turning while the fan is on, dimmed while it is off
    icons = layout.split_row(3)
    icons.add_element(card.create_icon("fan", FAN, icon="mdi:fan", spin=True))
    icons.add_element(card.create_icon("sun_icon", ENTITY))  # the entity's own icon
    icons.add_element(
        card.create_icon("info", icon="mdi:information-outline", label="No entity", color="accent")
    )

    # Buttons name actions, so they are created once the actions exist: in @startup, not above
    buttons = layout.split_row(3)
    buttons.add_element(card.create_button("add", label="Count", action="count", step=1))
    buttons.add_element(
        card.create_button("reset", label="Reset", action="reset", confirm="Reset the counter to zero?")
    )
    buttons.add_element(card.create_button("frame", label="Bare card", action="toggle_frame"))

    show_count()
    haa.set_message("Card ready")


@action(description="Add to the counter on the card")
def count(event: ActionEvent) -> int:
    """Add ``step`` (1 if not given) to the counter and show it."""
    remember(int(haa.get_variable("count", 0)) + int(event.data.get("step", 1)))
    total = show_count()
    print(f"Counted to {total}")
    return total


@action(description="Set the counter on the card back to zero")
def reset(event: ActionEvent) -> int:
    """Set the counter to zero and show it."""
    remember(0)
    haa.set_message("Counter reset")
    return show_count()


@action(description="Hide or show everything on the card that is not the automation's own content")
def toggle_frame(event: ActionEvent) -> bool:
    """Strip the card to a bare box, or bring its title, state, message and buttons back."""
    show = not haa.card.options["title"]
    haa.card.configure(title=show, state=show, message=show, actions=show, log=show)
    return show


@on_interval("00:01:00")
def uptime(event: IntervalEvent) -> None:
    """Show for how long the automation has been running."""
    running.set_value(event.execution_count)


@on_event("dashboard_count")
@action(execution_mode=ActionMode.QUEUE, description="Count a dashboard_count event")
def count_event(event: EventTriggerEvent) -> None:
    """Count a `dashboard_count` event; its data may carry a `step`.

    Events that arrive while one is being counted wait their turn (``QUEUE``);
    with the default mode, ``DROP``, they would be lost.
    """
    remember(int(haa.get_variable("count", 0)) + int(event.event_data.get("step", 1)))
    show_count()


@on_cron("0 0 * * *")
def midnight(event: CronEvent) -> None:
    """Start a new day at zero."""
    remember(0)
    show_count()
    haa.set_message("New day: counter reset")
