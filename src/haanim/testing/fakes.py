"""In-memory implementations of the host interfaces, for tests.

Each fake implements one protocol from ``haanim.interfaces`` and adds methods a
test uses to drive it (set a state, fire an event, register a service) and to
inspect what the engine did (service calls made, events fired).
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from haanim.engine.errors import NonExistingAutomationError, ServiceCallError
from haanim.interfaces import (
    AssetSigner,
    AutomationTimes,
    CardSink,
    FileSystem,
    Host,
    IssueReporter,
    StorageBackend,
)
from haanim.types import EventData, ServiceInfo, StateChangedEvent, StateVal

if TYPE_CHECKING:
    from haanim.engine.automation_context import AutomationContext

__all__ = [
    "FakeAutomationRegistry",
    "FakeClock",
    "FakeEventBus",
    "FakeAssetSigner",
    "FakeCardSink",
    "FakeFileSystem",
    "FakeIssueReporter",
    "FakeServiceCaller",
    "FakeStateProvider",
    "FakeStorage",
    "FakeSunProvider",
    "LocalFileSystem",
    "ServiceCallRecord",
    "make_host",
]

T = TypeVar("T")

DEFAULT_NOW = datetime(2025, 1, 6, 12, 0, 0, tzinfo=timezone.utc)
"""Where a FakeClock starts unless told otherwise: Monday 6 January 2025, noon UTC."""


SETTLE_ITERATIONS = 100
"""How many times FakeClock yields to the event loop to let woken tasks run.

