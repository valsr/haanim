# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-10-06

The first published release: the integration is installable with HACS and the `haanim` package is on PyPI.

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
