"""Top-level test configuration.

The engine tests (``tests/engine``) do not need Home Assistant. The integration
tests (``tests/integration``) do. When Home Assistant's test plugin is not
installed, the integration tests are skipped at collection and the engine tests
still run.
"""

from __future__ import annotations

try:
    import pytest_homeassistant_custom_component  # noqa: F401  pylint: disable=unused-import
except ImportError:
    collect_ignore = ["integration"]
else:
    # Must be set in the top-level conftest; provides the ``hass`` fixture and friends.
    pytest_plugins = "pytest_homeassistant_custom_component"
