"""Interfaces between the engine and its host.

The engine never talks to Home Assistant directly. Everything it needs from the
outside world is described by a protocol in this module and passed in through a
constructor, bundled in a ``Host``. The Home Assistant integration supplies real
implementations (``custom_components/haanim/ha``); ``haanim.testing.fakes``
supplies in-memory ones for tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from haanim.types import EventData, ServiceInfo, StateChangedEvent, StateVal

if TYPE_CHECKING:
    from haanim.engine.automation_context import AutomationContext

__all__ = [
    "AutomationRegistry",
    "Clock",
    "EventBus",
    "FileSystem",
    "Host",
    "ServiceCaller",
    "StateProvider",
    "SunProvider",
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


class Clock(Protocol):
    """Source of the current time."""

    def now(self) -> datetime:
        """Return the current time as a timezone-aware datetime in the host's time zone."""


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
    """

    states: StateProvider
    events: EventBus
    services: ServiceCaller
    clock: Clock
    sun: SunProvider
    files: FileSystem