After a timer fires, the tasks it wakes need turns on the event loop before
they reach their next wait. There is no public way to ask the loop whether it
has anything left to run, so the clock yields a fixed number of times. The
number is far more than any chain of awaits in the engine needs.
"""


def _resolve(future: asyncio.Future[None]) -> None:
    """Complete a future unless it is already finished or cancelled."""
    if not future.done():
        future.set_result(None)


class _FakeTimer:
    """A callback scheduled on a FakeClock; satisfies ``haanim.interfaces.TimerHandle``."""

    def __init__(self, when: datetime, sequence: int, callback: Callable[[], Any]) -> None:
        self.when = when
        self.sequence = sequence
        self._callback: Callable[[], Any] | None = callback

    def cancel(self) -> None:
        """Stop the callback from running."""
        self._callback = None

    @property
    def active(self) -> bool:
        """Whether the callback is still waiting to run."""
        return self._callback is not None

    def fire(self) -> None:
        """Run the callback once."""
        callback, self._callback = self._callback, None
        if callback is not None:
            callback()


class FakeClock:
    """A clock that only moves when a test moves it.

    ``sleep``, ``call_later``, ``call_at`` and ``wait_for`` register timers.
    Nothing happens to them until the test calls ``advance``, which moves the
    time forward, runs every timer that falls due in order, and lets the tasks
    they wake run.
    """

    def __init__(self, now: datetime = DEFAULT_NOW) -> None:
        """Initialize the clock.

        Args:
            now: The starting time. Must be timezone-aware.

        Raises:
            ValueError: If ``now`` has no time zone.
        """
        if now.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware datetime")
        # Kept as an instant in UTC and shown in the starting time's zone, so that
        # moving the clock is elapsed time also across a daylight saving change
        self._zone = now.tzinfo
        self._now = now.astimezone(timezone.utc)
        self._timers: list[_FakeTimer] = []
        self._sequence = 0

    # --- Clock protocol ---------------------------------------------------------

    def now(self) -> datetime:
        """Return the current fake time, in the time zone the clock was started in."""
        return self._now.astimezone(self._zone)

    async def sleep(self, seconds: float) -> None:
        """Suspend the caller until the clock has been advanced by ``seconds``."""
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        timer = self.call_later(seconds, lambda: _resolve(future))
        try:
            await future
        finally:
            timer.cancel()

    def call_later(self, delay: float, callback: Callable[[], Any]) -> _FakeTimer:
        """Schedule ``callback`` for when the clock has been advanced by ``delay`` seconds."""
        return self.call_at(self._now + timedelta(seconds=max(delay, 0.0)), callback)

    def call_at(self, when: datetime, callback: Callable[[], Any]) -> _FakeTimer:
        """Schedule ``callback`` for when the clock reaches ``when``.

        Raises:
            ValueError: If ``when`` has no time zone.
        """
        if when.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware datetime")
        self._sequence += 1
        timer = _FakeTimer(max(when.astimezone(timezone.utc), self._now), self._sequence, callback)
        self._timers.append(timer)
        return timer

    async def wait_for(self, awaitable: Awaitable[T], timeout: float) -> T:
        """Wait for an awaitable until the clock has been advanced by ``timeout`` seconds.

        Raises:
            TimeoutError: If the clock passed the timeout before the awaitable finished.
        """
        task: asyncio.Future[T] = asyncio.ensure_future(awaitable)
        if timeout <= 0:
            await asyncio.sleep(0)
            if task.done():
                return task.result()
            await self._cancel(task)
            raise TimeoutError

        timed_out: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        timer = self.call_later(timeout, lambda: _resolve(timed_out))
        try:
            waiting: set[asyncio.Future[Any]] = {task, timed_out}
            await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            await self._cancel(task)
            raise
        finally:
            timer.cancel()
            timed_out.cancel()

        if task.done():
            return task.result()
        await self._cancel(task)
        raise TimeoutError

    @staticmethod
    async def _cancel(task: asyncio.Future[Any]) -> None:
        """Cancel a task and wait until it has finished cancelling."""
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # pylint: disable=broad-exception-caught
            # The task failed while being cancelled; the timeout or cancellation
            # that caused this is what the caller is told about.
            pass

    # --- Test controls ----------------------------------------------------------

    async def advance(self, delta: timedelta | None = None, **kwargs: float) -> datetime:
        """Move the clock forward, running everything that falls due on the way.

        Timers run in order of their time, and in the order they were scheduled
        when times are equal. Before each timer runs, the clock is set to that
        timer's time, so code woken by it sees the right ``now()``. After each
        one, woken tasks get to run, which lets them schedule further timers
        inside the same advance (an interval loop fires repeatedly, for example).

        ``advance()`` with no arguments moves no time; it runs timers that are
        already due and lets pending tasks run.

        Args:
            delta: How far to move, or pass ``timedelta`` keyword arguments instead.
            **kwargs: Keyword arguments for ``timedelta``, e.g. ``minutes=5``.

        Returns:
            The new time.

        Raises:
            ValueError: If the clock would move backwards.
        """
        step = (delta or timedelta()) + timedelta(**kwargs)
        if step < timedelta():
            raise ValueError("FakeClock cannot move backwards")
        target = self._now + step

        await self.settle()
        while (timer := self._next_due(target)) is not None:
            self._now = timer.when
            timer.fire()
            await self.settle()
        self._now = target
        return self.now()

    async def settle(self) -> None:
        """Let tasks that are ready to run do so, without moving time."""
        for _ in range(SETTLE_ITERATIONS):
            await asyncio.sleep(0)

    def _next_due(self, target: datetime) -> _FakeTimer | None:
        """Remove and return the earliest active timer due at or before ``target``."""
        self._timers = [timer for timer in self._timers if timer.active]
        due = [timer for timer in self._timers if timer.when <= target]
        if not due:
            return None
        timer = min(due, key=lambda candidate: (candidate.when, candidate.sequence))
        self._timers.remove(timer)
        return timer

    @property
    def pending_timers(self) -> int:
        """The number of timers waiting to run, including sleeps and timeouts."""
        return sum(1 for timer in self._timers if timer.active)


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

    def fire(
        self, event_type: str, event_data: dict[str, Any] | None = None, *, user_id: str | None = None
    ) -> None:
        """Fire an event and deliver it to subscribers and one-time listeners.

        One-time listeners that are coroutine functions are scheduled on the
        running event loop.

        Args:
            event_type: The type of the event.
            event_data: The data of the event.
            user_id: The user that caused the event, for tests of ``user_id``.
        """
        self._counter += 1
        event = EventData(
            event_type=event_type,
            data=dict(event_data or {}),
            origin="LOCAL",
            time_fired=self._clock.now(),
            context_id=f"fake-context-{self._counter}",
            context_parent_id=None,
            context_user_id=user_id,
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
        self._files: dict[Path, tuple[str | bytes, datetime]] = {}
        self._unreadable: set[Path] = set()

    # --- FileSystem protocol ----------------------------------------------------

    def exists(self, path: Path) -> bool:
        """Return whether the file or directory exists."""
        return Path(path) in self._files or self.is_dir(path)

    def modified_time(self, path: Path) -> datetime:
        """Return when the file was last written.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        return self._entry(path)[1]

    def size(self, path: Path) -> int:
        """Return the size of the file's contents in bytes.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        return len(self._bytes(path))

    async def read_text(self, path: Path) -> str:
        """Return the file's contents.

        Raises:
            FileNotFoundError: If the file does not exist.
            PermissionError: If the file was marked unreadable.
        """
        if Path(path) in self._unreadable:
            raise PermissionError(f"Permission denied: {path}")
        return self._bytes(path).decode("utf-8")

    async def read_bytes(self, path: Path) -> bytes:
        """Return the file's contents as bytes.

        Raises:
            FileNotFoundError: If the file does not exist.
            PermissionError: If the file was marked unreadable.
        """
        if Path(path) in self._unreadable:
            raise PermissionError(f"Permission denied: {path}")
        return self._bytes(path)

    def is_dir(self, path: Path) -> bool:
        """Return whether the path is a directory: something that has files below it."""
        return any(Path(path) in file.parents for file in self._files)

    async def list_dir(self, path: Path) -> list[Path]:
        """Return the files and directories directly in a directory, sorted.

        Raises:
            FileNotFoundError: If the path is not a directory.
        """
        directory = Path(path)
        if not self.is_dir(directory):
            raise FileNotFoundError(f"No such directory: {path}")
        depth = len(directory.parts)
        return sorted({Path(*file.parts[: depth + 1]) for file in self._files if directory in file.parents})

    def _bytes(self, path: Path) -> bytes:
        content = self._entry(path)[0]
        return content.encode("utf-8") if isinstance(content, str) else content

    def _entry(self, path: Path) -> tuple[str | bytes, datetime]:
        try:
            return self._files[Path(path)]
        except KeyError:
            raise FileNotFoundError(f"No such file: {path}") from None

    # --- Test controls ----------------------------------------------------------

    def write(self, path: Path | str, content: str | bytes) -> None:
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
        return datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc)

    def size(self, path: Path) -> int:
        """Return the size of the file in bytes."""
        return Path(path).stat().st_size

    async def read_text(self, path: Path) -> str:
        """Return the file's contents decoded as UTF-8."""
        return Path(path).read_text(encoding="utf-8")

    async def read_bytes(self, path: Path) -> bytes:
        """Return the file's contents."""
        return Path(path).read_bytes()

    def is_dir(self, path: Path) -> bool:
        """Return whether the path is an existing directory."""
        return Path(path).is_dir()

    async def list_dir(self, path: Path) -> list[Path]:
        """Return the files and directories directly in a directory, sorted."""
        return sorted(Path(path).iterdir())


