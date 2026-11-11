# HAAnim: Python automations for Home Assistant

Write automations as Python files with decorators for triggers, and reach entities, services, storage and a
dashboard card through one object, `haa`.

## Features

- Time, interval, cron, event and state triggers, with constraints
- Actions with execution modes, timeouts and return values, callable as services
- A device per automation, with its status sensor and the sensors, switches, numbers, selects, buttons and text
  entities the automation declares
- Long-term statistics: read those of any entity, import past hours into the automation's own sensors
- A management panel, and a `custom:haanim-card` the automation fills itself, with tables and graphs
- Generators and async generators, as in Python
- Hot reload of changed files
- A test harness: test automations with `pytest`, without Home Assistant

## Installation

1. Add `https://github.com/valsr/haanim` to HACS as a custom **Integration** repository and download HAAnim.
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration → HAAnim**.

The download has the HAAnim engine in it: no Python package has to be installed into Home Assistant.

## Documentation

- [README](https://github.com/valsr/haanim#readme)
- [Automation guide](https://github.com/valsr/haanim/blob/main/docs/AUTOMATIONS.md)
- [Examples](https://github.com/valsr/haanim/tree/main/examples)

## Issues

<https://github.com/valsr/haanim/issues>
