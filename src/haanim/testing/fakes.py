"""In-memory implementations of the host interfaces, for tests.

Each fake implements one protocol from ``haanim.interfaces`` and adds methods a
test uses to drive it (set a state, fire an event, register a service) and to
inspect what the engine did (service calls made, events fired).
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from haanim.engine.errors import ActionNotFoundError, NonExistingAutomationError, ServiceCallError
from haanim.interfaces import FileSystem, Host
from haanim.types import EventData, ServiceInfo, StateChangedEvent, StateVal

if TYPE_CHECKING:
    from haanim.engine.automation_context import AutomationContext

__all__ = [
    "FakeAutomationRegistry",
    "FakeClock",
    "FakeEventBus",
    "FakeFileSystem",
    "FakeServiceCaller",
    "FakeStateProvider",
    "FakeSunProvider",
    "LocalFileSystem",
    "ServiceCallRecord",
    "make_host",
]

DEFAULT_NOW = datetime(2025, 1, 6, 12, 0, 0, tzinfo=timezone.utc)
"""Where a FakeClock starts unless told otherwise: Monday 6 January 2025, noon UTC."""


class FakeClock:
    """A clock that only moves when a test moves it."""

    def __init__(self, now: datetime = DEFAULT_NOW) -> None:
        """Initialize the clock.

        Args:
            now: The starting time. Must be timezone-aware.

        Raises:
            ValueError: If ``now`` has no time zone.
        """
        self._now = self._require_aware(now)

    @staticmethod
    def _require_aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware datetime")
        return value

    def now(self) -> datetime:
        """Return the current fake time."""
        return self._now

    def set(self, now: datetime) -> None:
        """Jump to the given time.

        Raises:
            ValueError: If ``now`` has no time zone.
        """
        self._now = self._require_aware(now)

    def advance(self, delta: timedelta | None = None, **kwargs: float) -> datetime:
        """Move the clock forward and return the new time.

        Args:
            delta: How far to move, or pass ``timedelta`` keyword arguments instead.
            **kwargs: Keyword arguments for ``timedelta``, e.g. ``minutes=5``.

        Raises:
            ValueError: If the clock would move backwards.
        """
        step = (delta or timedelta()) + timedelta(**kwargs)
        if step < timedelta():
            raise ValueError("FakeClock cannot move backwards")
        self._now += step
        return self._now


@dataclass
class _FakeRawState:
    """State object held by FakeStateProvider; satisfies ``haanim.types.RawState``."""

    entity_id: str
    state: str
    attributes: dict[str, Any]
    last_changed: datetime
    last_updated: datetime


class FakeStateProvider:
    """Entity states held in memory."""

    def __init__(self, clock: FakeClock | None = None) -> None:
        """Initialize the provider.

        Args:
            clock: Clock used to stamp state changes. A new FakeClock if omitted.
        """
        self._clock = clock or FakeClock()
        self._states: dict[str, _FakeRawState] = {}
        self._listeners: dict[str, list[asyncio.Queue[StateChangedEvent | None]]] = {}
        self._global_listeners: list[asyncio.Queue[StateChangedEvent | None]] = []

    # --- StateProvider protocol -------------------------------------------------

    def get(self, entity_id: str) -> StateVal:
        """Return the current state of an entity."""
        return StateVal(self._states.get(entity_id), entity_id)

    def exists(self, entity_id: str) -> bool:
        """Return whether the entity exists."""
        return entity_id in self._states

    def subscribe(self, entity_id: str | None = None) -> asyncio.Queue[StateChangedEvent | None]:
        """Subscribe to changes of one entity, or of all entities."""
        queue: asyncio.Queue[StateChangedEvent | None] = asyncio.Queue()
        if entity_id:
            self._listeners.setdefault(entity_id, []).append(queue)
        else:
            self._global_listeners.append(queue)
        return queue

    def unsubscribe(
        self, queue: asyncio.Queue[StateChangedEvent | None], entity_id: str | None = None
    ) -> None:
        """Remove a subscription."""
        listeners = self._listeners.get(entity_id, []) if entity_id else self._global_listeners
        if queue in listeners:
            listeners.remove(queue)

    # --- Test controls ----------------------------------------------------------

    def set_state(self, entity_id: str, state: str, attributes: dict[str, Any] | None = None) -> None:
        """Create or change an entity and notify subscribers.

        ``last_changed`` moves only when the state value changes; ``last_updated``
        moves on every call.

        Args:
            entity_id: The entity ID.
            state: The new state value.
            attributes: The new attributes. Replaces the old ones; empty if omitted.
        """
        now = self._clock.now()
        old = self._states.get(entity_id)
        last_changed = old.last_changed if old and old.state == state else now
        new = _FakeRawState(entity_id, state, dict(attributes or {}), last_changed, now)
        self._states[entity_id] = new

        notification = StateChangedEvent(
            entity_id=entity_id,
            old_state=StateVal(old, entity_id) if old else None,
            new_state=StateVal(new, entity_id),
        )
        for queue in [*self._listeners.get(entity_id, []), *self._global_listeners]:
            queue.put_nowait(notification)

    def remove(self, entity_id: str) -> None:
        """Remove an entity without notifying subscribers. Does nothing if it is missing."""
        self._states.pop(entity_id, None)

    def subscriber_count(self, entity_id: str | None = None) -> int:
        """Return the number of subscriptions for one entity, or of global ones."""
        return len(self._listeners.get(entity_id, []) if entity_id else self._global_listeners)


class FakeEventBus:
    """An event bus held in memory."""

    def __init__(self, clock: FakeClock | None = None) -> None:
        """Initialize the bus.

        Args:
            clock: Clock used to stamp fired events. A new FakeClock if omitted.
        """
        self._clock = clock or FakeClock()
        self._listeners: dict[str, list[tuple[asyncio.Queue[EventData | None], dict[str, Any] | None]]] = {}
        self._global_listeners: list[asyncio.Queue[EventData | None]] = []
        self._once: dict[str, list[Callable[[Any], Any]]] = {}
        self._counter = 0
        self.fired: list[EventData] = []
        """Every event fired on this bus, oldest first."""

    # --- EventBus protocol ------------------------------------------------------

    def subscribe(
        self,
        event_type: str | None = None,
        event_filter: dict[str, Any] | None = None,
    ) -> asyncio.Queue[EventData | None]:
        """Subscribe to one event type, or to all events."""
        queue: asyncio.Queue[EventData | None] = asyncio.Queue()
        if event_type:
            self._listeners.setdefault(event_type, []).append((queue, event_filter))
        else:
            self._global_listeners.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[EventData | None], event_type: str | None = None) -> None:
        """Remove a subscription."""
        if event_type:
            self._listeners[event_type] = [
                entry for entry in self._listeners.get(event_type, []) if entry[0] is not queue
            ]
        elif queue in self._global_listeners:
            self._global_listeners.remove(queue)

    def fire(self, event_type: str, event_data: dict[str, Any] | None = None) -> None:
        """Fire an event and deliver it to subscribers and one-time listeners.

        One-time listeners that are coroutine functions are scheduled on the
        running event loop.
        """
        self._counter += 1
        event = EventData(
            event_type=event_type,
            data=dict(event_data or {}),
            origin="LOCAL",
            time_fired=self._clock.now(),
            context_id=f"fake-context-{self._counter}",
            context_parent_id=None,
            context_user_id=None,
        )
        self.fired.append(event)

        for queue, event_filter in self._listeners.get(event_type, []):
            if all(event.data.get(key) == value for key, value in (event_filter or {}).items()):
                queue.put_nowait(event)
        for queue in self._global_listeners:
            queue.put_nowait(event)

        for callback_func in self._once.pop(event_type, []):
            result = callback_func(event)
            if inspect.isawaitable(result):
                asyncio.ensure_future(result)

    def listen_once(self, event_type: str, callback_func: Callable[[Any], Any]) -> Callable[[], None]:
        """Call ``callback_func`` the next time the event fires."""
        self._once.setdefault(event_type, []).append(callback_func)

        def cancel() -> None:
            listeners = self._once.get(event_type, [])
            if callback_func in listeners:
                listeners.remove(callback_func)

        return cancel

    # --- Test controls ----------------------------------------------------------

    def fired_types(self) -> list[str]:
        """Return the type of every fired event, oldest first."""
        return [event.event_type for event in self.fired]


@dataclass(frozen=True)
class ServiceCallRecord:
    """One service call made through a FakeServiceCaller.

    Args:
        domain: Service domain.
        service: Service name.
        data: Data passed to the call.
        return_response: Whether the caller asked for response data.
    """

    domain: str
    service: str
    data: dict[str, Any] = field(default_factory=dict)
    return_response: bool = False


class FakeServiceCaller:
    """Services held in memory, recording every call."""

    def __init__(self) -> None:
        """Initialize with no services registered."""
        self._services: dict[tuple[str, str], ServiceInfo] = {}
        self._responses: dict[tuple[str, str], dict[str, Any] | None] = {}
        self._failures: dict[tuple[str, str], str] = {}
        self.calls: list[ServiceCallRecord] = []
        """Every call made, oldest first, including calls that failed."""

    # --- ServiceCaller protocol -------------------------------------------------

    def has_service(self, domain: str, service: str) -> bool:
        """Return whether the service is registered."""
        return (domain, service) in self._services

    def services(self) -> list[ServiceInfo]:
        """Return a description of every registered service."""
        return list(self._services.values())

    async def async_call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any] | None = None,
        *,
        return_response: bool = False,
    ) -> dict[str, Any] | None:
        """Record the call and return the stubbed response.

        Raises:
            ServiceCallError: If the service is not registered or was set to fail.
        """
        key = (domain, service)
        self.calls.append(ServiceCallRecord(domain, service, dict(data or {}), return_response))
        if key not in self._services:
            raise ServiceCallError(domain, service, "service not found")
        if key in self._failures:
            raise ServiceCallError(domain, service, self._failures[key])
        return self._responses.get(key) if return_response else None

    # --- Test controls ----------------------------------------------------------

    def register(
        self,
        domain: str,
        service: str,
        *,
        description: str = "",
        fields: dict[str, Any] | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        """Register a service, replacing any previous registration.

        Args:
            domain: Service domain.
            service: Service name.
            description: Description reported by ``services()``.
            fields: Parameter details reported by ``services()``.
            response: Response data returned to callers that ask for it.
        """
        key = (domain, service)
        self._services[key] = ServiceInfo(domain, service, description, dict(fields or {}))
        self._responses[key] = response
        self._failures.pop(key, None)

    def fail(self, domain: str, service: str, reason: str = "failed") -> None:
        """Make calls to a registered service raise ``ServiceCallError``.

        Raises:
            KeyError: If the service is not registered.
        """
        key = (domain, service)
        if key not in self._services:
            raise KeyError(f"{domain}.{service} is not registered")
        self._failures[key] = reason

    def calls_to(self, domain: str, service: str) -> list[ServiceCallRecord]:
        """Return the calls made to one service, oldest first."""
        return [call for call in self.calls if (call.domain, call.service) == (domain, service)]


class FakeSunProvider:
    """Sunrise and sunset at fixed times of day."""

    def __init__(self, sunrise: str | None = "07:00", sunset: str | None = "19:00") -> None:
        """Initialize the provider.

        Args:
            sunrise: Time of sunrise as ``HH:MM``, or ``None`` for no sunrise.
            sunset: Time of sunset as ``HH:MM``, or ``None`` for no sunset.
        """
        self._times: dict[str, tuple[int, int] | None] = {
            "sunrise": self._parse(sunrise),
            "sunset": self._parse(sunset),
        }

    @staticmethod
    def _parse(value: str | None) -> tuple[int, int] | None:
        if value is None:
            return None
        hour, minute = value.split(":")
        return int(hour), int(minute)

    def next_event(self, event: str, after: datetime) -> datetime | None:
        """Return the next occurrence of the event strictly after the given time.

        The result is in the time zone of ``after``.

        Raises:
            ValueError: If ``event`` is not ``"sunrise"`` or ``"sunset"``.
        """
        if event not in self._times:
            raise ValueError(f"Unknown sun event: {event}")
        time_of_day = self._times[event]
        if time_of_day is None:
            return None
        candidate = after.replace(hour=time_of_day[0], minute=time_of_day[1], second=0, microsecond=0)
        if candidate <= after:
            candidate += timedelta(days=1)
        return candidate


class FakeFileSystem:
    """Files held in memory."""

    def __init__(self, clock: FakeClock | None = None) -> None:
        """Initialize an empty file system.

        Args:
            clock: Clock used to stamp writes. A new FakeClock if omitted.
        """
        self._clock = clock or FakeClock()
        self._files: dict[Path, tuple[str, datetime]] = {}
        self._unreadable: set[Path] = set()

    # --- FileSystem protocol ----------------------------------------------------

    def exists(self, path: Path) -> bool:
        """Return whether the file exists."""
        return Path(path) in self._files

    def modified_time(self, path: Path) -> datetime:
        """Return when the file was last written.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        return self._entry(path)[1]

    async def read_text(self, path: Path) -> str:
        """Return the file's contents.

        Raises:
            FileNotFoundError: If the file does not exist.
            PermissionError: If the file was marked unreadable.
        """
        if Path(path) in self._unreadable:
            raise PermissionError(f"Permission denied: {path}")
        return self._entry(path)[0]

    def _entry(self, path: Path) -> tuple[str, datetime]:
        try:
            return self._files[Path(path)]
        except KeyError:
            raise FileNotFoundError(f"No such file: {path}") from None

    # --- Test controls ----------------------------------------------------------

    def write(self, path: Path | str, content: str) -> None:
        """Create or replace a file, stamping it with the clock's current time."""
        self._files[Path(path)] = (content, self._clock.now())

    def delete(self, path: Path | str) -> None:
        """Remove a file. Does nothing if it is missing."""
        self._files.pop(Path(path), None)
        self._unreadable.discard(Path(path))

    def make_unreadable(self, path: Path | str) -> None:
        """Make reads of an existing file raise ``PermissionError``."""
        self._unreadable.add(Path(path))


