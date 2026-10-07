"""The entity object automations read through ``haa.entity``.

See "Entity Access" and "HAAnimEntity" in the design. A ``HAAnimEntity`` is a
snapshot of one entity taken when it is read. Comparing it compares its state
with the conversion rules of trigger expressions, so a comparison means the
same in an ``@on_state`` expression and in action code.
"""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from haanim.engine.errors import NonExistingEntityError
from haanim.engine.expression_eval import EntityOperand, Unusable, compare, contains, truth


class HAAnimEntity:
    """A snapshot of an entity: its state, attributes and timestamps.

    The object does not change if the entity changes afterwards. Reading it
    never raises: a missing entity has ``exists == False`` and ``state is
    None``, and a missing attribute is ``None``.
    """

    __slots__ = ("_entity_id", "_state", "_attributes", "_last_changed", "_last_updated")

    # Comparing by state means two equal objects need not be the same entity
    __hash__ = None  # type: ignore[assignment]

    def __init__(
        self,
        entity_id: str,
        state: str | None = None,
        *,
        attributes: Mapping[str, Any] | None = None,
        last_changed: datetime | None = None,
        last_updated: datetime | None = None,
    ) -> None:
        """Initialize the snapshot.

        Args:
            entity_id: Full entity ID, such as ``"sensor.temperature"``.
            state: The state string; None if the entity does not exist.
            attributes: The entity's attributes. They are copied.
            last_changed: When the state last changed.
            last_updated: When the state or an attribute last changed.
        """
        self._entity_id = entity_id
        self._state = None if state is None else str(state)
        self._attributes: dict[str, Any] = dict(attributes or {}) if state is not None else {}
        self._last_changed = last_changed if state is not None else None
        self._last_updated = last_updated if state is not None else None

    # --- Properties ---------------------------------------------------------------

    @property
    def entity_id(self) -> str:
        """Full entity ID, such as ``"sensor.temperature"``."""
        return self._entity_id

    @property
    def exists(self) -> bool:
        """False if the host has no such entity."""
        return self._state is not None

    @property
    def state(self) -> str | None:
        """The raw state string; None if the entity does not exist."""
        return self._state

    @property
    def attributes(self) -> dict[str, Any]:
        """All attributes; empty if the entity does not exist."""
        return dict(self._attributes)

    @property
    def last_changed(self) -> datetime | None:
        """When the state last changed."""
        return self._last_changed

    @property
    def last_updated(self) -> datetime | None:
        """When the state or an attribute last changed."""
        return self._last_updated

    def __getitem__(self, attribute: str) -> Any:
        """Return one attribute; None if it is missing or the entity does not exist."""
        return self._attributes.get(attribute)

    # --- Comparisons --------------------------------------------------------------

    def _operand(self) -> EntityOperand | None:
        """Return the entity as the expression evaluator sees it; None if it does not exist."""
        if self._state is None:
            return None
        return EntityOperand(self._entity_id, self._state, self._attributes)

    def _compare(self, comparison: Callable[[Any, Any], bool], other: Any) -> bool:
        """Compare the state with a value by the conversion rules of expressions.

        As in an expression, a comparison with an unusable value is false:
        the entity is missing, or its state cannot be converted.
        """
        mine = self._operand()
        if isinstance(other, HAAnimEntity):
            other = other._operand()  # pylint: disable=protected-access
        if mine is None or other is None:
            return False
        try:
            return compare(comparison, mine, other)
        except Unusable:
            return False

    def __eq__(self, other: object) -> bool:
        """Compare the state for equality."""
        return self._compare(operator.eq, other)

    def __ne__(self, other: object) -> bool:
        """Compare the state for inequality. False, like every comparison, if a value is unusable."""
        return self._compare(operator.ne, other)

    def __lt__(self, other: Any) -> bool:
        """Compare the state with ``<``."""
        return self._compare(operator.lt, other)

    def __le__(self, other: Any) -> bool:
        """Compare the state with ``<=``."""
        return self._compare(operator.le, other)

    def __gt__(self, other: Any) -> bool:
        """Compare the state with ``>``."""
        return self._compare(operator.gt, other)

    def __ge__(self, other: Any) -> bool:
        """Compare the state with ``>=``."""
        return self._compare(operator.ge, other)

    def __contains__(self, item: Any) -> bool:
        """Test whether a string is part of the state: ``"alert" in entity``."""
        mine = self._operand()
        if isinstance(item, HAAnimEntity):
            item = item._operand()  # pylint: disable=protected-access
        if mine is None or item is None:
            return False
        try:
            return contains(mine, item)
        except Unusable:
            return False

    def __bool__(self) -> bool:
        """Return the state as a boolean: True for on/true, False for off/false and for anything else."""
        mine = self._operand()
        if mine is None:
            return False
        try:
            return truth(mine)
        except Unusable:
            return False

    # --- Conversions --------------------------------------------------------------

    def _require_state(self) -> str:
        """Return the state string, or raise if the entity does not exist."""
        if self._state is None:
            raise NonExistingEntityError(self._entity_id)
        return self._state

    def __float__(self) -> float:
        """Convert the state to a float.

        Raises:
            ValueError: If the state is not numeric (``unavailable``, say).
            NonExistingEntityError: If the entity does not exist.
        """
        state = self._require_state()
        try:
            return float(state)
        except ValueError:
            raise ValueError(f"{self._entity_id} is '{state}', which is not a number") from None

    def __int__(self) -> int:
        """Convert the state to an int, truncating: ``int()`` of a state of ``3.7`` is 3.

        Raises:
            ValueError: If the state is not numeric.
            NonExistingEntityError: If the entity does not exist.
        """
        return int(float(self))

    def __str__(self) -> str:
        """Return the state string; the empty string if the entity does not exist."""
        return self._state if self._state is not None else ""

    def __repr__(self) -> str:
        """Describe the snapshot."""
        if self._state is None:
            return f"HAAnimEntity({self._entity_id!r}, missing)"
        return f"HAAnimEntity({self._entity_id!r}, state={self._state!r})"

    # --- String methods, applied to the state string ------------------------------

    def upper(self) -> str:
        """Return the state in upper case."""
        return self._require_state().upper()

    def lower(self) -> str:
        """Return the state in lower case."""
        return self._require_state().lower()

    def strip(self, chars: str | None = None) -> str:
        """Return the state without leading and trailing whitespace, or the given characters."""
        return self._require_state().strip(chars)

    def startswith(self, prefix: str | tuple[str, ...]) -> bool:
        """Return whether the state starts with a prefix."""
        return self._require_state().startswith(prefix)

    def endswith(self, suffix: str | tuple[str, ...]) -> bool:
        """Return whether the state ends with a suffix."""
        return self._require_state().endswith(suffix)

    def split(self, sep: str | None = None, maxsplit: int = -1) -> list[str]:
        """Split the state into a list."""
        return self._require_state().split(sep, maxsplit)
