"""Demo script showcasing all HAAnim features.

This example demonstrates:
- Action execution with different modes
- All trigger types (time, state, interval, cron, event)
- Constraints (keyword arguments of the trigger decorators)
- HAAnim API (haa instance) usage
- Persistent storage
- Service calls
- Script-to-script communication
- Lifecycle hooks (startup, shutdown)
"""

from haanim import (
    ActionMode,
    action,
    on_time,
    on_state,
    on_interval,
    on_cron,
    on_event,
    startup,
    shutdown,
    haa,
    log,
)

# =============================================================================
# Lifecycle Hooks
# =============================================================================


@startup
async def on_startup():
    """Run when script is loaded."""
    log.info("Demo script loaded!")

    # Initialize storage
    counter = haa.get_variable("counter", "0")
    log.info(f"Counter initialized at: {counter}")

    # Set script status
    haa.set_message("Demo script ready")


@shutdown
async def on_shutdown():
    """Run when script is unloaded."""
    log.info("Demo script unloading...")
    haa.set_message("Shutting down")


# =============================================================================
# Time-based Triggers
# =============================================================================


@action(name="Morning Routine", description="Activates morning scene")
@on_time("sunrise - 15 minutes")
async def morning_routine():
    """Morning automation."""
    log.info("Good morning!")

    # Turn on lights gradually
    await haa.service.light.turn_on(entity_id="light.bedroom", brightness=50, transition=60)

    # Update storage
    await haa.set_variable("last_morning", str(haa.id))


@on_time("sunset", when="binary_sensor.presence == 'on'")
async def evening_routine():
    """Evening automation - only when someone is home."""
    log.info("Evening routine starting")

    await haa.service.light.turn_on(entity_id="light.living_room", brightness=200)


# =============================================================================
# State-based Triggers
# =============================================================================


@on_state("sensor.temperature > 25")
async def temperature_high(event):
    """Triggered when temperature exceeds 25°C."""
    temp = event.new_state.state
    log.warning(f"Temperature is high: {temp}°C")

    # Turn on AC
    await haa.service.climate.set_temperature(entity_id="climate.ac", temperature=22)


@on_state("binary_sensor.motion == 'on'", start_time="sunset", end_time="sunrise")  # Only at night
async def motion_at_night(event):
    """Motion detected at night."""
    log.info(f"Motion detected in {event.entity_id}")

    # Turn on lights
    await haa.service.light.turn_on(entity_id="light.hallway")


# =============================================================================
# Interval Triggers
# =============================================================================


@on_interval("00:05:00")  # Every 5 minutes
async def periodic_check():
    """Regular status check."""
    # Increment counter
    counter = int(haa.get_variable("counter", "0"))
    counter += 1
    await haa.set_variable("counter", str(counter))

    log.info(f"Periodic check #{counter}")

    # Check entities
    temp = haa.entity.sensor.temperature
    humidity = haa.entity.sensor.humidity
    log.debug(f"Temp: {temp}°C, Humidity: {humidity}%")


# =============================================================================
# Cron Triggers
# =============================================================================


@on_cron("0 */2 * * *")  # Every 2 hours
async def hourly_cleanup():
    """Clean up old data every 2 hours."""
    log.info("Running cleanup task")

    # Clear old storage values
    old_runs = int(haa.get_variable("cleanup_runs", "0"))
    await haa.set_variable("cleanup_runs", str(old_runs + 1))


# =============================================================================
# Event Triggers
# =============================================================================


@on_event("custom_event", data={"source": "automation"})
async def handle_custom_event(event):
    """Handle custom Home Assistant events."""
    log.info(f"Received custom event: {event.event_data}")


# =============================================================================
# Action Execution Modes
# =============================================================================


@action(name="Quick Action", execution_mode=ActionMode.DROP)
async def quick_action():
    """Drop new executions if already running."""
    log.info("Quick action started")
    await haa.service.script.turn_on(entity_id="script.quick_task")


@action(name="Queued Task", execution_mode=ActionMode.QUEUE)
async def queued_task():
    """Queue up to 10 executions."""
    log.info("Processing queued task")
    # Simulate work
    import asyncio

    await asyncio.sleep(2)
    log.info("Queued task complete")


@action(name="Emergency Stop", execution_mode=ActionMode.CANCEL)
async def emergency_stop():
    """Cancel current execution and start new one."""
    log.warning("EMERGENCY STOP ACTIVATED")

    # Turn off all lights
    await haa.service.light.turn_off(entity_id="all")

    # Stop other scripts
    for script in haa.scripts():
        if script.id != haa.id and script.is_running():
            await script.stop()


# =============================================================================
# Script-to-Script Communication
# =============================================================================


@action(name="Call Other Script")
async def call_other_script():
    """Demonstrate calling another script."""
    # Get reference to another script
    other_script = haa.script("other_demo")

    if other_script.is_enabled():
        # Call an action in the other script
        result = await other_script.call("some_action", param1="value")
        log.info(f"Other script returned: {result}")
    else:
        log.warning("Other script is disabled")


# =============================================================================
# Entity Access & Service Calls
# =============================================================================


@action(name="Entity Demo")
async def entity_demo():
    """Demonstrate entity access."""
    # Read entity states
    temp = haa.entity.sensor.temperature
    motion = haa.entity.binary_sensor.motion
    light_state = haa.state("light.living_room")

    log.info(f"Temperature: {temp}")
    log.info(f"Motion: {motion}")
    log.info(f"Light state: {light_state}")

    # Conditional logic based on state
    if temp > 23:
        await haa.service.climate.turn_on(entity_id="climate.ac")


@action(name="Service Demo")
async def service_demo():
    """Demonstrate service calls."""
    # Call service with parameters
    result = await haa.service.light.turn_on(entity_id="light.bedroom", brightness=255, rgb_color=[255, 0, 0])

    if result.success:
        log.info("Light turned on successfully")
        if result.response_data:
            log.debug(f"Service response: {result.response_data}")
    else:
        log.error(f"Failed to turn on light: {result.error}")


# =============================================================================
# Storage Demo
# =============================================================================


@action(name="Storage Demo")
async def storage_demo():
    """Demonstrate persistent storage."""
    # Store values
    await haa.set_variable("last_run", "2026-01-04 13:00:00")
    await haa.set_variable("run_count", "42")

    # Retrieve values
    last_run = haa.get_variable("last_run", "never")
    run_count = haa.get_variable("run_count", "0")

    log.info(f"Last run: {last_run}, Count: {run_count}")

    # Remove a value
    await haa.unset_variable("temp_value")

    # Clear all (be careful!)
    # await haa.clear_variables()


# =============================================================================
# Manual Actions (UI only)
# =============================================================================


@action(name="Test Button", description="A simple test action for UI")
async def test_button():
    """Manual action for testing."""
    log.info("Test button pressed!")
    haa.set_message("Test executed")

    # Do something simple
    await haa.service.notify.persistent_notification(message="Test action executed", title="HAAnim Demo")
