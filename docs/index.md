# HAAnim

Write Home Assistant automations in Python. An automation is a folder with a `main.py`; decorators say when
its functions run, and the `haa` object reaches entities, services, storage and the automation's own
dashboard card.

```python
from haanim import StateEvent, TimeEvent, haa, on_state, on_time


@on_state("sensor.temperature > 30")
async def high_temperature(event: StateEvent):
    await haa.service.notify.mobile_app(message=f"It is {float(haa.entity.sensor.temperature)}°C")


@on_time("09:00", day_of_week="weekdays", when="person.john == 'home'")
async def morning(event: TimeEvent):
    await haa.service.light.turn_on(entity_id="light.bedroom", brightness=150)
```

## What you get

- **Triggers**: time (including sunrise and sunset), interval, cron, Home Assistant events and state
  expressions, each with optional constraints.
- **Actions** that can be run by hand, by a service, by another automation or by a trigger, with `DROP`,
  `QUEUE` and `CANCEL` execution modes and timeouts.
- **`haa`**: entities, service calls, `sleep` and `wait_for`, persistent variables, assets, and calling
  other automations.
- **A dashboard card** per automation, which the automation fills itself: text, HTML, images and camera
  pictures, values, entities, icons, gauges, badges, graphs and buttons, laid out in rows.
- **A panel** in the sidebar with every automation's controls, actions and log.
- **A sensor per automation** (`sensor.haanim_<id>`: `on`, `off`, `error`).
- **Hot reload**: edit a file and the automation is reloaded.
- **A test harness**: test an automation with `pytest`, with no Home Assistant running.

## Where to go

| If you want to                              | Read                                         |
| ------------------------------------------- | -------------------------------------------- |
| Install HAAnim and run a first automation   | [Getting started](getting-started.md)        |
| Know everything an automation can do        | [Writing automations](AUTOMATIONS.md)        |
| Use the card, the panel and the services    | [In Home Assistant](home-assistant.md)       |
| See complete automations to copy from       | [Examples and demos](examples.md)            |

!!! warning "Automations are code you trust"
    The interpreter keeps automations from blocking Home Assistant by accident: no blocking I/O, an import
    allowlist, loops that yield. It is a guard rail, not a sandbox. An automation can do whatever Home
    Assistant can, so only install automations you trust.

HAAnim is a custom integration and is not supported by the Home Assistant project. It is released under
the MIT license.