class FakeAssetSigner:
    """Signs URL paths by adding the lifetime, so a test can read it back."""

    def __init__(self) -> None:
        """Initialize with nothing signed."""
        self.signed: list[tuple[str, float]] = []
        """``(path, expires)`` for every signed path, oldest first."""

    def sign(self, path: str, expires: float) -> str:
        """Return the path with ``?signed=<expires>`` added."""
        self.signed.append((path, expires))
        return f"{path}?signed={expires:g}"


class FakeCardSink:
    """Card content held in memory."""

    def __init__(self) -> None:
        """Initialize with no cards."""
        self.cards: dict[str, list[dict[str, Any]]] = {}
        """The latest content of each automation's card, by automation ID."""
        self.updates: list[tuple[str, list[dict[str, Any]]]] = []
        """``(automation_id, blocks)`` for every update, oldest first."""

    def card_changed(self, automation_id: str, blocks: list[dict[str, Any]]) -> None:
        """Record an update."""
        self.cards[automation_id] = blocks
        self.updates.append((automation_id, blocks))


class FakeIssueReporter:
    """Issues held in memory."""

    def __init__(self) -> None:
        """Initialize with no issues."""
        self.issues: dict[str, tuple[str, dict[str, str]]] = {}
        """The issues currently raised: ``(key, placeholders)`` by issue ID."""
        self.history: list[tuple[str, str]] = []
        """``("report" | "clear", issue_id)`` for every call, oldest first."""

    def report(self, issue_id: str, key: str, placeholders: dict[str, str]) -> None:
        """Raise or replace an issue."""
        self.issues[issue_id] = (key, dict(placeholders))
        self.history.append(("report", issue_id))

    def clear(self, issue_id: str) -> None:
        """Remove an issue. Does nothing if it is not raised."""
        self.issues.pop(issue_id, None)
        self.history.append(("clear", issue_id))


