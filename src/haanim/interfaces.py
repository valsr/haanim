"""Interfaces between the engine and its host.

The engine never talks to Home Assistant directly. Everything it needs from the
outside world is described by a protocol in this module and passed in through a
constructor, bundled in a ``Host``. The Home Assistant integration supplies real
implementations (``custom_components/haanim/ha``); ``haanim.testing.fakes``
supplies in-memory ones for tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from haanim.types import EventData, ServiceInfo, StateChangedEvent, StateVal

if TYPE_CHECKING:
    from haanim.engine.automation_context import AutomationContext

T = TypeVar("T")

__all__ = [
    "AutomationRegistry",
    "Clock",
    "EventBus",
    "FileSystem",
    "Host",
    "IssueReporter",
    "ServiceCaller",
    "StateProvider",
    "SunProvider",
    "TimerHandle",
]


class StateProvider(Protocol):
    """Read entity states and receive their changes."""

    def get(self, entity_id: str) -> StateVal:
        """Return the current state of an entity.

        A missing entity gives a ``StateVal`` whose ``state`` is ``None``.
        """

    def exists(self, entity_id: str) -> bool:
        """Return whether the entity exists."""

    def subscribe(self, entity_id: str | None = None) -> asyncio.Queue[StateChangedEvent | None]:
        """Subscribe to changes of one entity, or of all entities if ``entity_id`` is ``None``.

        The returned queue receives a ``StateChangedEvent`` per change, and
        ``None`` when the provider shuts down.
        """

    def unsubscribe(
        self, queue: asyncio.Queue[StateChangedEvent | None], entity_id: str | None = None
    ) -> None:
        """Remove a subscription. ``entity_id`` must match the value used to subscribe."""


class EventBus(Protocol):
    """Receive and fire events."""

    def subscribe(
        self,
        event_type: str | None = None,
        event_filter: dict[str, Any] | None = None,
    ) -> asyncio.Queue[EventData | None]:
        """Subscribe to one event type, or to all events if ``event_type`` is ``None``.

        With ``event_filter``, only events whose data contains every listed key
        with an equal value are delivered. The queue receives ``None`` when the
        bus shuts down.
        """

    def unsubscribe(self, queue: asyncio.Queue[EventData | None], event_type: str | None = None) -> None:
        """Remove a subscription. ``event_type`` must match the value used to subscribe."""

    def fire(self, event_type: str, event_data: dict[str, Any] | None = None) -> None:
        """Fire an event."""

    def listen_once(self, event_type: str, callback_func: Callable[[Any], Any]) -> Callable[[], None]:
        """Call ``callback_func`` the next time the event fires, then stop listening.

        The callback receives the host's event object and may be a coroutine
        function. Returns a function that cancels the listener.
        """


class ServiceCaller(Protocol):
    """Discover and call services."""

    def has_service(self, domain: str, service: str) -> bool:
        """Return whether the service exists."""

    def services(self) -> list[ServiceInfo]:
        """Return a description of every available service."""

    async def async_call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any] | None = None,
        *,
        return_response: bool = False,
    ) -> dict[str, Any] | None:
        """Call a service and wait for it to finish.

        Returns the service's response data if ``return_response`` is true and
        the service provides one, otherwise ``None``.

        Raises:
            ServiceCallError: If the service fails. A missing service is reported
                the same way; callers that need to tell the two apart check
                ``has_service`` first.
        """


class TimerHandle(Protocol):
    """A scheduled callback that can be cancelled."""

    def cancel(self) -> None:
        """Stop the callback from running. Does nothing if it already ran or was cancelled."""


class Clock(Protocol):
    """Source of time for the engine.

    All time in the engine comes from here: timestamps, delays, scheduled
    callbacks and timeouts. Nothing in the engine reads the system clock or
    calls ``asyncio.sleep`` directly, so a test can replace the clock and
    control time.
    """

    def now(self) -> datetime:
        """Return the current time as a timezone-aware datetime in the host's time zone."""

    async def sleep(self, seconds: float) -> None:
        """Suspend the caller for the given time.

        A value of zero or less yields to the event loop once and returns.
        """

    def call_later(self, delay: float, callback: Callable[[], Any]) -> TimerHandle:
        """Call ``callback`` once, ``delay`` seconds from now.

        The callback is a plain function, not a coroutine function, and is
        called on the event loop. A delay of zero or less means as soon as possible.
        """

    def call_at(self, when: datetime, callback: Callable[[], Any]) -> TimerHandle:
        """Call ``callback`` once, at the given timezone-aware time.

        A time that is not in the future means as soon as possible.
        """

    async def wait_for(self, awaitable: Awaitable[T], timeout: float) -> T:
        """Wait for an awaitable, giving up after ``timeout`` seconds.

        If the time runs out, the awaitable is cancelled and ``TimeoutError``
        is raised. A timeout of zero or less gives up at once unless the
        awaitable is already finished.

        Raises:
            TimeoutError: If the awaitable did not finish in time.
        """


