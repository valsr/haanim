# GitHub Copilot Instructions for HAAnim

## Project Overview
HAAnim is a Home Assistant Custom Component (HACS integration) that provides ability for end user to create
and manage automation entities using python by loading and executing user defined python scripts. The aim of
this integration is:
1. Provide a flexible and powerful way for users to create complex automations using python (similar to
    pyscript extension - https://github.com/custom-components/pyscript).
2. Expose a simple and intuitive interface within Home Assistant for managing these automations - allowing
    animations to be managed and executed.
3. Ensure seamless integration with Home Assistant's core features, including state management, event handling,
    and service calls.
4. Allow animations to be easily shared and reused within the Home Assistant community via HACS.
5. Provide robust error handling and logging to help users debug their scripts.

## Code Style and Standards

### Python Style
- Follow PEP 8 guidelines strictly
- Use type hints for all function parameters and return values
- Keep lines under 110 characters
- Use meaningful variable and function names
- Add comprehensive docstrings in Google format to all functions and classes
- NEVER include "Attributes:" or "Methods:" sections in docstrings
- Use async/await for all I/O operations
- The integration should follow Home Assistant's best practices and coding standards to ensure compatibility

### Documentation Format
When generating method or class documentation, always use Google format:
```python
def example_function(param1: str, param2: int) -> bool:
    """Brief description of what the function does.

    More detailed description if needed, explaining the purpose and behavior.

    Args:
        param1: Description of param1.
        param2: Description of param2.

    Returns:
        Description of return value.

    Raises:
        ExceptionType: When and why this exception is raised.
    """
```

### Home Assistant Specific
- Import from `homeassistant.*` packages (not `hass.*`)
- Use `async_setup` and `async_setup_entry` for initialization
- Always use `_LOGGER` for logging (import from `logging`)
- Follow Home Assistant's entity naming conventions
- Use `DOMAIN` constant from `const.py` for the integration domain
- Implement proper config flow for UI configuration
- Add translations for all user-facing strings

### File Organization
- Keep integration logic in `custom_components/haanim/`
- Use `const.py` for constants and configuration
- Add new platforms in separate files (e.g., `sensor.py`, `switch.py`)
- Update `PLATFORMS` list in `__init__.py` when adding new platforms
- Add translations to both `strings.json` and `translations/en.json`

## Common Patterns

### Creating Entities
```python
from homeassistant.helpers.entity import Entity

class HAnimEntity(Entity):
    """Base class for HAAnim entities."""

    def __init__(self, name: str) -> None:
        """Initialize the entity.

        Args:
            name: The name of the entity.
        """
        self._attr_name = name
        self._attr_unique_id = f"haanim_{name.lower().replace(' ', '_')}"
```

### Async Setup
```python
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry.

    Args:
        hass: Home Assistant instance.
        entry: The config entry.

    Returns:
        True if setup was successful.
    """
    # Setup logic here
    return True
```

### Error Handling
- Use Home Assistant's built-in exception types
- Log errors with `_LOGGER.error()` or `_LOGGER.exception()`
- Provide user-friendly error messages in config flow

## Integration Guidelines

### When Adding New Features
1. Update `manifest.json` if adding new requirements
2. Add configuration options to `config_flow.py`
3. Update translations in `strings.json` and `translations/en.json`
4. Add the platform to `PLATFORMS` in `__init__.py`
5. Update `README.md` with usage instructions
6. Update `CHANGELOG.md` with changes

### Testing Considerations
- Test all async functions properly
- Ensure config flow validation works
- Test entity state updates
- Verify translations display correctly

## Common Imports
```python
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
```

## DRY Principles
- Extract common functionality into helper functions
- Reuse base entity classes for similar entities
- Keep configuration in `const.py`
- Avoid code duplication across platform files

## Remember
- This is a HACS integration - follow HACS requirements
- Always maintain backward compatibility when possible
- Keep the integration lightweight and efficient
- Use Home Assistant's helper utilities when available
- Follow the principle: clean, readable, testable, and maintainable code

## Documentation

- Place documentation files in the `docs/` fodler
    - Excpetion: README.md, CHANGELOG.md, CONTRIBUTING.md, LICENSE
