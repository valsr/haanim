"""Filtered Python builtins available to automation code."""

from __future__ import annotations

import builtins
from typing import Any

from custom_components.haanim.const import RESTRICTED_BUILTINS


class SafeBuiltins:
    """Provides a filtered set of Python builtins for automation execution."""

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
