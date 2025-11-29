"""Event-based automation example.

This script demonstrates event triggers with HAAnim.
Copy this file to your config/haanim/ folder to use it.

Note: Variables like 'hass', 'state', 'log', and 'event' are provided
by the HAAnim runtime and are available in all script functions.
"""

from haanim import event_trigger, scene, state_trigger


@event_trigger("zha_event")
@scene("Handle ZHA Button Press")
def handle_zha_button(event_data: dict):
    """Handle Zigbee button events.

    This responds to ZHA (Zigbee Home Automation) events,
    typically from button presses or device actions.

    Args:
        event_data: Event data containing device_id, command, etc.
    """
    device_id = event_data.get("device_id")
    command = event_data.get("command")

    log.info(f"ZHA event: device={device_id}, command={command}")

    # Handle specific button commands
    if command == "on":
        hass.call_service("light", "turn_on", entity_id="light.living_room")
    elif command == "off":
        hass.call_service("light", "turn_off", entity_id="light.living_room")
    elif command == "move_with_on_off":
        # Brightness up
        hass.call_service(
            "light",
            "turn_on",
            entity_id="light.living_room",
            brightness_step=25,
        )
    elif command == "move":
        # Brightness down
        hass.call_service(
            "light",
            "turn_on",
            entity_id="light.living_room",
            brightness_step=-25,
        )


@event_trigger("mobile_app_notification_action")
@scene("Handle Mobile Notification Actions")
def handle_notification_action(event_data: dict):
    """Handle actions from mobile app notifications.

    When a user taps an action button on a notification,
    this function processes the response.

    Args:
        event_data: Contains action identifier and other data.
    """
    action = event_data.get("action")
    log.info(f"Notification action received: {action}")

    if action == "OPEN_GARAGE":
        hass.call_service("cover", "open_cover", entity_id="cover.garage_door")
        log.info("Opening garage door from notification")
    elif action == "DISMISS_ALERT":
        # Just acknowledge, no action needed
        log.info("Alert dismissed")
    elif action == "TURN_OFF_LIGHTS":
        hass.call_service("light", "turn_off", entity_id="all")
        log.info("All lights turned off from notification")


@state_trigger("binary_sensor.motion_backyard", new="on")
@scene("Motion Light Automation")
def backyard_motion():
    """Turn on backyard light when motion is detected.

    Automatically turns off after a delay.
    """
    # Turn on the light
    hass.call_service(
        "light",
        "turn_on",
        entity_id="light.backyard",
        brightness=255,
    )

    log.info("Backyard motion detected, light turned on")

    # Note: For auto-off functionality, you would typically use
    # Home Assistant's built-in timer or automation features.
    # HAAnim focuses on the trigger-action pattern.


@state_trigger("input_boolean.guest_mode", new="on")
@scene("Guest Mode Activated")
def guest_mode_on():
    """Configure house for guests when guest mode is enabled."""
    # Set comfortable temperature
    hass.call_service(
        "climate",
        "set_temperature",
        entity_id="climate.main_thermostat",
        temperature=72,
    )

    # Turn on ambient lighting
    hass.call_service(
        "light",
        "turn_on",
        entity_id="light.guest_room",
        brightness=200,
        color_temp_kelvin=3500,
    )

    # Send welcome message to smart speaker
    hass.call_service(
        "tts",
        "google_say",
        entity_id="media_player.living_room_speaker",
        message="Welcome! Guest mode has been activated.",
    )

    log.info("Guest mode activated")


@scene("Send Test Notification")
def send_test_notification():
    """Send a test notification with action buttons.

    Useful for testing the notification action handler.
    """
    hass.call_service(
        "notify",
        "mobile_app",
        title="Test Notification",
        message="This is a test notification with actions",
        data={
            "actions": [
                {
                    "action": "TURN_OFF_LIGHTS",
                    "title": "Turn Off Lights",
                },
                {
                    "action": "DISMISS_ALERT",
                    "title": "Dismiss",
                },
            ]
        },
    )

    log.info("Test notification sent")
