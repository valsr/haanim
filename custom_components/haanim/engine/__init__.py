"""AST-based Python script execution engine for HAAnim.

This module provides a secure, sandboxed Python execution environment using
AST (Abstract Syntax Tree) evaluation instead of exec/eval for better security.
"""

from __future__ import annotations

import ast
import builtins
import importlib
import logging
from typing import Any

from custom_components.haanim.const import DEFAULT_IMPORT_ALLOWLIST, RESTRICTED_BUILTINS
from custom_components.haanim.engine.AstEvaluator import AstEvaluator
from custom_components.haanim.engine.errors import (
    ScriptRuntimeError,
    ScriptSecurityError,
)

_LOGGER = logging.getLogger(__name__)

__all__ = [
    # Error types
    "ScriptRuntimeError",
    "ScriptSecurityError",
    # Core components
    "ImportController",
    "SafeBuiltins",
    "SymbolTable",
]


class SafeBuiltins:
    """Provides a filtered set of Python builtins for script execution."""

    def __init__(
        self,
        restricted: set[str] | None = None,
        additional_allowed: dict[str, Any] | None = None,
    ) -> None:
        """Initialize safe builtins.

        Args:
            restricted: Set of builtin names to restrict. Defaults to RESTRICTED_BUILTINS.
            additional_allowed: Additional names to make available.
        """
        self._restricted = restricted or RESTRICTED_BUILTINS
        self._builtins: dict[str, Any] = {}

        # Copy allowed builtins
        for name in dir(builtins):
            if not name.startswith("_") and name not in self._restricted:
                self._builtins[name] = getattr(builtins, name)

        # Add additional allowed items
        if additional_allowed:
            self._builtins.update(additional_allowed)

    def get_builtins(self) -> dict[str, Any]:
        """Get the filtered builtins dictionary.

        Returns:
            Dictionary of allowed builtins.
        """
        return self._builtins.copy()


class ImportController:
    """Controls which modules can be imported in scripts."""

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
        """Register a virtual module that can be imported by scripts.

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
            ScriptSecurityError: If the module is not allowed.
        """
        # Check for virtual modules first
        if module_name in self._virtual_modules:
            return self._virtual_modules[module_name]

        if not self.is_allowed(module_name):
            _LOGGER.error("Import blocked - module '%s' is not in allowlist", module_name)
            raise ScriptSecurityError(f"Import of module '{module_name}' is not allowed")

        try:
            module = importlib.import_module(module_name)
            self._imported_modules[module_name] = module
            return module
        except ImportError as err:
            _LOGGER.error("Failed to import module '%s': %s", module_name, err)
            raise ScriptRuntimeError(f"Failed to import module '{module_name}': {err}") from err


class SymbolTable:
    """Manages variable scopes during script execution."""

    def __init__(self, parent: SymbolTable | None = None) -> None:
        """Initialize a symbol table.

        Args:
            parent: Parent symbol table for scope chain.
        """
        self._symbols: dict[str, Any] = {}
        self._parent = parent

    def get(self, name: str, default: Any = None) -> Any:
        """Get a symbol value.

        Args:
            name: The symbol name.
            default: Default value if not found.

        Returns:
            The symbol value or default.
        """
        if name in self._symbols:
            return self._symbols[name]
        if self._parent:
            return self._parent.get(name, default)
        return default

    def set(self, name: str, value: Any) -> None:
        """Set a symbol value in the current scope.

        Args:
            name: The symbol name.
            value: The value to set.
        """
        self._symbols[name] = value

    def set_global(self, name: str, value: Any) -> None:
        """Set a symbol value in the global scope.

        Args:
            name: The symbol name.
            value: The value to set.
        """
        if self._parent:
            self._parent.set_global(name, value)
        else:
            self._symbols[name] = value

    def exists(self, name: str) -> bool:
        """Check if a symbol exists.

        Args:
            name: The symbol name.

        Returns:
            True if the symbol exists in this or parent scope.
        """
        if name in self._symbols:
            return True
        if self._parent:
            return self._parent.exists(name)
        return False

    def delete(self, name: str) -> bool:
        """Delete a symbol from the current scope.

        Args:
            name: The symbol name.

        Returns:
            True if the symbol was deleted.
        """
        if name in self._symbols:
            del self._symbols[name]
            return True
        return False

    def as_dict(self) -> dict[str, Any]:
        """Get all symbols as a dictionary.

        Returns:
            Dictionary of all symbols in scope chain.
        """
        result: dict[str, Any] = {}
        if self._parent:
            result.update(self._parent.as_dict())
        result.update(self._symbols)
        return result

    def create_child(self) -> SymbolTable:
        """Create a child scope.

        Returns:
            A new SymbolTable with this as parent.
        """
        return SymbolTable(parent=self)


class EvalFunction:
    """Wrapper for user-defined functions in scripts."""

    def __init__(
        self,
        name: str,
        args: ast.arguments,
        body: list[ast.stmt],
        decorators: list[Any],
        engine: AstEvaluator,
        closure: SymbolTable,
        is_async: bool = False,
    ) -> None:
        """Initialize an evaluated function.

        Args:
            name: Function name.
            args: AST arguments node.
            body: List of AST statement nodes for the function body.
            decorators: List of evaluated decorators.
            engine: The AstEvaluator instance.
            closure: The symbol table at function definition time.
            is_async: Whether this is an async function.
        """
        self.name = name
        self.args = args
        self.body = body
        self.decorators = decorators
        self.engine = engine
        self.closure = closure
        self.is_async = is_async
        self.__name__ = name

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Call the function.

        Args:
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            The function return value.
        """
        # Create new scope for function execution
        local_scope = self.closure.create_child()

        # Bind positional arguments
        arg_names = [arg.arg for arg in self.args.args]
        for i, (name, value) in enumerate(zip(arg_names, args)):
            local_scope.set(name, value)

        # Bind keyword arguments
        for name, value in kwargs.items():
            local_scope.set(name, value)

        # Bind defaults for missing arguments
        defaults = self.args.defaults
        num_defaults = len(defaults)
        num_args = len(arg_names)
        for i, default in enumerate(defaults):
            arg_index = num_args - num_defaults + i
            arg_name = arg_names[arg_index]
            if not local_scope.exists(arg_name):
                default_val = await self.engine.aeval(default, local_scope)
                local_scope.set(arg_name, default_val)

        # Execute function body
        result = None
        for stmt in self.body:
            try:
                result = await self.engine.aeval(stmt, local_scope)
                if isinstance(result, ReturnValue):
                    return result.value
            except ReturnValue as ret:
                return ret.value

        return result


class ReturnValue(Exception):
    """Used to propagate return values up the call stack."""

    def __init__(self, value: Any) -> None:
        """Initialize with return value.

        Args:
            value: The value being returned.
        """
        super().__init__()
        self.value = value
