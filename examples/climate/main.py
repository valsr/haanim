from haanim import HAAnim, ActionEvent, TimeEvent, StateEvent, IntervalEvent
from haanim import action, on_time, on_state, on_interval, startup, shutdown
from haanim import ActionMode, ActionTimeOutError
from haanim import haa

# Module-level state
alert_count = 0


@startup
def initialize(event: ActionEvent):
    """Initialize automation."""
    global alert_count
    alert_count = haa.get_variable("alert_count", 0)
    threshold = haa.get_variable("threshold", 25.0)
    print(f"Initialized: {alert_count} alerts, threshold {threshold}°C")


@on_time("09:00", day_of_week="weekdays", when="person.john == 'home'")
async def morning_routine(event: TimeEvent):
    """Morning routine on weekdays when home."""
    haa.set_message("Starting morning routine")

    await haa.service.light.turn_on(entity_id="light.bedroom", brightness=150)

    temp = float(haa.entity.sensor.outdoor_temp)
    await haa.service.notify.mobile_app(message=f"Good morning! Temperature: {temp}°C")

    haa.set_message("Morning routine completed")


@on_state("sensor.temperature > 30")
async def high_temperature_alert(event: StateEvent):
    """Alert on high temperature."""
    global alert_count

    alert_count += 1
    haa.set_variable("alert_count", alert_count)

    temp = float(haa.entity.sensor.temperature)
    await haa.service.notify.mobile_app(message=f"High temperature: {temp}°C (Alert #{alert_count})")


@action(execution_mode=ActionMode.DROP, timeout=60)
async def send_notification(event: ActionEvent):
    """Send notification; a request made while one is in progress is dropped."""
    try:
        await haa.automation("notifications").call("send_message")
    except ActionTimeOutError:
        print("Notification timed out")


@on_interval("01:00:00")
def hourly_check(event: IntervalEvent):
    """Hourly status check."""
    temp = float(haa.entity.sensor.temperature)
    print(f"Temperature: {temp}°C, Alerts: {alert_count}")
    print(f"Executed {event.execution_count} times")


@shutdown
def cleanup(event: ActionEvent):
    """Save state on shutdown."""
    haa.set_variable("last_shutdown", haa.now().isoformat())
    print("Shutdown complete")
