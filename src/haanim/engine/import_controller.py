"""Import allowlist enforcement for automation code."""

from __future__ import annotations

import importlib
import logging
from collections.abc import Iterable
from typing import Any

from haanim.const import DEFAULT_IMPORT_ALLOWLIST
from haanim.engine.errors import AutomationSecurityError
from haanim.engine.guards import guard_module

_LOGGER = logging.getLogger(__name__)


class ImportController:
    """Controls which modules can be imported in automations."""

    def __init__(
        self,
        additional: Iterable[str] | None = None,
        allow_all: bool = False,
    ) -> None:
        """Initialize the import controller.

        Args:
            additional: Modules allowed in addition to DEFAULT_IMPORT_ALLOWLIST.
            allow_all: If True, allow all imports (use with caution).
        """
        self._allowlist = set(DEFAULT_IMPORT_ALLOWLIST) | set(additional or ())
        self._allow_all = allow_all
        self._virtual_modules: dict[str, Any] = {}

    def register_virtual_module(self, name: str, module: Any) -> None:
        """Register an object the engine supplies when an automation imports ``name``.

        A virtual module takes precedence over a real module of the same name.

        Args:
            name: The module name (e.g., 'haanim').
            module: The module object or namespace to expose.
        """
        self._virtual_modules[name] = module

    def is_allowed(self, module_name: str) -> bool:
        """Check if a module is allowed to be imported.

        A module is allowed if it or one of its parent packages is on the
        allowlist: allowing ``homeassistant`` allows ``homeassistant.const``.

        Args:
            module_name: The module name to check.

        Returns:
            True if the module can be imported.
        """
        if self._allow_all or module_name in self._virtual_modules:
            return True

        parts = module_name.split(".")
        return any(".".join(parts[: count + 1]) in self._allowlist for count in range(len(parts)))

    def safe_import(self, module_name: str) -> Any:
        """Import a module if allowed.

        Args:
            module_name: The module to import.

        Returns:
            What the automation gets for the module: the object registered for a
            virtual module, a guarded stand-in for a module with disabled
            members, or the module itself.

        Raises:
            AutomationSecurityError: If the module is not allowed.
            ImportError: If the module is allowed but cannot be imported.
        """
        if module_name in self._virtual_modules:
            return self._virtual_modules[module_name]

        if not self.is_allowed(module_name):
            _LOGGER.error("Import blocked - module '%s' is not in allowlist", module_name)
            raise AutomationSecurityError(f"Import of module '{module_name}' is not allowed")

        return guard_module(module_name, importlib.import_module(module_name))
