"""Time-based automation example.

This script demonstrates time-based triggers and scenes with HAAnim.
Copy this file to your config/haanim/ folder to use it.
"""

from haanim import scene, state_active, time_active, time_trigger


@scene("Good Morning")
def morning_routine():
    """Activate morning scene with gradual wake-up lights.

    This scene can be triggered manually or set up with a time trigger.
    """
    # Gradually turn on bedroom lights
    hass.call_service(
        "light",
        "turn_on",
        entity_id="light.bedroom",
        brightness=100,
        transition=30,  # 30 second transition
        color_temp_kelvin=4500,  # Neutral white
    )

    # Turn on kitchen lights
    hass.call_service(
        "light",
        "turn_on",
        entity_id="light.kitchen",
        brightness=200,
    )

    # Start coffee maker if available
    if state.get("switch.coffee_maker").state == "off":
        hass.call_service("switch", "turn_on", entity_id="switch.coffee_maker")

    log.info("Morning routine activated")


@scene("Good Night")
def night_routine():
    """Prepare house for sleep.

    Turns off most lights and sets up night mode.
    """
    # Turn off all lights except night light
    hass.call_service("light", "turn_off", entity_id="all")

    # Turn on dim night light
    hass.call_service(
        "light",
        "turn_on",
        entity_id="light.hallway_night_light",
        brightness=25,
        color_temp_kelvin=2700,  # Warm
    )

    # Lock all doors
    hass.call_service("lock", "lock", entity_id="all")

    # Arm security system
    hass.call_service(
        "alarm_control_panel",
        "alarm_arm_night",
        entity_id="alarm_control_panel.home_alarm",
    )

    log.info("Good night routine activated")


@time_trigger("07:00")
@time_active("mon,tue,wed,thu,fri")  # Only on weekdays
@state_active("binary_sensor.someone_home", "on")  # Only if someone is home
@scene("Weekday Morning Wake-Up")
def weekday_wakeup():
    """Automatic wake-up on weekday mornings.

    Uses multiple constraints:
    - Only triggers at 7:00 AM
    - Only on weekdays (Mon-Fri)
    - Only when someone is home

    Note: This function is called automatically by the trigger,
    but the morning_routine scene can also be triggered manually
    at any time from the panel.
    """
    log.info("Triggering weekday morning routine")
    morning_routine()


@time_trigger("22:30")
@scene("Auto Night Mode")
def auto_night_mode():
    """Automatically activate night mode at 10:30 PM.

    This checks if anyone is still active before activating.
    """
    # Check if TV is on (someone might be watching)
    tv_state = state.get("media_player.living_room_tv")
    if tv_state.state == "playing":
        log.info("TV is on, skipping auto night mode")
        return

    # Check for motion in last 30 minutes
    motion_state = state.get("binary_sensor.living_room_motion")
    if motion_state.state == "on":
        log.info("Motion detected, delaying night mode")
        # Could schedule for later using Home Assistant automation
        return

    log.info("Activating night mode")
    night_routine()


@scene("Movie Mode")
def movie_mode():
    """Set up perfect movie watching ambiance.

    Dims lights and sets TV to optimal settings.
    """
    # Dim living room lights
    hass.call_service(
        "light",
        "turn_on",
        entity_id="light.living_room",
        brightness=30,
        color_temp_kelvin=2700,
    )

    # Turn on bias lighting behind TV if available
    if state.get("light.tv_bias_light").state != "unavailable":
        hass.call_service(
            "light",
            "turn_on",
            entity_id="light.tv_bias_light",
            brightness=50,
            rgb_color=[255, 180, 100],
        )

    # Turn off other distracting lights
    hass.call_service("light", "turn_off", entity_id="light.ceiling_fan_light")

    log.info("Movie mode activated")
