"""Scoped symbol table used by the AST evaluator."""

from __future__ import annotations

from typing import Any


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
