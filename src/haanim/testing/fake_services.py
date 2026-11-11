"""In-memory services for tests: a fake ServiceCaller that records every call."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from haanim.engine.errors import ServiceCallError
from haanim.types import ServiceInfo

__all__ = ["AlwaysThereServices", "FakeServiceCaller", "ServiceCallRecord"]


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


class AlwaysThereServices(FakeServiceCaller):
    """Services that all exist unless a test says one is missing."""

    def __init__(self) -> None:
        super().__init__()
        self._missing: set[tuple[str, str]] = set()

    def has_service(self, domain: str, service: str) -> bool:
        """Return whether the service exists: every one does that was not marked missing."""
        return (domain, service) not in self._missing

    async def async_call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any] | None = None,
        *,
        return_response: bool = False,
    ) -> dict[str, Any] | None:
        """Record the call; a service nobody stubbed succeeds without a response."""
        key = (domain, service)
        if key not in self._missing and key not in self._services:
            self.register(domain, service)
        return await super().async_call(domain, service, data, return_response=return_response)

    def remove(self, domain: str, service: str) -> None:
        """Make a service not exist."""
        key = (domain, service)
        self._missing.add(key)
        self._services.pop(key, None)
        self._responses.pop(key, None)
        self._failures.pop(key, None)

    def restore(self, domain: str, service: str) -> None:
        """Make a service exist again."""
        self._missing.discard((domain, service))
