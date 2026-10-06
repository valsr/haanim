"""Tests for the climate example, written as an automation author would write them."""

from __future__ import annotations

from pathlib import Path

from haanim.testing import AutomationHarness

CLIMATE = Path(__file__).parents[1] / "climate"


async def test_high_temperature_alert() -> None:
    """Crossing 30 degrees sends one notification and counts the alert."""
    async with AutomationHarness(CLIMATE) as automation:
        automation.set_state("sensor.temperature", "25")
        automation.set_state("sensor.temperature", "31")

        await automation.wait_idle()
        (call,) = automation.service_calls("notify.mobile_app")
        assert call.data["message"] == "High temperature: 31.0°C (Alert #1)"
        assert automation.get_variable("alert_count") == 1


async def test_alert_counts_each_crossing() -> None:
    """Staying above the threshold is one alert; coming back and crossing again is another."""
    async with AutomationHarness(CLIMATE) as automation:
        for temperature in ("31", "33", "28", "32"):
            automation.set_state("sensor.temperature", temperature)
            await automation.wait_idle()
        assert len(automation.service_calls("notify.mobile_app")) == 2
        assert automation.get_variable("alert_count") == 2


async def test_alert_count_is_kept_across_restarts() -> None:
    """@startup reads the stored count, so the numbering goes on."""
    async with AutomationHarness(CLIMATE, variables={"alert_count": 7}) as automation:
        assert "Initialized: 7 alerts, threshold 25.0°C" in automation.logs()
        automation.set_state("sensor.temperature", "35")
        await automation.wait_idle()
        assert automation.service_calls("notify.mobile_app")[0].data["message"].endswith("(Alert #8)")


async def test_morning_routine_on_a_weekday_at_home() -> None:
    """At 09:00 on a Monday with John at home, the light goes on and the temperature is announced."""
    async with AutomationHarness(CLIMATE, now="2025-01-06 08:59:00") as automation:
        automation.set_state("person.john", "home")
        automation.set_state("sensor.outdoor_temp", "4.5")
        await automation.advance_time(minutes=2)

        (light,) = automation.service_calls("light.turn_on")
        assert light.data == {"entity_id": "light.bedroom", "brightness": 150}
        assert (
            automation.service_calls("notify.mobile_app")[0].data["message"]
            == "Good morning! Temperature: 4.5°C"
        )
        assert automation.message == "Morning routine completed"


async def test_no_morning_routine_when_away() -> None:
    """The `when` constraint keeps the routine from running while John is away."""
    async with AutomationHarness(CLIMATE, now="2025-01-06 08:59:00") as automation:
        automation.set_state("person.john", "away")
        await automation.advance_time(minutes=2)
        assert automation.service_calls("light.turn_on") == []


async def test_no_morning_routine_at_the_weekend() -> None:
    """The `day_of_week` constraint keeps the routine from running on a Saturday."""
    async with AutomationHarness(CLIMATE, now="2025-01-04 08:59:00") as automation:
        automation.set_state("person.john", "home")
        automation.set_state("sensor.outdoor_temp", "4.5")
        await automation.advance_time(minutes=2)
        assert automation.service_calls("light.turn_on") == []


async def test_send_notification_calls_the_other_automation() -> None:
    """The action calls `send_message` of the notifications automation."""
    async with AutomationHarness(CLIMATE) as automation:
        automation.stub_automation("notifications", send_message="sent")
        await automation.call("send_notification")
        (call,) = automation.automation_calls("notifications")
        assert (call.action, call.caller) == ("send_message", "climate")


async def test_hourly_check_reports_the_temperature() -> None:
    """Every hour the temperature and the number of runs are printed."""
    async with AutomationHarness(CLIMATE, states={"sensor.temperature": "21"}) as automation:
        await automation.advance_time(hours=2)
        assert automation.logs().count("Temperature: 21.0°C, Alerts: 0") == 2
        assert "Executed 2 times" in automation.logs()


async def test_shutdown_records_when_it_stopped() -> None:
    """@shutdown stores the time of the stop."""
    async with AutomationHarness(CLIMATE, now="2025-01-06 10:00:00") as automation:
        await automation.stop()
        assert automation.get_variable("last_shutdown") == "2025-01-06T10:00:00+00:00"
        assert "Shutdown complete" in automation.logs()


async def test_hourly_check_run_by_hand() -> None:
    """Run from the card or a service, the check has no run count to report, and does not fail."""
    async with AutomationHarness(CLIMATE, states={"sensor.temperature": "21"}) as automation:
        await automation.call("hourly_check")
        assert "Temperature: 21.0°C, Alerts: 0" in automation.logs()
        assert "Executed" not in automation.logs()
