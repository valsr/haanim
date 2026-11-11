# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-11-09

### Added

- Each automation is a device in Home Assistant, with its status sensor on it.
- Automations declare entities of their device with class decorators: `@sensor_entity`,
  `@binary_sensor_entity`, `@switch_entity`, `@number_entity`, `@select_entity`, `@button_entity` and
  `@text_entity`. HAAnim keeps their state, which survives restarts; `haa.device.entity()` reads and writes it.
- Commands from Home Assistant (turning a switch on, setting a number, pressing a button) run the class's hooks
  as actions, with an `EntityCommandEvent`.
- The automation page in the panel has an **Entities** tab: remove leftover entities and purge stored data.
- The test harness drives entities: `entity()`, `entities`, `command()` and `entities=`.
- Long-term statistics: `entity.import_statistics()` imports past hours into a declared sensor with a
  `state_class` (usage per hour for sums, which continue from and join up with the stored ones), and
  `haa.statistics()` and `entity.statistics()` read the statistics of any entity.
- The `demo_entities` example, with a backfill of energy statistics.
- Async generators: `yield` in an `async def`, `async for`, async comprehensions and async generator
  expressions, with `asend`, `athrow` and `aclose`.
- Generators: `yield`, `yield from` and generator expressions, lazy and with `send`, `throw` and `close`.
  `list`, `sum`, `sorted` and the other calls that consume every item pull a generator with the event loop free
  between items.
- Cards have a table element: `haa.card.create_table()`, with column names, rows of values, units and a
  title, and `add_row(..., limit=...)` for a rolling log.
- Constants for automations: `EntityPlatform`, `EntityCommand`, `StateClass`, `NumberMode`, `TextMode`, `Period`,
  and common units (`UnitOfEnergy`, `UnitOfTemperature`, ... and `PERCENTAGE`) with Home Assistant's names and values.

### Fixed

- Test harness: `time_zone=` sets the zone the automation runs in even without `now=` (it was UTC); an action
  a trigger, an entity command or `@shutdown` ran that fails now fails the test (`expect_failures=True` to
  collect failures in `failures` instead); and an automation's `from .package import module` works, with or
  without `__init__.py`.
- Test harness: services behave as in Home Assistant. One stubbed without a response gives none even when asked
  (`supports_response="optional"` or `"only"` says otherwise); `stub_service(..., fields=[...])` refuses other
  keys, as the service's schema does; and `response=` may be a function of the call's data, for answers that
  depend on the call. The contract tests cover services that give no response.
- `return_response=` passed to a service call raises `TypeError`: it reached the service as a field, which the
  service refused.
- A service call whose data the service's schema refuses gives a failed result with the reason; it was reported
  as an unexpected error.
- `except StopIteration` in automation code caught nothing: Python turned it into `RuntimeError` on its way
  through the interpreter. It now behaves as in Python.
- Automation code run synchronously by Python code (a `key=` function of `sorted`, a generator pulled by `any`)
  could freeze Home Assistant for good. It is now stopped with a `TimeoutError` after 10 seconds.
- The test harness's `wait_idle()` gave up on a long calculation after a fixed number of event-loop turns,
  saying the action should be given time. It now waits as long as the actions compute, up to `max_steps`
  steps of automation code (1,000,000 by default), and says whether actions are waiting or still computing.

## [0.3.1] - 2026-11-09

### Fixed

- Calling a service that gives no response (`light.turn_on`, `persistent_notification.create`, most services)
  failed with "An action which does not return responses can't be called with return_response=True". A
  response is now asked for only from services that can give one.
- The services guide no longer shows `return_response=True` as an argument: it reached the service as a field.

## [0.3.0] - 2026-10-23

### Added

- An automation's `metadata.json` can allow imports for that automation alone: `additional_imports` lists
  modules allowed in addition to the allowlist and the integration's options, and `allow_all_imports: true`
  turns the allowlist off for it. Both add to the integration's options and never narrow them.

## [0.2.0] - 2026-10-06

The first published release: the integration is installable with HACS and the `haanim` package is on PyPI.
It needs Home Assistant 2026.11 or newer; the package needs Python 3.14.

### Added

- **The automation engine**: automations are folders with a `main.py`; time, interval, cron, event and
  state triggers with constraints; actions with `DROP`, `QUEUE` and `CANCEL` modes, timeouts and return
  values; a lifecycle with `@startup` and `@shutdown`; hot reload.
- **`haa`**: entity access, service calls, `sleep` and `wait_for`, persistent variables, assets
  (`read_asset`, `asset_url`), calling and controlling other automations.
- **Cards**: an automation fills its own dashboard card (`haa.card`) with text, HTML, images and camera
  pictures, values, entities, icons, gauges, badges, graphs and buttons, laid out in rows and cells.
- **In Home Assistant**: one sensor per automation (`sensor.haanim_<id>`); services to run actions, to
  enable, disable, start, stop, restart and reload automations, to list automations and actions, to clear
  the log and to set a log level per automation; the `custom:haanim-card` card and a management panel.
- **The `haanim` pip package**: the engine without Home Assistant, type information for everything an
  automation imports (`py.typed`), and `haanim.testing.AutomationHarness` for testing automations with
  `pytest`.
- Example automations with harness tests in `examples/`, among them a demo for each part of the card, and
  documentation on [Read the Docs](https://haanim.readthedocs.io/).

### Changed

- **Breaking:** scripts are now automations, in folders; `time_trigger`, `set_status`, `log_info()` and the
  other old names are gone, as are the services `reload_automations` and `get_config` and the REST views.
  See the automation guide for the current API.
- A release of the integration has the engine in it: installing it with HACS installs no Python package
  into Home Assistant.

## [0.1.0] - 2025-11-25

### Added
- Initial release
- Basic HAAnim integration for Home Assistant
