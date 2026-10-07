"""Hallway light that follows motion.

Motion turns the light on and it stays on while there is movement. When the
motion sensor has been off for the configured time, the light goes off again.
By day the light is left alone.
"""

from haanim import ActionEvent, ActionMode, StateEvent, action, haa, on_state

LIGHT = "light.hallway"
MOTION = "binary_sensor.hallway_motion"
DEFAULT_MINUTES = 5


def minutes() -> float:
    """How long the light stays on after the last movement."""
    return float(haa.get_variable("minutes", DEFAULT_MINUTES))


@on_state(f"{MOTION} == 'on'", start_time="sunset", end_time="sunrise")
@action(execution_mode=ActionMode.CANCEL, description="Turn the hallway light on until the motion ends")
async def light_on_motion(event: StateEvent) -> None:
    """Turn the light on, wait for the motion to end, then turn it off.

    New motion cancels the wait in progress and starts over (``CANCEL``), so
    the light never goes off while somebody is still walking around.
    """
    await haa.service.light.turn_on(entity_id=LIGHT, brightness=120)
    haa.set_message("Motion: light on")

    # First the sensor has to report "off", then stay that way
    await haa.wait_for(f"{MOTION} == 'off'")
    stayed_on = await haa.wait_for(f"{MOTION} == 'on'", timeout=minutes() * 60)
    if stayed_on:
        return  # motion again; the trigger has started a new run of this action

    await haa.service.light.turn_off(entity_id=LIGHT)
    haa.set_message("No motion: light off")


@action(description="Set how many minutes the light stays on after the last movement")
def set_minutes(event: ActionEvent) -> float:
    """Store the delay. Called with ``minutes=<number>``."""
    value = float(event.data.get("minutes", DEFAULT_MINUTES))
    if value <= 0:
        raise ValueError("minutes must be more than 0")
    haa.set_variable("minutes", value)
    return value
