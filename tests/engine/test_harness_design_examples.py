"""The two harness examples of the design, run as they are written there.

See "Testing User Automations" in the design. The automation they test is the
design's Complete Example, kept in ``examples/climate``; the fixture puts it
where the examples look for it, ``automations/climate``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from haanim.testing import AutomationHarness

CLIMATE = Path(__file__).parents[2] / "examples" / "climate"


@pytest.fixture(autouse=True)
def automations_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run each test in a directory that has the example as ``automations/climate``."""
    shutil.copytree(CLIMATE, tmp_path / "automations" / "climate")
    monkeypatch.chdir(tmp_path)


# --- Verbatim from the design -------------------------------------------------------


async def test_high_temperature_alert():
    async with AutomationHarness("automations/climate") as automation:
        automation.set_state("sensor.temperature", "25")
        automation.set_state("sensor.temperature", "31")  # crosses the threshold

        await automation.wait_idle()  # all dispatched actions finished
        assert automation.service_calls("notify.mobile_app")[0].data["message"].startswith("High temperature")
        assert automation.get_variable("alert_count") == 1


async def test_morning_routine_only_when_home():
    async with AutomationHarness("automations/climate", now="2025-01-06 08:59:00") as automation:
        automation.set_state("person.john", "away")
        await automation.advance_time(minutes=2)  # passes 09:00
        assert automation.service_calls("light.turn_on") == []


# --- The other side of each example ---------------------------------------------------


async def test_no_alert_below_the_threshold() -> None:
    """Test the first example fails for the right reason: no crossing, no alert."""
    async with AutomationHarness("automations/climate") as automation:
        automation.set_state("sensor.temperature", "25")
        automation.set_state("sensor.temperature", "29")
        await automation.wait_idle()
        assert automation.service_calls("notify.mobile_app") == []
        assert automation.get_variable("alert_count") is None


async def test_morning_routine_when_home() -> None:
    """Test the second example fails for the right reason: at home the routine runs."""
    async with AutomationHarness("automations/climate", now="2025-01-06 08:59:00") as automation:
        automation.set_state("person.john", "home")
        automation.set_state("sensor.outdoor_temp", "4.5")
        await automation.advance_time(minutes=2)
        (call,) = automation.service_calls("light.turn_on")
        assert call.data == {"entity_id": "light.bedroom", "brightness": 150}
        assert (
            automation.service_calls("notify.mobile_app")[0].data["message"]
            == "Good morning! Temperature: 4.5°C"
        )
        assert automation.message == "Morning routine completed"
