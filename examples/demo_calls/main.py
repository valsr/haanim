"""Demo: the world outside the automation. Entities, services, other automations.

- **Entities** are read with ``haa.entity`` and ``haa.state()``: here the
  temperature and the fan.
- **Services** change them. An automation does not set an entity's state; it
  calls the service that does: ``input_number.set_value`` for the temperature
  setting, ``input_boolean.toggle`` for the fan.
- **Other automations** are called by their ID: ``notifications`` sends a
  message, and ``demo_basics`` counts on *its* card and returns the new count.

A state trigger puts the three together: when it gets warmer than 28 degrees
the automation turns the fan on and has a message sent.
"""

from haanim import (
    ActionEvent,
    NonExistingAutomationError,
    StateEvent,
    action,
    haa,
    on_state,
    startup,
)

TEMPERATURE = "sensor.temperature"
SETTING = "input_number.temperature"  # a Number helper; the sensor above is a template that follows it
FAN = "input_boolean.fan"  # a Toggle helper called "Fan"
WARM = 28

summary = haa.card.create_text("summary", "")
others = haa.card.create_text("others", "")
answer = haa.card.create_text("answer", "_Nothing called yet_")


def temperature() -> float | None:
    """The temperature as a number; None while the sensor has none."""
    state = haa.state(TEMPERATURE)
    try:
        return float(state) if state is not None else None
    except ValueError:
        return None


def show() -> None:
    """Say on the card what the automation reads from the entities, and which automations there are."""
    degrees = temperature()
    fan = haa.state(FAN) or "not there"
    reading = "unknown" if degrees is None else f"{degrees:g} °C"
    verdict = "warm" if degrees is not None and degrees > WARM else "fine"
    summary.set_text(f"The automation reads **{reading}** ({verdict}) and the fan **{fan}**.")
    lines = [f"- `{other.id}`: {other.state}" for other in haa.automations()]
    others.set_text("\n".join(sorted(lines)) or "_No automations_")


@startup
def build_card(event: ActionEvent) -> None:
    """Lay the card out."""
    card = haa.card
    layout = card.layout
    card.add_element(card.create_text("intro", "## Calls"))

    card.add_element(
        card.create_text("t_entities", "**Entities**, live on the card and read by the automation")
    )
    layout.split_row(2).add_element(card.create_entity("temperature", TEMPERATURE)).add_element(
        card.create_icon("fan", FAN, icon="mdi:fan", spin=True)
    )
    card.add_element(summary)

    card.add_element(card.create_text("t_services", "**Services** change entities"))
    services = layout.split_row(3)
    services.add_element(card.create_button("cooler", label="Cooler", action="change_temperature", by=-1))
    services.add_element(card.create_button("warmer", label="Warmer", action="change_temperature", by=1))
    services.add_element(card.create_button("toggle", label="Fan", action="toggle_fan"))

    card.add_element(card.create_text("t_others", "**Other automations**"))
    calls = layout.split_row(2)
    calls.add_element(card.create_button("notify", label="Send a message", action="notify"))
    calls.add_element(card.create_button("count", label="Count on Basics", action="count_there"))
    card.add_element(answer)
    card.add_element(others)
    card.add_element(card.create_button("refresh", label="Read again", action="refresh"))
    show()


@action(description="Read the entities and the automations again")
def refresh(event: ActionEvent) -> None:
    """Show what the entities say now."""
    show()


@action(description="Make it warmer or cooler by calling input_number.set_value")
async def change_temperature(event: ActionEvent) -> float:
    """Change the temperature setting by ``by`` degrees (1 if not given), through its service."""
    value = (temperature() or 20.0) + float(event.data.get("by", 1))
    call = await haa.service.input_number.set_value(entity_id=SETTING, value=value)
    # A service call that fails does not raise: its result says so
    haa.set_message(f"Set to {value:g} °C" if call.success else f"Could not set it: {call.error}")
    show()
    return value


@action(description="Turn the fan on or off by calling input_boolean.toggle")
async def toggle_fan(event: ActionEvent) -> None:
    """Toggle the fan through its service."""
    await haa.service.input_boolean.toggle(entity_id=FAN)
    haa.set_message("Fan toggled")
    show()


@action(description="Have the notifications automation send a message")
async def notify(event: ActionEvent) -> str:
    """Call ``send_message`` of the ``notifications`` automation, with data; it returns what it sent."""
    text = str(event.data.get("text", "Hello from the calls demo"))
    try:
        sent = await haa.automation("notifications").call("send_message", text=text, title="Demo: calls")
    except NonExistingAutomationError:
        answer.set_text("There is no `notifications` automation: copy it from the examples.")
        return ""
    answer.set_text(f"`notifications.send_message` returned **{sent}**")
    return str(sent)


@action(description="Run the count action of the basics demo, and show what it returns")
async def count_there(event: ActionEvent) -> int:
    """Call ``count`` of ``demo_basics`` with a step; its card counts, and this one shows the answer."""
    basics = haa.automation("demo_basics")
    if not basics.is_running():
        answer.set_text(f"`demo_basics` is {basics.state}: start it first.")
        return 0
    total = int(await basics.call("count", step=1))
    answer.set_text(f"`demo_basics.count` returned **{total}**")
    return total


@on_state(f"{TEMPERATURE} > {WARM}")
async def too_warm(event: ActionEvent) -> None:
    """When it gets warmer than 28 degrees: turn the fan on, and have a message sent."""
    await haa.service.input_boolean.turn_on(entity_id=FAN)
    degrees = event.new_state if isinstance(event, StateEvent) else haa.state(TEMPERATURE)
    await haa.call("notify", text=f"It is {degrees} °C: the fan is on")
    haa.set_message("Warm: fan turned on")
    show()