class FakeStorage:
    """Documents held in memory."""

    def __init__(self) -> None:
        """Initialize with nothing stored."""
        self._documents: dict[str, str] = {}
        self.saves: list[str] = []
        """The key of every save, oldest first."""

    async def load(self, key: str) -> Any:
        """Return a copy of the document saved under a key, or None."""
        text = self._documents.get(key)
        return None if text is None else json.loads(text)

    async def save(self, key: str, data: Any) -> None:
        """Save a copy of a document.

        Raises:
            TypeError: If the data is not a JSON value.
        """
        self._documents[key] = json.dumps(data)
        self.saves.append(key)

    def peek(self, key: str) -> Any:
        """Return what is stored under a key without going through the event loop."""
        text = self._documents.get(key)
        return None if text is None else json.loads(text)


class FakeAutomationRegistry:
    """A set of automations held in memory, recording control calls."""

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._contexts: dict[str, AutomationContext] = {}
        self.states: dict[str, str] = {}
        """State to report for an automation, by ID."""
        self.messages: dict[str, str] = {}
        """Error message to report for an automation, by ID."""
        self.times: dict[str, AutomationTimes] = {}
        self.disabled: set[str] = set()
        """IDs of the automations to report as disabled."""
        self.control_calls: list[tuple[str, str]] = []
        """``(operation, automation_id)`` for every enable/disable/start/stop/restart, oldest first."""

    # --- AutomationRegistry protocol -------------------------------------------

    def get_all_contexts(self) -> list[AutomationContext]:
        """Return the context of every registered automation."""
        return list(self._contexts.values())

    def get_context_by_name(self, automation_id: str) -> AutomationContext | None:
        """Return the context of the automation with the given ID, or ``None``."""
        return self._contexts.get(automation_id)

    async def async_call_action(
        self,
        automation_id: str,
        action_name: str,
        data: dict[str, Any] | None = None,
        *,
        caller: str | None = None,
    ) -> Any:
        """Call an action of a registered automation directly.

        Raises:
            NonExistingAutomationError: If no such automation is registered.
            ActionNotFoundError: If the automation has no such action.
        """
        context = self._contexts.get(automation_id)
        if context is None:
            raise NonExistingAutomationError(automation_id)
        return await context.run_action(action_name, data, caller=caller)

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

    def automation_state(self, automation_id: str) -> str:
        """Return the state set for an automation; ``on`` for a registered one, else ``unavailable``."""
        default = "on" if automation_id in self._contexts else "unavailable"
        return self.states.get(automation_id, default)

    def automation_message(self, automation_id: str) -> str | None:
        """Return the message set for an automation."""
        return self.messages.get(automation_id)

    def is_automation_enabled(self, automation_id: str) -> bool:
        """Return whether an automation is enabled; True unless it was disabled."""
        return automation_id not in self.disabled

    def automation_times(self, automation_id: str) -> AutomationTimes:
        """Return the times set for an automation in ``times``; all None otherwise."""
        return self.times.get(automation_id, AutomationTimes())

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
    issues: IssueReporter | None = None,
    storage: StorageBackend | None = None,
    hass: Any = None,
    asset_signer: AssetSigner | None = None,
    cards: CardSink | None = None,
) -> Host:
    """Build a Host from fakes.

    Fakes that are not passed are created. The created state provider, event
    bus and file system share the host's clock. ``hass`` is what automations
    get from ``import hass``; pass a stand-in to test an automation that uses it.

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
        issues=issues or FakeIssueReporter(),
        storage=storage or FakeStorage(),
        hass=hass,
        asset_signer=asset_signer or FakeAssetSigner(),
        cards=cards or FakeCardSink(),
    )
