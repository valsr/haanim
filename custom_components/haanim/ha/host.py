"""Home Assistant implementations of the engine's host interfaces.

The engine (the ``haanim`` package) reaches Home Assistant only through the
protocols in ``haanim.interfaces``. This module implements the ones that are
not already provided by ``StateManager`` and ``EventManager`` and bundles them
all into a ``Host``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry
from homeassistant.helpers.service import async_get_all_descriptions
from homeassistant.helpers.sun import get_astral_event_next
from homeassistant.util import dt as dt_util

from custom_components.haanim.const import DOMAIN
from custom_components.haanim.ha.events import EventManager
from custom_components.haanim.ha.state import StateManager
from haanim.engine.errors import ServiceCallError
from haanim.interfaces import Host
from haanim.types import ServiceInfo

T = TypeVar("T")

__all__ = ["HAClock", "HAFileSystem", "HAServiceCaller", "HASunProvider", "build_host"]


class HAServiceCaller:
    """Service discovery and calls through Home Assistant's service registry."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the service caller.

        Args:
            hass: Home Assistant instance.
        """
        self._hass = hass
        self._descriptions: dict[str, dict[str, Any]] = {}

    async def async_refresh_descriptions(self) -> None:
        """Load the service descriptions used by ``services()``.

        Home Assistant only provides descriptions asynchronously, so they are
        cached here. Services registered after the last refresh are still
        listed by ``services()``, with an empty description.
        """
        self._descriptions = await async_get_all_descriptions(self._hass)

    def has_service(self, domain: str, service: str) -> bool:
        """Return whether the service exists."""
        return self._hass.services.has_service(domain, service)

    def services(self) -> list[ServiceInfo]:
        """Return a description of every registered service."""
        result: list[ServiceInfo] = []
        for domain, names in self._hass.services.async_services().items():
            for name in names:
                description = self._descriptions.get(domain, {}).get(name) or {}
                result.append(
                    ServiceInfo(
                        domain=domain,
                        name=name,
                        description=description.get("description", "") or "",
                        fields=dict(description.get("fields", {}) or {}),
                    )
                )
        return result

    async def async_call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any] | None = None,
        *,
        return_response: bool = False,
    ) -> dict[str, Any] | None:
        """Call a service and wait for it to finish.

        Raises:
            ServiceCallError: If Home Assistant reports the call as failed.
        """
        try:
            response = await self._hass.services.async_call(
                domain,
                service,
                data or {},
                blocking=True,
                return_response=return_response,
            )
        except HomeAssistantError as err:
            raise ServiceCallError(domain, service, str(err)) from err
        return response if isinstance(response, dict) else None


class HAClock:
    """Real time, in Home Assistant's configured time zone, on the running event loop."""

    def now(self) -> datetime:
        """Return the current time as a timezone-aware datetime."""
        return dt_util.now()

    async def sleep(self, seconds: float) -> None:
        """Suspend the caller for the given time."""
        await asyncio.sleep(max(seconds, 0.0))

    def call_later(self, delay: float, callback: Callable[[], Any]) -> asyncio.TimerHandle:
        """Call ``callback`` once, ``delay`` seconds from now."""
        return asyncio.get_running_loop().call_later(max(delay, 0.0), callback)

    def call_at(self, when: datetime, callback: Callable[[], Any]) -> asyncio.TimerHandle:
        """Call ``callback`` once, at the given timezone-aware time."""
        return self.call_later((when - self.now()).total_seconds(), callback)

    async def wait_for(self, awaitable: Awaitable[T], timeout: float) -> T:
        """Wait for an awaitable, giving up after ``timeout`` seconds.

        Raises:
            TimeoutError: If the awaitable did not finish in time.
        """
        return await asyncio.wait_for(awaitable, timeout=max(timeout, 0.0))


class HASunProvider:
    """Sunrise and sunset times for Home Assistant's configured location."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the sun provider.

        Args:
            hass: Home Assistant instance.
        """
        self._hass = hass

    def next_event(self, event: str, after: datetime) -> datetime | None:
        """Return the next ``"sunrise"`` or ``"sunset"`` after the given time."""
        return get_astral_event_next(self._hass, event, after)


class HAFileSystem:
    """File access that reads through Home Assistant's executor."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the file system.

        Args:
            hass: Home Assistant instance.
        """
        self._hass = hass

    def exists(self, path: Path) -> bool:
        """Return whether the path exists."""
        return path.exists()

    def modified_time(self, path: Path) -> datetime:
        """Return when the file was last modified."""
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

    async def read_text(self, path: Path) -> str:
        """Return the file's contents decoded as UTF-8."""
        return await self._hass.async_add_executor_job(_read_text, path)

    def is_dir(self, path: Path) -> bool:
        """Return whether the path is an existing directory."""
        return path.is_dir()

    async def list_dir(self, path: Path) -> list[Path]:
        """Return the files and directories directly in a directory, sorted."""
        return await self._hass.async_add_executor_job(_list_dir, path)


def _read_text(path: Path) -> str:
    """Read a file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def _list_dir(path: Path) -> list[Path]:
    """List a directory in sorted order."""
    return sorted(path.iterdir())


class HAIssueReporter:
    """Reports problems as Home Assistant repair issues."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the reporter.

        Args:
            hass: Home Assistant instance.
        """
        self._hass = hass

    def report(self, issue_id: str, key: str, placeholders: dict[str, str]) -> None:
        """Create or update a repair issue.

        The owner fixes these by renaming or removing a folder, so they are
        not fixable from the UI and disappear when ``clear`` is called.
        """
        issue_registry.async_create_issue(
            self._hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=issue_registry.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders=placeholders,
        )

    def clear(self, issue_id: str) -> None:
        """Delete a repair issue. Does nothing if it does not exist."""
        issue_registry.async_delete_issue(self._hass, DOMAIN, issue_id)


def build_host(hass: HomeAssistant, state_manager: StateManager, event_manager: EventManager) -> Host:
    """Bundle the Home Assistant implementations into a Host.

    Args:
        hass: Home Assistant instance.
        state_manager: The integration's state manager.
        event_manager: The integration's event manager.

    Returns:
        A Host backed by Home Assistant.
    """
    return Host(
        states=state_manager,
        events=event_manager,
        services=HAServiceCaller(hass),
        clock=HAClock(),
        sun=HASunProvider(hass),
        files=HAFileSystem(hass),
        issues=HAIssueReporter(hass),
        hass=hass,
    )
