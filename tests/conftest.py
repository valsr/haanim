"""Test configuration and fixtures for HAAnim tests."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant


@pytest.fixture
def hass():
    """Return a Home Assistant instance for testing.

    Returns:
        HomeAssistant: A test Home Assistant instance.
    """
    # This is a placeholder - in real tests, you would use
    # pytest-homeassistant-custom-component fixtures
    pass


@pytest.fixture
def mock_config_entry():
    """Return a mock config entry.

    Returns:
        ConfigEntry: A mock configuration entry for testing.
    """
    # Placeholder for mock config entry
    pass
