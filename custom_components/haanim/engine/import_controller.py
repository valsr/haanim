"""Import allowlist enforcement for automation code."""

from __future__ import annotations

import importlib
import logging
from typing import Any

from custom_components.haanim.const import DEFAULT_IMPORT_ALLOWLIST
from custom_components.haanim.engine.errors import AutomationRuntimeError, AutomationSecurityError

_LOGGER = logging.getLogger(__name__)


class ImportController:
    """Controls which modules can be imported in automations."""

    def __init__(
        self,
        allowlist: list[str] | None = None,
        allow_all: bool = False,
    ) -> None:
        """Initialize the import controller.

        Args:
            allowlist: List of allowed module names. Defaults to DEFAULT_IMPORT_ALLOWLIST.
            allow_all: If True, allow all imports (use with caution).
        """
        self._allowlist = set(allowlist or DEFAULT_IMPORT_ALLOWLIST)
        self._allow_all = allow_all
        self._imported_modules: dict[str, Any] = {}
        self._virtual_modules: dict[str, Any] = {}

    def register_virtual_module(self, name: str, module: Any) -> None:
        """Register a virtual module that can be imported by automations.

        Args:
            name: The module name (e.g., 'haanim').
            module: The module object or namespace to expose.
        """
        self._virtual_modules[name] = module
        self._allowlist.add(name)

    def is_allowed(self, module_name: str) -> bool:
        """Check if a module is allowed to be imported.

        Args:
            module_name: The module name to check.

        Returns:
            True if the module can be imported.
        """
        if self._allow_all:
            return True

        # Check the top-level module name
        top_level = module_name.split(".")[0]
        return top_level in self._allowlist

    def safe_import(self, module_name: str, _: list[str] | None = None) -> Any:
        """Safely import a module if allowed.

        Args:
            module_name: The module to import.
            fromlist: List of names to import from the module.

        Returns:
            The imported module.

        Raises:
            AutomationSecurityError: If the module is not allowed.
        """
        # Check for virtual modules first
        if module_name in self._virtual_modules:
            return self._virtual_modules[module_name]

        if not self.is_allowed(module_name):
            _LOGGER.error("Import blocked - module '%s' is not in allowlist", module_name)
            raise AutomationSecurityError(f"Import of module '{module_name}' is not allowed")

        try:
            module = importlib.import_module(module_name)
            self._imported_modules[module_name] = module
            return module
        except ImportError as err:
            _LOGGER.error("Failed to import module '%s': %s", module_name, err)
            raise AutomationRuntimeError(f"Failed to import module '{module_name}': {err}") from err
