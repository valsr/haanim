# HAAnim Type Stubs

This directory contains type stub files (`.pyi`) for the HAAnim virtual module that provides type hints for user automations.

## Usage

To get proper IDE support (autocompletion, type checking, documentation) in your HAAnim automations:

### Option 1: Copy to your automations folder

Copy `haanim.pyi` to your HAAnim automations folder (e.g., `config/haanim/`).

### Option 2: Configure your IDE

Add this `stubs` directory to your Python path or type checker configuration.

**For VS Code (Pylance)**, add to your `settings.json`:
```json
{
    "python.analysis.extraPaths": ["path/to/haanim/stubs"]
}
```

**For mypy**, add to `mypy.ini` or `pyproject.toml`:
```ini
[mypy]
mypy_path = path/to/haanim/stubs
```

## Regenerating Stubs

If the decorators change, regenerate the stubs using:

```bash
uv run python scripts/generate_stubs.py
```

Or use the VS Code task: **"Generate HAAnim Stubs"**

## Available Exports

The `haanim` module provides the following decorators:

- `@scene` - Mark a function as a manually executable scene
- `@state_trigger` - Trigger on entity state changes
- `@time_trigger` - Trigger at specific times (cron, sunrise/sunset, etc.)
- `@event_trigger` - Trigger on Home Assistant events
- `@time_active` - Constrain when triggers can fire (time-based)
- `@state_active` - Constrain when triggers can fire (state-based)
- `@service` - Expose a function as a Home Assistant service

## Built-in Globals

The following are available as global variables in your automations (not from import):

- `log` - Logger instance for your automation
- `log_debug`, `log_info`, `log_warning`, `log_error` - Logging shortcuts
- `sleep` - Async sleep function for delays
- `hass` - Home Assistant instance (when available)
- `state` - StateManager for entity access (when available)