class SunProvider(Protocol):
    """Sunrise and sunset times at the host's location."""

    def next_event(self, event: str, after: datetime) -> datetime | None:
        """Return the next ``"sunrise"`` or ``"sunset"`` after the given time.

        Returns ``None`` if the event cannot be determined.
        """


class FileSystem(Protocol):
    """Read files without blocking the event loop."""

    def exists(self, path: Path) -> bool:
        """Return whether the path exists."""

    def modified_time(self, path: Path) -> datetime:
        """Return when the file was last modified.

        Raises:
            OSError: If the file cannot be inspected.
        """

    async def read_text(self, path: Path) -> str:
        """Return the file's contents decoded as UTF-8.

        Raises:
            OSError: If the file cannot be read.
        """

    def is_dir(self, path: Path) -> bool:
        """Return whether the path is an existing directory."""

    async def list_dir(self, path: Path) -> list[Path]:
        """Return the paths of the files and directories directly in a directory, sorted.

        Raises:
            OSError: If the path is not a directory that can be read.
        """


class IssueReporter(Protocol):
    """Problems the owner has to fix, shown to them until they are fixed.

    In Home Assistant these are repair issues.
    """

    def report(self, issue_id: str, key: str, placeholders: dict[str, str]) -> None:
        """Raise an issue, or update it if it is already raised.

        Args:
            issue_id: Identifies the issue; reporting the same ID again replaces it.
            key: The kind of issue, which selects the text shown.
            placeholders: Values to put into that text.
        """

    def clear(self, issue_id: str) -> None:
        """Remove an issue. Does nothing if it is not raised."""


class AutomationRegistry(Protocol):
    """The set of loaded automations and the operations on them.

    This is what an automation's ``haa`` object uses to reach other automations.
    """

    def get_all_contexts(self) -> list[AutomationContext]:
        """Return the context of every loaded automation."""

    def get_context_by_name(self, automation_id: str) -> AutomationContext | None:
        """Return the context of the automation with the given ID, or ``None``."""

    async def async_call_action(self, automation_id: str, action_name: str, *args: Any, **kwargs: Any) -> Any:
        """Call an action of an automation and return its result."""

    async def async_enable_automation(self, automation_id: str) -> None:
        """Enable and start an automation."""

    async def async_disable_automation(self, automation_id: str) -> None:
        """Stop and disable an automation."""

    async def async_start_automation(self, automation_id: str) -> None:
        """Start an automation."""

    async def async_stop_automation(self, automation_id: str) -> None:
        """Stop an automation."""

    async def async_restart_automation(self, automation_id: str) -> None:
        """Restart an automation."""


@dataclass(frozen=True)
class Host:
    """Everything the engine needs from the system it runs in.

    Args:
        states: Entity state access.
        events: Event bus.
        services: Service discovery and calls.
        clock: Current time.
        sun: Sunrise and sunset times.
        files: File access.
        issues: Where problems the owner has to fix are reported.
        hass: What an automation gets from ``import hass``: the running Home
            Assistant instance. The engine never uses it itself. None if the
            host has none to offer.
    """

    states: StateProvider
    events: EventBus
    services: ServiceCaller
    clock: Clock
    sun: SunProvider
    files: FileSystem
    issues: IssueReporter
    hass: Any = None
