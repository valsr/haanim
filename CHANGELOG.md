# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **The automation engine as designed**: automations are folders with a `main.py`; time, interval, cron,
  event and state triggers with constraints; actions with `DROP`, `QUEUE` and `CANCEL` modes, timeouts and
  return values; a lifecycle with `@startup` and `@shutdown`; hot reload.
- **`haa`**: entity access, service calls, `sleep` and `wait_for`, persistent variables, assets
  (`read_asset`, `asset_url`), card content (`haa.card`), calling and controlling automations.
- **One sensor per automation** (`sensor.haanim_<id>`), the services `haanim.run_action`, `enable`,
  `disable`, `start`, `stop`, `restart`, `reload`, `list_automations` and `list_actions`, and ten
  integration options.
- **Frontend**: the `custom:haanim-card` dashboard card and a management panel, fed by websocket commands.
- **The `haanim` pip package**: the engine without Home Assistant, type information for everything an
  automation imports (`py.typed`), and `haanim.testing.AutomationHarness` for testing automations with
  `pytest`.
- Example automations with harness tests in `examples/`, an automation guide in `docs/AUTOMATIONS.md`, and
  an end-to-end smoke test for the development container.
- UV package management integration
- Comprehensive `pyproject.toml` with all dependencies and tool configurations
- `UV_GUIDE.md` documentation for UV usage
- Test suite structure with pytest
- **GitHub Actions CI workflow** with multi-version testing, linting, and coverage reporting
- Make commands for UV operations (`make install`, `make dev`, `make test`, etc.)
- `.python-version` file for Python version management
- **VS Code tasks and debug configurations** for one-click development
  - Start Home Assistant with automatic browser opening
  - Run and Debug configurations
  - Testing and linting tasks
  - Container management tasks

### Changed

- **Breaking:** scripts are now automations, in folders; `time_trigger`, `set_status`, `log_info()` and the
  other old names are gone, as are the services `reload_automations` and `get_config` and the REST views.
  See the automation guide for the current API.
- The integration requires the `haanim` package at its own version, and the package no longer depends on
  Home Assistant.
- CI fails on any `pylint` message, `mypy` or `pyright` error, and on less than 100% coverage of the
  automation-facing API.
- Updated README with UV setup instructions
- Updated CONTRIBUTING guide with UV workflows
- Enhanced Makefile with UV-based commands
- Updated `.gitignore` to include UV-specific entries
- **Migrated hosting from GitLab to GitHub**, removed `.gitlab-ci.yml`, and made GitHub Actions the primary CI platform

### Infrastructure

- Moved from manual dependency management to UV
- Added automated testing and linting in GitHub Actions
- Standardized development workflow with Make commands
- Configured coverage reporting with Codecov and GitHub Actions artifacts
- Added secret scanning with Gitleaks
- **Integrated VS Code development workflow** with tasks and debug configs

## [0.1.0] - 2025-11-25

### Added
- Initial release
- Basic HAAnim integration for Home Assistant
