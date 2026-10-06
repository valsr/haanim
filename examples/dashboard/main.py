"""A card that shows everything `haa.card` can do.

The card has a title that changes with what the automation does, a heading, a
logo from the automation's assets, a counter that is kept across restarts, the
live state of an entity, icons that follow entities, and three buttons, one of which strips the card to a
bare box and back. Add it to a
dashboard with::

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
FAN = "input_boolean.fan"  # a Toggle helper called "Fan"; any entity that is on or off will do


def show_count() -> int:
    """Put the stored count on the card and in its title, and return it."""
    count = int(haa.get_variable("count", 0))
    haa.card.value("count", label="Button presses", value=count)
    # The title of the card follows the count
    haa.card.set_title(f"Dashboard demo: {count} pressed" if count else "Dashboard demo")
    return count


@startup
def build_card(event: ActionEvent) -> None:
    """Build the card. Card content is not kept across restarts, so it is built here."""
    haa.card.text("intro", "## Dashboard demo\nA card filled by an automation with **`haa.card`**.")
    haa.card.image("logo", asset="logo.svg", alt="HAAnim logo")
    show_count()
    haa.card.value("uptime", label="Running for", value=0, unit="min")
    haa.card.entity("sun", ENTITY)
    # Icons follow their entity: lit and turning while the fan is on, dimmed while it is off
    haa.card.icon("fan", FAN, icon="mdi:fan", spin=True)
    haa.card.icon("sun_icon", ENTITY)  # the entity's own icon, which changes with its state
    haa.card.icon("info", icon="mdi:information-outline", label="An icon no entity drives", color="accent")
    haa.card.button("add", label="Count", action="count", step=1)
    haa.card.button("reset", label="Reset", action="reset", confirm="Reset the counter to zero?")
    haa.card.button("frame", label="Bare card on/off", action="toggle_frame")
    haa.set_message("Card ready")


@action(description="Add to the counter on the card")
def count(event: ActionEvent) -> int:
    """Add ``step`` (1 if not given) to the counter and show it."""
    haa.set_variable("count", int(haa.get_variable("count", 0)) + int(event.data.get("step", 1)))
    total = show_count()
    print(f"Counted to {total}")
    return total


@action(description="Set the counter on the card back to zero")
def reset(event: ActionEvent) -> int:
    """Set the counter to zero and show it."""
    haa.set_variable("count", 0)
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
    haa.card.value("uptime", label="Running for", value=event.execution_count, unit="min")


@on_event("dashboard_count")
@action(execution_mode=ActionMode.QUEUE, description="Count a dashboard_count event")
def count_event(event: EventTriggerEvent) -> None:
    """Count a `dashboard_count` event; its data may carry a `step`.

    Events that arrive while one is being counted wait their turn (``QUEUE``);
    with the default mode, ``DROP``, they would be lost.
    """
    haa.set_variable("count", int(haa.get_variable("count", 0)) + int(event.event_data.get("step", 1)))
    show_count()


@on_cron("0 0 * * *")
def midnight(event: CronEvent) -> None:
    """Start a new day at zero."""
    haa.set_variable("count", 0)
    show_count()
    haa.set_message("New day: counter reset")
