"""Files of an automation that other files of it import."""

from __future__ import annotations

import ast
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from haanim.engine.errors import AutomationSecurityError
from haanim.engine.symbol_table import SymbolTable

if TYPE_CHECKING:
    from haanim.interfaces import FileSystem


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


class ModuleLoader:
    """Loads the files an automation imports with relative imports.

    One loader is shared by all files of an automation, so that every import
    of a file gives the same module.
    """

    def __init__(
        self,
        name: str,
        files: FileSystem,
        root: Path,
        run_file: Callable[[Path, SymbolTable], Awaitable[None]],
    ) -> None:
        """Initialize the loader.

        Args:
            name: Name of the automation, for error messages.
            files: File system to read the files from.
            root: Directory relative imports must stay within.
            run_file: Checks and executes a file in the given module scope.
        """
        self._name = name
        self._files = files
        self._root = root
        self._run_file = run_file
        self.modules: dict[Path, AutomationModule] = {}

    async def import_from(self, importer: Path, node: ast.ImportFrom, scope: SymbolTable) -> None:
        """Evaluate a relative import statement.

        Args:
            importer: Path of the file containing the statement.
            node: The import statement.
            scope: The scope to bind the imported names in.
        """
        package = importer.parent
        for _ in range(node.level - 1):
            package = package.parent
        if not package.is_relative_to(self._root):
            raise AutomationSecurityError("Relative import reaches outside the automation")

        if node.module:
            # from .helper import name
            module = await self._load(package.joinpath(*node.module.split(".")), node)
            for alias in node.names:
                try:
                    obj = getattr(module, alias.name)
                except AttributeError:
                    raise ImportError(f"cannot import name '{alias.name}' from '.{node.module}'") from None
                scope.set(alias.asname or alias.name, obj)
        else:
            # from . import helper
            for alias in node.names:
                scope.set(alias.asname or alias.name, await self._load(package / alias.name, node))

    async def _load(self, location: Path, node: ast.ImportFrom) -> AutomationModule:
        """Load a file of the automation as a module, once.

        Args:
            location: Path of the module without its ``.py`` suffix.
            node: The import statement, for the error message.

        Returns:
            The module. The same object is returned on every import of the file.
        """
        candidates = [location.with_name(location.name + ".py"), location / "__init__.py"]
        path = next((candidate for candidate in candidates if self._files.exists(candidate)), None)
        if path is None:
            dotted = "." * node.level + (node.module or location.name)
            raise ModuleNotFoundError(f"No module named '{dotted}' in automation '{self._name}'")

        if path in self.modules:
            return self.modules[path]

        module_scope = SymbolTable()
        module = AutomationModule(path, module_scope)
        # Registered before it runs, so that two files importing each other terminate.
        self.modules[path] = module
        try:
            await self._run_file(path, module_scope)
        except BaseException:
            del self.modules[path]
            raise
        return module
