"""Data types shared between the engine and its host.

These are plain Python types with no dependency on Home Assistant. The host
(the Home Assistant integration, or the fakes in ``haanim.testing``) creates
them and the engine consumes them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

STATE_UNAVAILABLE = "unavailable"
STATE_UNKNOWN = "unknown"


class RawState(Protocol):
    """The attributes StateVal reads from a host's state object."""

    @property
    def entity_id(self) -> str:
        """Entity ID."""

    @property
    def state(self) -> str:
        """State value."""

    @property
    def attributes(self) -> Any:
        """Mapping of attribute names to values."""

    @property
    def last_changed(self) -> datetime:
        """When the state last changed."""

    @property
    def last_updated(self) -> datetime:
        """When the state or an attribute last changed."""


@dataclass
class StateChangedEvent:
    """Data class representing a state changed event.

    Used for strongly typed state change notifications in queues.
    """

    entity_id: str
    old_state: StateVal | None
    new_state: StateVal


class StateVal:
    """Wrapper class for entity states.

    Provides convenient access to entity state values and attributes,
    with helper methods for type conversion.
    """

    def __init__(self, state: RawState | None, entity_id: str | None = None) -> None:
        """Initialize a StateVal wrapper.

        Args:
            state: The host's state object, or None if entity not found.
            entity_id: The entity ID (used when state is None).
        """
        self._state = state
        self._entity_id = entity_id or (state.entity_id if state else None)

    @property
    def state(self) -> str | None:
        """Get the state value as a string.

        Returns:
            The state value, or None if unavailable.
        """
        if self._state is None:
            return None
        return self._state.state

    @property
    def entity_id(self) -> str | None:
        """Get the entity ID.

        Returns:
            The entity ID.
        """
        return self._entity_id

    @property
    def attributes(self) -> dict[str, Any]:
        """Get all state attributes.

        Returns:
            Dictionary of attributes.
        """
        if self._state is None:
            return {}
        return dict(self._state.attributes)

    @property
    def last_changed(self) -> datetime | None:
        """Get the time the state last changed.

        Returns:
            Datetime of last change.
        """
        if self._state is None:
            return None
        return self._state.last_changed

    @property
    def last_updated(self) -> datetime | None:
        """Get the time the state was last updated.

        Returns:
            Datetime of last update.
        """
        if self._state is None:
            return None
        return self._state.last_updated

    def __str__(self) -> str:
        """Get string representation (the state value).

        Returns:
            The state value as string.
        """
        return self.state or ""

    def __repr__(self) -> str:
        """Get detailed representation.

        Returns:
            Detailed string representation.
        """
        return f"StateVal({self._entity_id}={self.state})"

    def __eq__(self, other: Any) -> bool:
        """Compare state value equality.

        Args:
            other: Value to compare with.

        Returns:
            True if state equals other.
        """
        if isinstance(other, StateVal):
            return self.state == other.state
        return self.state == str(other)

    def __bool__(self) -> bool:
        """Boolean evaluation of state.

        Returns:
            True if state is truthy (not None, unavailable, unknown, off, false, 0).
        """
        if self._state is None:
            return False
        state = self.state
        if state in (None, STATE_UNAVAILABLE, STATE_UNKNOWN, "off", "false", "0", ""):
            return False
        return True

    def __getattr__(self, name: str) -> Any:
        """Get a state attribute by name.

        Args:
            name: Attribute name.

        Returns:
            Attribute value.

        Raises:
            AttributeError: If attribute not found.
        """
        if name.startswith("_"):
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")
        if self._state is None:
            raise AttributeError(f"Entity '{self._entity_id}' not found")
        if name in self._state.attributes:
            return self._state.attributes[name]
        raise AttributeError(f"Entity '{self._entity_id}' has no attribute '{name}'")

    def get(self, attr: str, default: Any = None) -> Any:
        """Get an attribute with a default value.

        Args:
            attr: Attribute name.
            default: Default value if not found.

        Returns:
            Attribute value or default.
        """
        if self._state is None:
            return default
        return self._state.attributes.get(attr, default)

    def as_int(self, default: int = 0) -> int:
        """Convert state to integer.

        Args:
            default: Default value if conversion fails.

        Returns:
            State as integer.
        """
        try:
            return int(float(self.state or default))
        except (ValueError, TypeError):
            return default

    def as_float(self, default: float = 0.0) -> float:
        """Convert state to float.

        Args:
            default: Default value if conversion fails.

        Returns:
            State as float.
        """
        try:
            return float(self.state or default)
        except (ValueError, TypeError):
            return default

    def as_bool(self) -> bool:
        """Convert state to boolean.

        Returns:
            State as boolean.
        """
        if self.state in ("on", "true", "yes", "1", "home", "open"):
            return True
        return False

    def as_datetime(self) -> datetime | None:
        """Convert state to datetime.

        Returns:
            State as datetime, or None if conversion fails.
        """
        try:
            return datetime.fromisoformat(self.state or "")
        except (ValueError, TypeError):
            return None

    def is_available(self) -> bool:
        """Check if the entity state is available.

        Returns:
            True if state is not unavailable or unknown.
        """
        return self.state not in (None, STATE_UNAVAILABLE, STATE_UNKNOWN)


@dataclass
class EventData:
    """Data class representing an event notification.

    Used for strongly typed event notifications in queues.
    """

    event_type: str
    data: dict[str, Any]
    origin: str | None
    time_fired: datetime
    context_id: str
    context_parent_id: str | None
    context_user_id: str | None


@dataclass(frozen=True)
class ServiceInfo:
    """Description of a service offered by the host.

    Args:
        domain: Service domain, e.g. ``light``.
        name: Service name without the domain, e.g. ``turn_on``.
        description: Human-readable description.
        fields: Parameter details keyed by parameter name.
    """

    domain: str
    name: str
    description: str = ""
    fields: dict[str, Any] = field(default_factory=dict)
