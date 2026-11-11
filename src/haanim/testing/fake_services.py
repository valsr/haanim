"""In-memory services for tests: a fake ServiceCaller that records every call."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from haanim.const import ResponseSupport
from haanim.engine.errors import ServiceCallError
from haanim.types import ServiceInfo

__all__ = ["AlwaysThereServices", "FakeServiceCaller", "Response", "ServiceCallRecord"]

ResponseData = dict[str, Any] | None
Response = ResponseData | Callable[..., ResponseData | Awaitable[ResponseData]]
"""What a fake service responds: data, or a function called with the call's data as keyword arguments."""

TARGET_FIELDS = frozenset({"entity_id", "device_id", "area_id", "floor_id", "label_id"})
"""Keys Home Assistant accepts on any service besides its declared fields."""


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
        self._responses: dict[tuple[str, str], Response] = {}
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
        """Record the call and return the stubbed response, as Home Assistant's caller does.

        A service that gives no response returns None even when asked; one that only
        responds fails unless asked. A response function runs on every call.

        Raises:
            ServiceCallError: If the service is not registered, was set to fail, must be
                asked for its response, gets a key it does not declare, or its response
                function raises.
        """
        key = (domain, service)
        data = dict(data or {})
        self.calls.append(ServiceCallRecord(domain, service, dict(data), return_response))
        info = self._services.get(key)
        if info is None:
            raise ServiceCallError(domain, service, "service not found")
        if key in self._failures:
            raise ServiceCallError(domain, service, self._failures[key])
        if info.fields and (extra := sorted(set(data) - set(info.fields) - TARGET_FIELDS)):
            raise ServiceCallError(domain, service, f"extra keys not allowed: {', '.join(extra)}")
        if info.supports_response is ResponseSupport.ONLY and not return_response:
            raise ServiceCallError(domain, service, "the service must be called asking for its response")
        response = await self._respond(key, data)
        if not return_response or info.supports_response is ResponseSupport.NONE:
            return None
        return response

    async def _respond(self, key: tuple[str, str], data: dict[str, Any]) -> ResponseData:
        """Return the stubbed response, calling its function with the call's data."""
        response = self._responses.get(key)
        if not callable(response):
            return response
        try:
            result = response(**data)
            if inspect.isawaitable(result):
                result = await result
        except Exception as err:  # pylint: disable=broad-exception-caught
            raise ServiceCallError(*key, str(err) or type(err).__name__) from err
        return result

    # --- Test controls ----------------------------------------------------------

    def register(
        self,
        domain: str,
        service: str,
        *,
        description: str = "",
        fields: dict[str, Any] | None = None,
        response: Response = None,
        supports_response: ResponseSupport | str | None = None,
    ) -> None:
        """Register a service, replacing any previous registration.

        Args:
            domain: Service domain.
            service: Service name.
            description: Description reported by ``services()``.
            fields: Parameter details reported by ``services()``. When given, a
                call with any other key fails, as Home Assistant's schemas do
                (target keys such as ``entity_id`` are always allowed).
            response: Response data returned to callers that ask for it, or a
                function (it may be a coroutine function) called with the
                call's data as keyword arguments that returns it. A function
                that raises makes the call fail.
            supports_response: Whether the service gives a response: ``"none"``,
                ``"optional"`` or ``"only"``. Defaults to ``"optional"`` with a
                response and ``"none"`` without.

        Raises:
            ValueError: If a service that gives no response is given one.
        """
        if supports_response is None:
            support = ResponseSupport.NONE if response is None else ResponseSupport.OPTIONAL
        else:
            support = ResponseSupport(supports_response)
        if support is ResponseSupport.NONE and response is not None:
            raise ValueError(f"{domain}.{service} gives no response, so it cannot be given one")
        key = (domain, service)
        self._services[key] = ServiceInfo(domain, service, description, dict(fields or {}), support)
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
