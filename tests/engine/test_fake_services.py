"""Tests for FakeServiceCaller: which services give a response, responses computed per call, and fields."""

from __future__ import annotations

from typing import Any

import pytest

from haanim.const import ResponseSupport
from haanim.engine.errors import ServiceCallError
from haanim.testing import FakeServiceCaller


def describe(services: FakeServiceCaller, name: str) -> ResponseSupport:
    return next(info.supports_response for info in services.services() if info.name == name)


# --- Which services give a response -------------------------------------------------


def test_response_support_follows_the_response() -> None:
    """A service registered with a response may give one; without, it gives none, as most services."""
    services = FakeServiceCaller()
    services.register("weather", "get_forecast", response={"ok": True})
    services.register("light", "turn_on")
    assert describe(services, "get_forecast") is ResponseSupport.OPTIONAL
    assert describe(services, "turn_on") is ResponseSupport.NONE


def test_response_support_is_a_string() -> None:
    services = FakeServiceCaller()
    services.register("weather", "get_forecast", response={"ok": True}, supports_response="only")
    assert describe(services, "get_forecast") == "only"


async def test_a_service_without_responses_returns_none_when_asked() -> None:
    """HAAnim's proxy always asks; Home Assistant's caller then asks only services that can respond."""
    services = FakeServiceCaller()
    services.register("recorder", "import_statistics")
    assert await services.async_call("recorder", "import_statistics", {}, return_response=True) is None


async def test_a_service_that_only_responds_must_be_asked() -> None:
    services = FakeServiceCaller()
    services.register("weather", "get_forecast", response={"ok": True}, supports_response=ResponseSupport.ONLY)
    with pytest.raises(ServiceCallError, match="must be called asking for its response"):
        await services.async_call("weather", "get_forecast", {})
    assert await services.async_call("weather", "get_forecast", {}, return_response=True) == {"ok": True}


def test_a_response_for_a_service_without_responses_is_a_mistake() -> None:
    services = FakeServiceCaller()
    with pytest.raises(ValueError, match="gives no response"):
        services.register("light", "turn_on", response={"ok": True}, supports_response="none")


async def test_an_optional_service_without_a_response_returns_none() -> None:
    services = FakeServiceCaller()
    services.register("script", "run", supports_response="optional")
    assert await services.async_call("script", "run", {}, return_response=True) is None


# --- Responses computed per call ----------------------------------------------------


async def test_a_function_computes_the_response_from_the_call() -> None:
    def window(start: str, end: str, **_: Any) -> dict[str, Any]:
        return {"rows": [start, end]}

    services = FakeServiceCaller()
    services.register("recorder", "get_statistics", response=window)
    result = await services.async_call(
        "recorder", "get_statistics", {"start": "2025-01", "end": "2025-02", "period": "month"}, return_response=True
    )
    assert result == {"rows": ["2025-01", "2025-02"]}
    assert describe(services, "get_statistics") is ResponseSupport.OPTIONAL


async def test_an_async_function_computes_the_response() -> None:
    async def double(value: int) -> dict[str, Any]:
        return {"value": value * 2}

    services = FakeServiceCaller()
    services.register("math", "double", response=double)
    assert await services.async_call("math", "double", {"value": 4}, return_response=True) == {"value": 8}


async def test_a_function_that_raises_fails_the_call() -> None:
    def refuse(**_: Any) -> dict[str, Any]:
        raise RuntimeError("window too large")

    services = FakeServiceCaller()
    services.register("recorder", "get_statistics", response=refuse)
    with pytest.raises(ServiceCallError, match="window too large"):
        await services.async_call("recorder", "get_statistics", {}, return_response=True)
    assert len(services.calls) == 1


async def test_the_function_runs_even_when_no_response_is_asked() -> None:
    """The service runs either way; only the response is dropped, so a failure still fails the call."""
    seen: list[dict[str, Any]] = []

    def record(**data: Any) -> dict[str, Any]:
        seen.append(data)
        return {"ok": True}

    services = FakeServiceCaller()
    services.register("script", "run", response=record)
    assert await services.async_call("script", "run", {"x": 1}) is None
    assert seen == [{"x": 1}]


# --- Fields -------------------------------------------------------------------------


async def test_declared_fields_reject_other_keys() -> None:
    """As Home Assistant's schema does: a stray return_response field is refused."""
    services = FakeServiceCaller()
    services.register("recorder", "import_statistics", fields={"statistic_id": {}, "stats": {}})
    with pytest.raises(ServiceCallError, match="extra keys not allowed: return_response"):
        await services.async_call(
            "recorder", "import_statistics", {"statistic_id": "sensor.x", "stats": [], "return_response": True}
        )
    await services.async_call("recorder", "import_statistics", {"statistic_id": "sensor.x", "stats": []})


async def test_targets_are_always_allowed() -> None:
    services = FakeServiceCaller()
    services.register("light", "turn_on", fields={"brightness": {}})
    await services.async_call("light", "turn_on", {"entity_id": "light.hall", "area_id": "hall", "brightness": 3})


async def test_without_declared_fields_any_key_is_accepted() -> None:
    services = FakeServiceCaller()
    services.register("light", "turn_on")
    await services.async_call("light", "turn_on", {"anything": 1})
