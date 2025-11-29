"""Basic HAAnim automation example.

This script demonstrates basic automation patterns with HAAnim.
Copy this file to your config/haanim/ folder to use it.
"""

from haanim import scene, state_trigger


@scene("Toggle Living Room Lights")
def toggle_living_room():
    """Toggle the living room lights on or off.

    This action can be triggered manually from the HAAnim panel
    or via the haanim.run_action service.
    """
    # Get current state
    current_state = state.get("light.living_room")

    if current_state.state == "on":
        # Turn off the light
        hass.call_service("light", "turn_off", entity_id="light.living_room")
        log.info("Living room lights turned off")
    else:
        # Turn on the light with warm white
        hass.call_service(
            "light",
            "turn_on",
            entity_id="light.living_room",
            brightness=255,
            color_temp_kelvin=3000,
        )
        log.info("Living room lights turned on")


@state_trigger("binary_sensor.front_door", new="on")
@scene("Front Door Alert")
def front_door_opened():
    """Send notification when front door opens.

    This automation triggers automatically when the front door
    sensor changes to 'on' state.
    """
    # Get time to customize message
    import datetime

    now = datetime.datetime.now()
    time_str = now.strftime("%H:%M")

    # Send notification
    hass.call_service(
        "notify",
        "mobile_app",
        title="Door Alert",
        message=f"Front door opened at {time_str}",
    )

    log.info("Front door notification sent")


@scene("Set Brightness")
def set_brightness(level: int = 128):
    """Set living room brightness to a specific level.

    Args:
        level: Brightness level from 0-255. Defaults to 128.
    """
    hass.call_service(
        "light",
        "turn_on",
        entity_id="light.living_room",
        brightness=level,
    )
    log.info(f"Set brightness to {level}")
