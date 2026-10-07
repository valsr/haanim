"""Scoped symbol table used by the AST evaluator."""

from __future__ import annotations

from typing import Any

SCOPE_MODULE = "module"
SCOPE_BLOCK = "block"
SCOPE_FUNCTION = "function"
SCOPE_CLASS = "class"
SCOPE_COMPREHENSION = "comprehension"


class SymbolTable:
    """Manages variable scopes during automation execution."""

    def __init__(self, parent: SymbolTable | None = None, kind: str | None = None) -> None:
        """Initialize a symbol table.

        Args:
            parent: Parent symbol table for scope chain.
            kind: What the scope belongs to: one of the ``SCOPE_*`` constants.
                Defaults to the module scope without a parent, a block with one.
        """
        if kind is None:
            kind = SCOPE_MODULE if parent is None else SCOPE_BLOCK
        self._symbols: dict[str, Any] = {}
        self._parent = parent
        self.kind = kind
        self.first_arg: Any = None
        self._global_names: set[str] = set()
        self._nonlocal_names: set[str] = set()

    def _root(self) -> SymbolTable:
        """Return the outermost (module) scope."""
        scope = self
        while scope._parent is not None:
            scope = scope._parent
        return scope

    def _owner(self, name: str) -> SymbolTable:
        """Return the scope that assignments to ``name`` made in this scope go to."""
        if name in self._global_names:
            return self._root()
        if name in self._nonlocal_names:
            scope = self._parent
            while scope is not None and scope._parent is not None:
                if name in scope._symbols and scope.kind != SCOPE_CLASS:
                    return scope
                scope = scope._parent
            raise SyntaxError(f"no binding for nonlocal '{name}' found")
        return self

    def declare_global(self, name: str) -> None:
        """Make ``name`` refer to the module scope from now on in this scope.

        Args:
            name: The symbol name.
        """
        self._global_names.add(name)

    def declare_nonlocal(self, name: str) -> None:
        """Make ``name`` refer to the nearest enclosing function scope that has it.

        Args:
            name: The symbol name.
        """
        self._nonlocal_names.add(name)

    def get(self, name: str, default: Any = None) -> Any:
        """Get a symbol value.

        Args:
            name: The symbol name.
            default: Default value if not found.

        Returns:
            The symbol value or default.
        """
        if name in self._global_names:
            return self._root().get(name, default)
        if name in self._symbols:
            return self._symbols[name]
        if self._parent:
            return self._parent.get(name, default)
        return default

    def set(self, name: str, value: Any) -> None:
        """Set a symbol value in the current scope.

        A name declared ``global`` or ``nonlocal`` in this scope is set in the
        scope the declaration refers to.

        Args:
            name: The symbol name.
            value: The value to set.
        """
        self._owner(name)._symbols[name] = value

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
        if name in self._global_names:
            return name in self._root()._symbols
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
        owner = self._owner(name)
        if name in owner._symbols:
            del owner._symbols[name]
            return True
        return False

    def own_symbols(self) -> dict[str, Any]:
        """Return the symbols defined in this scope itself, without its parents."""
        return dict(self._symbols)

    def function_scope(self) -> SymbolTable:
        """Return the nearest scope that is not a comprehension.

        That is the scope ``global``, ``nonlocal`` and ``:=`` apply to.
        """
        scope = self
        while scope.kind == SCOPE_COMPREHENSION and scope._parent is not None:
            scope = scope._parent
        return scope

    def closure_scope(self) -> SymbolTable:
        """Return the scope a function defined here closes over.

        A function defined in a class body does not see the names of the class
        body, so this skips class scopes.
        """
        scope = self
        while scope.kind == SCOPE_CLASS and scope._parent is not None:
            scope = scope._parent
        return scope

    def enclosing_first_arg(self) -> Any:
        """Return the first argument of the function this scope is in, for ``super()``."""
        scope: SymbolTable | None = self
        while scope is not None:
            if scope.kind == SCOPE_FUNCTION:
                return scope.first_arg
            scope = scope._parent
        return None

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

    def create_child(self, kind: str = SCOPE_BLOCK) -> SymbolTable:
        """Create a child scope.

        Args:
            kind: What the scope belongs to: one of the ``SCOPE_*`` constants.

        Returns:
            A new SymbolTable with this as parent.
        """
        return SymbolTable(parent=self, kind=kind)
