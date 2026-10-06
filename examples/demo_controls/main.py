"""Demo: the controls that show a state. Values, entities, icons, gauges and badges.

Each of them shows either something the automation sets, or the state of an
entity, which it then follows by itself:

- a value and an entity: a label with what it is worth;
- icons: lit and turning while their entity is active, or exactly what the automation says;
- gauges: a number within a range, as a progress bar or as a dial;
- badges: a short text in a coloured pill.

"Work" moves the progress bar a step, and the bar and the badge change
colour with it. "Fan" toggles the fan, and everything that follows the fan
changes without the automation doing anything.
"""

from haanim import ActionEvent, action, haa, startup

TEMPERATURE = "sensor.temperature"
FAN = "input_boolean.fan"  # a Toggle helper called "Fan"; any entity that is on or off will do
SUN = "sun.sun"

steps = haa.card.create_value("steps", label="Steps done", value=0, unit="of 10")
progress = haa.card.create_gauge("progress", 0, max=10, label="Progress")
status = haa.card.create_badge("status", "Not started", color="disabled")


def show(done: int) -> None:
    """Show how far the work is: the value, the bar and the badge, each in its own way."""
    steps.set_value(done)
    progress.set_value(done)
    # There are no thresholds: the automation sets the colour that fits the value
    progress.set_color("success" if done >= 10 else "warning" if done >= 7 else None)
    if done >= 10:
        status.set_text("Done")
        status.set_icon("mdi:check")
        status.set_color("success")
    elif done:
        status.set_text("Working")
        status.set_icon("mdi:progress-wrench")
        status.set_color("primary")
    else:
        status.set_text("Not started")
        status.set_icon(None)
        status.set_color("disabled")


@startup
def build_card(event: ActionEvent) -> None:
    """Lay the card out."""
    card = haa.card
    layout = card.layout
    card.add_element(card.create_text("intro", "## Controls"))

    card.add_element(card.create_text("t_values", "**Values and entities**"))
    card.add_element(steps)
    card.add_element(card.create_entity("temperature", TEMPERATURE))

    card.add_element(card.create_text("t_icons", "**Icons**: following an entity, or fixed"))
    icons = layout.split_row(3)
    icons.add_element(card.create_icon("fan", FAN, icon="mdi:fan", spin=True))
    icons.add_element(card.create_icon("sun", SUN))  # the entity's own icon
    icons.add_element(
        card.create_icon("info", icon="mdi:information-outline", label="No entity", color="accent")
    )

    card.add_element(card.create_text("t_gauges", "**Gauges**: a bar and two dials"))
    card.add_element(progress)
    dials = layout.split_row(2)
    dials.add_element(card.create_gauge("dial", entity_id=TEMPERATURE, min=10, max=35, kind="dial"))
    dials.add_element(
        card.create_gauge("load", 62, unit="%", label="Fixed value", kind="dial", color="warning")
    )

    card.add_element(card.create_text("t_badges", "**Badges**"))
    badges = layout.split_row(3)
    badges.add_element(status)
    badges.add_element(card.create_badge("fan_state", entity_id=FAN, icon="mdi:fan", color="accent"))
    badges.add_element(card.create_badge("plain", "Plain"))

    buttons = layout.split_row(3)
    buttons.add_element(card.create_button("work", label="Work", action="work"))
    buttons.add_element(card.create_button("again", label="Start over", action="start_over"))
    buttons.add_element(card.create_button("toggle", label="Fan", action="toggle_fan"))
    show(int(haa.get_variable("done", 0)))


@action(description="Do a step of the work")
def work(event: ActionEvent) -> int:
    """Move the progress on by ``steps`` (1 if not given), up to ten."""
    done = min(10, int(haa.get_variable("done", 0)) + int(event.data.get("steps", 1)))
    haa.set_variable("done", done)
    show(done)
    return done


@action(description="Set the progress back to nothing")
def start_over(event: ActionEvent) -> None:
    """Forget the work done."""
    haa.set_variable("done", 0)
    show(0)


@action(description="Turn the fan on or off")
async def toggle_fan(event: ActionEvent) -> None:
    """Toggle the fan. The icon and the badge that follow it change by themselves."""
    await haa.service.input_boolean.toggle(entity_id=FAN)
