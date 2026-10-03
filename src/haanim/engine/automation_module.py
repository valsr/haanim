"""Files of an automation that other files of it import."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from haanim.engine.symbol_table import SymbolTable


class AutomationModule:
    """A file of an automation, as seen by the files that import it.

    Its attributes are the file's module-level names, read live from the scope
    the file runs in.
    """

    def __init__(self, path: Path, scope: SymbolTable) -> None:
        """Initialize the module.

        Args:
            path: The file the module was loaded from.
            scope: The module-level scope of the file.
        """
        self.path = path
        self._scope = scope

    def __getattr__(self, name: str) -> Any:
        """Return a module-level name of the file."""
        scope: SymbolTable = self.__dict__["_scope"]
        if name in scope.own_symbols():
            return scope.get(name)
        raise AttributeError(f"module '{self.path.stem}' has no attribute '{name}'")
