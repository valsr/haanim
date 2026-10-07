"""Demo: the basics of a card. Text, a value, buttons, and the actions behind them.

The card has a heading, a counter that is kept across restarts, a line that
says what happened last, and a row of buttons. Each button runs an action;
two of them pass data to it, one asks before it runs, and one strips the card
of everything that is not the automation's own content. The title and the
status message follow the count. Add it to a dashboard with::

    type: custom:haanim-card
    automation_id: demo_basics

The counter also counts every ``demo_count`` event (fire one from Developer
tools, with ``step`` in its data if you like), and starts again from zero
every midnight.
"""

from haanim import (
    ActionEvent,
    ActionMode,
    CronEvent,
    EventTriggerEvent,
    action,
    haa,
    on_cron,
    on_event,
    startup,
)

# Elements are created once and changed in place afterwards. They are created here, each time the
# automation starts, and put on the card in build_card.
counter = haa.card.create_value("count", label="Button presses", value=0)
last = haa.card.create_text("last", "_Nothing pressed yet_")


def show_count(what: str | None = None) -> int:
    """Put the stored count on the card and in its title, and return it."""
    count = int(haa.get_variable("count", 0))
    counter.set_value(count)
    if what is not None:
        last.set_text(f"Last: **{what}** at {haa.now().strftime('%H:%M:%S')}")
    # The title of the card follows the count
    haa.card.set_title(f"Basics: {count} pressed" if count else "Basics demo")
    return count


@startup
def build_card(event: ActionEvent) -> None:
    """Lay the card out. Card content is not kept across restarts, so it is built here."""
    card = haa.card
    card.add_element(
        card.create_text("intro", "## Basics\nText is **markdown**. The buttons below run actions.")
    )
    card.add_element(counter)
    card.add_element(last)

    # Buttons name actions, so they are created once the actions exist: in @startup, not above.
    # Keyword arguments of a button are the data of the call: here the step.
    buttons = card.layout.split_row(4)
    buttons.add_element(card.create_button("add", label="Count", action="count", step=1))
    buttons.add_element(card.create_button("add5", label="+5", action="count", step=5))
    buttons.add_element(
        card.create_button("reset", label="Reset", action="reset", confirm="Reset the counter to zero?")
    )
    buttons.add_element(card.create_button("frame", label="Bare card", action="toggle_frame"))

    show_count()
    haa.set_message("Card ready")


@action(description="Add to the counter on the card")
def count(event: ActionEvent) -> int:
    """Add ``step`` (1 if not given) to the counter, show it, and return the new count to the caller."""
    step = int(event.data.get("step", 1))
    haa.set_variable("count", int(haa.get_variable("count", 0)) + step)
    total = show_count(f"counted {step}")
    haa.set_message(f"Counted to {total}")
    print(f"Counted to {total}")
    return total


@action(description="Set the counter on the card back to zero")
def reset(event: ActionEvent) -> int:
    """Set the counter to zero and show it."""
    haa.set_variable("count", 0)
    haa.set_message("Counter reset")
    return show_count("reset")


@action(description="Hide or show everything on the card that is not the automation's own content")
def toggle_frame(event: ActionEvent) -> bool:
    """Strip the card to a bare box, or bring its title, state, message and buttons back."""
    show = not haa.card.options["title"]
    haa.card.configure(title=show, state=show, message=show, actions=show, log=show)
    return show


@on_event("demo_count")
@action(execution_mode=ActionMode.QUEUE, description="Count a demo_count event")
def count_event(event: ActionEvent) -> None:
    """Count a `demo_count` event; its data may carry a `step`.

    Events that arrive while one is being counted wait their turn (``QUEUE``);
    with the default mode, ``DROP``, they would be lost. Run by hand, the step
    comes from the data of the call instead.
    """
    data = event.event_data if isinstance(event, EventTriggerEvent) else event.data
    haa.set_variable("count", int(haa.get_variable("count", 0)) + int(data.get("step", 1)))
    show_count("an event")


@on_cron("0 0 * * *")
def midnight(event: CronEvent) -> None:
    """Start a new day at zero."""
    haa.set_variable("count", 0)
    show_count("a new day")
    haa.set_message("New day: counter reset")
