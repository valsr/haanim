"""Demo: the automation's own device in Home Assistant, and the entities it declares.

Each class below is an entity of the device "Demo: entities". The sensor is
written by the automation; the switch, number, select and button are operated
by users in Home Assistant, and each command runs the class's hook.
"""

from datetime import timedelta

from haanim import (
    ActionEvent,
    DeviceEntity,
    action,
    EntityCommandEvent,
    button_entity,
    haa,
    number_entity,
    on_interval,
    select_entity,
    sensor_entity,
    startup,
    switch_entity,
)


@sensor_entity(
    name="Minutes running", unit="min", state_class="total_increasing", icon="mdi:timer", initial=0
)
class ticks:
    """Written by the automation: no hooks."""


@sensor_entity(name="Energy", unit="kWh", device_class="energy", state_class="total_increasing", initial=0)
class energy:
    """Long-term statistics only: the backfill action imports past hours into it."""


# kWh used in each hour of a day, from midnight
PROFILE = [0.3] * 6 + [0.8, 1.2, 0.9] + [0.5] * 8 + [1.1, 1.6, 1.4, 1.0, 0.7] + [0.4] * 2


@switch_entity(name="Boost", icon="mdi:fire", initial=False)
class boost:
    def turn_on(self, entity: DeviceEntity, event: EntityCommandEvent) -> None:
        entity.set_state(True)
        haa.set_message("Boost on")

    def turn_off(self, entity: DeviceEntity, event: EntityCommandEvent) -> None:
        entity.set_state(False)
        haa.set_message("Boost off")


@number_entity(name="Target", min=10, max=30, step=0.5, unit="°C", initial=20)
class target:
    def set_value(self, entity: DeviceEntity, event: EntityCommandEvent) -> None:
        entity.set_state(event.value)


@select_entity(name="Mode", options=["comfort", "eco"], initial="comfort")
class mode:
    def select_option(self, entity: DeviceEntity, event: EntityCommandEvent) -> None:
        entity.set_state(event.value)
        if event.value == "eco":
            haa.device.entity(target).set_state(18)


@button_entity(name="Reset count", icon="mdi:restart")
class reset:
    def press(self, entity: DeviceEntity, event: EntityCommandEvent) -> None:
        haa.device.entity(ticks).set_state(0)


@startup
def begin(event: ActionEvent) -> None:
    haa.device.entity(ticks).set_state(0)


@on_interval(60)
def count(event: ActionEvent) -> None:
    minutes = haa.device.entity(ticks)
    minutes.set_state((minutes.state or 0) + 1)


@action(description="Import the last 24 hours of energy use as long-term statistics.")
async def backfill(event: ActionEvent) -> int:
    last = haa.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    first = last - timedelta(hours=23)
    rows = [{"start": first + timedelta(hours=hour), "usage": PROFILE[hour]} for hour in range(24)]
    return await haa.device.entity(energy).import_statistics(rows)