class LocalFileSystem:
    """Real files on disk, read synchronously.

    Not a fake: it is the simplest real implementation of the FileSystem
    protocol, for tests that keep automations in a temporary directory.
    Reads block the event loop, which is fine for small files in tests.
    """

    def exists(self, path: Path) -> bool:
        """Return whether the path exists."""
        return Path(path).exists()

    def modified_time(self, path: Path) -> datetime:
        """Return when the file was last modified."""
        return datetime.fromtimestamp(Path(path).stat().st_mtime)

    async def read_text(self, path: Path) -> str:
        """Return the file's contents decoded as UTF-8."""
        return Path(path).read_text(encoding="utf-8")


class FakeAutomationRegistry:
    """A set of automations held in memory, recording control calls."""

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._contexts: dict[str, AutomationContext] = {}
        self.control_calls: list[tuple[str, str]] = []
        """``(operation, automation_id)`` for every enable/disable/start/stop/restart, oldest first."""

    # --- AutomationRegistry protocol -------------------------------------------

    def get_all_contexts(self) -> list[AutomationContext]:
        """Return the context of every registered automation."""
        return list(self._contexts.values())

    def get_context_by_name(self, automation_id: str) -> AutomationContext | None:
        """Return the context of the automation with the given ID, or ``None``."""
        return self._contexts.get(automation_id)

    async def async_call_action(self, automation_id: str, action_name: str, *args: Any, **kwargs: Any) -> Any:
        """Call an action directly on the registered context.

        Raises:
            NonExistingAutomationError: If the automation is not registered.
            ActionNotFoundError: If the automation has no such action.
        """
        context = self._contexts.get(automation_id)
        if context is None:
            raise NonExistingAutomationError(automation_id)
        action = context.get_action(action_name)
        if action is None:
            raise ActionNotFoundError(automation_id, action_name)
        result = action.func(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    async def async_enable_automation(self, automation_id: str) -> None:
        """Record an enable request."""
        self._record("enable", automation_id)

    async def async_disable_automation(self, automation_id: str) -> None:
        """Record a disable request."""
        self._record("disable", automation_id)

    async def async_start_automation(self, automation_id: str) -> None:
        """Record a start request."""
        self._record("start", automation_id)

    async def async_stop_automation(self, automation_id: str) -> None:
        """Record a stop request."""
        self._record("stop", automation_id)

    async def async_restart_automation(self, automation_id: str) -> None:
        """Record a restart request."""
        self._record("restart", automation_id)

    def _record(self, operation: str, automation_id: str) -> None:
        if automation_id not in self._contexts:
            raise NonExistingAutomationError(automation_id)
        self.control_calls.append((operation, automation_id))

    # --- Test controls ----------------------------------------------------------

    def add(self, context: AutomationContext) -> None:
        """Register an automation context under its automation ID."""
        self._contexts[context.automation_id] = context


def make_host(
    *,
    states: FakeStateProvider | None = None,
    events: FakeEventBus | None = None,
    services: FakeServiceCaller | None = None,
    clock: FakeClock | None = None,
    sun: FakeSunProvider | None = None,
    files: FileSystem | None = None,
) -> Host:
    """Build a Host from fakes.

    Fakes that are not passed are created. The created state provider, event
    bus and file system share the host's clock.

    Returns:
        A Host whose members are the given or created fakes.
    """
    clock = clock or FakeClock()
    return Host(
        states=states or FakeStateProvider(clock),
        events=events or FakeEventBus(clock),
        services=services or FakeServiceCaller(),
        clock=clock,
        sun=sun or FakeSunProvider(),
        files=files or FakeFileSystem(clock),
    )
