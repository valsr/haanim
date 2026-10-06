"""Tests for service calls from action code.

See "Service Calls", "HAAnimServiceProxy" and "HAAnimServiceCall" in the design.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.errors import NonExistingServiceError
from haanim.engine.haanim_api import HAAnim, HAAnimServiceCall, HAAnimServiceProxy
from haanim.testing import (
    FakeAutomationRegistry,
    FakeClock,
    FakeServiceCaller,
    LocalFileSystem,
    make_host,
)
from haanim.testing.fakes import DEFAULT_NOW
from tests.engine.helpers import automation_file, load_and_run, make_context

PARAM_INFO = {
    "entity_id": {
        "description": "Name(s) of entities to turn on",
        "example": "light.living_room",
        "required": False,
        "selector": {"entity": {"domain": "light"}},
    },
    "brightness": {
        "description": "Brightness value (0-255)",
        "example": 120,
        "required": False,
        "selector": {"number": {"min": 0, "max": 255}},
    },
}


@pytest.fixture
def clock() -> FakeClock:
    """A fake clock."""
    return FakeClock()


@pytest.fixture
def services() -> FakeServiceCaller:
    """Three services: one described, one plain, one that returns a response."""
    caller = FakeServiceCaller()
    caller.register("light", "turn_on", description="Turn on one or more lights", fields=PARAM_INFO)
    caller.register("light", "turn_off")
    caller.register("weather", "get_forecast", response={"forecast": [{"temp": 12}]})
    return caller


@pytest.fixture
def haa(services: FakeServiceCaller, clock: FakeClock, tmp_path: Path) -> HAAnim:
    """The haa instance of an automation."""
    host = make_host(services=services, clock=clock)
    return HAAnim(host, "me", FakeAutomationRegistry())


class TestServiceProxy:
    """Every row of the HAAnimServiceProxy table."""

    def test_domain_and_name(self, haa: HAAnim) -> None:
        """domain is the service domain, name the service without it."""
        proxy = haa.service.light.turn_on
        assert type(proxy) is HAAnimServiceProxy
        assert (proxy.domain, proxy.name) == ("light", "turn_on")

    def test_description(self, haa: HAAnim) -> None:
        """description is the host's description; empty if it has none."""
        assert haa.service.light.turn_on.description == "Turn on one or more lights"
        assert haa.service.light.turn_off.description == ""

    def test_param_info(self, haa: HAAnim) -> None:
        """param_info has the design's structure: details by parameter name."""
        param_info = haa.service.light.turn_on.param_info
        assert param_info == PARAM_INFO
        assert param_info["brightness"]["selector"] == {"number": {"min": 0, "max": 255}}
        assert param_info["entity_id"].get("required", False) is False
        assert haa.service.light.turn_off.param_info == {}

    def test_param_info_is_a_copy(self, haa: HAAnim) -> None:
        """Changing what was handed out does not change the proxy."""
        proxy = haa.service.light.turn_on
        proxy.param_info["brightness"]["example"] = 1
        proxy.param_info.clear()
        assert proxy.param_info == PARAM_INFO

    def test_properties_are_read_only(self, haa: HAAnim) -> None:
        """The proxy describes a service; it cannot be pointed at another."""
        proxy = haa.service.light.turn_on
        for name in ("domain", "name", "description", "param_info"):
            with pytest.raises(AttributeError):
                setattr(proxy, name, "other")

    async def test_call(self, haa: HAAnim, services: FakeServiceCaller) -> None:
        """call(**params) calls the service with the parameters."""
        result = await haa.service.light.turn_on.call(entity_id="light.living_room", brightness=200)
        assert type(result) is HAAnimServiceCall
        (record,) = services.calls
        assert (record.domain, record.service) == ("light", "turn_on")
        assert record.data == {"entity_id": "light.living_room", "brightness": 200}

    async def test_direct_call(self, haa: HAAnim, services: FakeServiceCaller) -> None:
        """The proxy can be called directly, as in haa.service.light.turn_on(...)."""
        result = await haa.service.light.turn_on(
            entity_id=["light.living_room", "light.kitchen"], brightness=150, rgb_color=[255, 0, 0]
        )
        assert result.success is True
        assert services.calls[0].data == {
            "entity_id": ["light.living_room", "light.kitchen"],
            "brightness": 150,
            "rgb_color": [255, 0, 0],
        }

    def test_proxy_of_a_missing_service(self, haa: HAAnim) -> None:
        """Getting a proxy never raises; a missing service has no description or parameters."""
        proxy = haa.service.light.dim
        assert (proxy.domain, proxy.name, proxy.description, proxy.param_info) == ("light", "dim", "", {})
        assert repr(proxy) == "HAAnimServiceProxy('light.dim')"

    def test_private_names_are_not_services(self, haa: HAAnim) -> None:
        """Names with a leading underscore are not looked up as domains or services."""
        with pytest.raises(AttributeError):
            haa.service._hidden  # pylint: disable=pointless-statement,protected-access
        with pytest.raises(AttributeError):
            haa.service.light._hidden  # pylint: disable=pointless-statement,protected-access


class TestServices:
    """haa.services(): every available service as a proxy."""

    def test_lists_every_service(self, haa: HAAnim) -> None:
        """One proxy per service of the host."""
        found = haa.services()
        assert all(type(proxy) is HAAnimServiceProxy for proxy in found)
        assert sorted((proxy.domain, proxy.name) for proxy in found) == [
            ("light", "turn_off"),
            ("light", "turn_on"),
            ("weather", "get_forecast"),
        ]

    def test_find_a_service(self, haa: HAAnim) -> None:
        """The design's example: find a service by domain and name."""
        all_services = haa.services()
        turn_on = next((s for s in all_services if s.domain == "light" and s.name == "turn_on"), None)
        assert turn_on is not None
        assert turn_on.description == "Turn on one or more lights"
        assert next((s for s in all_services if s.name == "dim"), None) is None

    def test_reflects_the_host_now(self, haa: HAAnim, services: FakeServiceCaller) -> None:
        """A service registered later is in the next list."""
        services.register("switch", "toggle")
        assert ("switch", "toggle") in [(proxy.domain, proxy.name) for proxy in haa.services()]


class TestServiceCallResult:
    """Every row of the HAAnimServiceCall table."""

    async def test_success(self, haa: HAAnim) -> None:
        """success is True, error and error_code are None."""
        result = await haa.service.light.turn_on(entity_id="light.living_room")
        assert (result.success, result.error, result.error_code) == (True, None, None)

    async def test_domain_and_service(self, haa: HAAnim) -> None:
        """domain and service name what was called."""
        result = await haa.service.weather.get_forecast()
        assert (result.domain, result.service) == ("weather", "get_forecast")

    async def test_response_data(self, haa: HAAnim) -> None:
        """response_data is the service's response; an empty dictionary if it returned none."""
        assert (await haa.service.weather.get_forecast()).response_data == {"forecast": [{"temp": 12}]}
        assert (await haa.service.light.turn_on()).response_data == {}

    async def test_call_and_complete_time(
        self, haa: HAAnim, services: FakeServiceCaller, clock: FakeClock
    ) -> None:
        """call_time is when the call was made and complete_time when it finished, on HAAnim's clock."""
        original = services.async_call

        async def slow(*args: Any, **kwargs: Any) -> Any:
            await clock.sleep(2.5)
            return await original(*args, **kwargs)

        services.async_call = slow  # type: ignore[method-assign]
        call = asyncio.create_task(haa.service.light.turn_on())
        await clock.advance(seconds=2.5)
        result = await call

        assert result.call_time == DEFAULT_NOW
        assert result.complete_time == DEFAULT_NOW + timedelta(seconds=2.5)
        assert isinstance(result.call_time, datetime) and result.call_time.tzinfo is not None
        # The design's example
        assert (result.complete_time - result.call_time).total_seconds() == 2.5

    async def test_failing_service(self, haa: HAAnim, services: FakeServiceCaller) -> None:
        """A service that fails does not raise: the result carries the error and its code."""
        services.fail("light", "turn_on", "device offline")
        result = await haa.service.light.turn_on(entity_id="light.living_room")

        assert result.success is False
        assert result.error == "device offline"
        assert result.error_code == "home_assistant_error"
        assert result.response_data == {}
        assert result.complete_time is not None
        assert (result.domain, result.service) == ("light", "turn_on")

    async def test_unexpected_host_error(self, haa: HAAnim, services: FakeServiceCaller) -> None:
        """An exception the host did not translate is reported through the result too."""

        async def broken(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("kaboom")

        services.async_call = broken  # type: ignore[method-assign]
        result = await haa.service.light.turn_on()
        assert (result.success, result.error, result.error_code) == (False, "kaboom", "unknown_error")

    async def test_unexpected_error_without_a_message(self, haa: HAAnim, services: FakeServiceCaller) -> None:
        """The error is never empty: the exception's type stands in for a missing message."""

        async def broken(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError

        services.async_call = broken  # type: ignore[method-assign]
        assert (await haa.service.light.turn_on()).error == "RuntimeError"

    async def test_result_cannot_be_changed(self, haa: HAAnim) -> None:
        """The result is a record of what happened."""
        result = await haa.service.light.turn_on()
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.success = False  # type: ignore[misc]

    async def test_no_methods_of_the_old_api(self, haa: HAAnim) -> None:
        """is_success(), is_failure() and get_response() are properties now."""
        result = await haa.service.light.turn_on()
        for name in ("is_success", "is_failure", "get_response", "mark_success", "mark_failure"):
            assert not hasattr(result, name)

    async def test_properties_of_the_table(self, haa: HAAnim) -> None:
        """The result has exactly the properties of the design's table."""
        result = await haa.service.light.turn_on()
        assert {field.name for field in dataclasses.fields(result)} == {
            "success",
            "error",
            "error_code",
            "response_data",
            "call_time",
            "complete_time",
            "domain",
            "service",
        }


class TestMissingService:
    """A call to a service that does not exist raises NonExistingServiceError."""

    async def test_raises(self, haa: HAAnim, services: FakeServiceCaller) -> None:
        """The error names the service, and nothing is called."""
        with pytest.raises(NonExistingServiceError) as exc_info:
            await haa.service.light.dim(entity_id="light.living_room")
        assert (exc_info.value.domain, exc_info.value.service) == ("light", "dim")
        assert services.calls == []

    async def test_raises_for_call_too(self, haa: HAAnim) -> None:
        """call() and the direct call behave the same."""
        with pytest.raises(NonExistingServiceError):
            await haa.service.nowhere.nothing.call()

    async def test_service_registered_after_the_proxy_was_taken(
        self, haa: HAAnim, services: FakeServiceCaller
    ) -> None:
        """Existence is checked when the call is made."""
        proxy = haa.service.switch.toggle
        services.register("switch", "toggle")
        assert (await proxy()).success is True


EXPLORE = """
from haanim import HAAnimServiceCall, HAAnimServiceProxy, NonExistingServiceError, action, haa

@action
async def explore_service(event):
    light_turn_on = haa.service.light.turn_on
    lines = [
        f"Domain: {light_turn_on.domain}",
        f"Name: {light_turn_on.name}",
        f"Description: {light_turn_on.description}",
    ]
    for param_name, param_details in light_turn_on.param_info.items():
        lines.append(f"Parameter: {param_name}")
        lines.append(f"  Description: {param_details.get('description', 'N/A')}")
        lines.append(f"  Required: {param_details.get('required', False)}")
        if 'example' in param_details:
            lines.append(f"  Example: {param_details['example']}")

    result = await light_turn_on.call(entity_id="light.living_room", brightness=200)
    if result.success:
        lines.append("Light turned on successfully")
        lines.append(f"Completed in {(result.complete_time - result.call_time).total_seconds()}s")
    else:
        lines.append(f"Failed to turn on light: {result.error}")
        lines.append(f"Error code: {result.error_code}")
    lines.append(isinstance(light_turn_on, HAAnimServiceProxy) and isinstance(result, HAAnimServiceCall))
    return lines

@action
async def list_services(event):
    return sorted([f"{service.domain}.{service.name}: {service.description}" for service in haa.services()])

@action
async def missing(event):
    try:
        await haa.service.light.dim()
    except NonExistingServiceError as err:
        return f"{err.domain}.{err.service} does not exist"
"""


class TestFromAutomationCode:
    """The design's examples, run by the interpreter."""

    @staticmethod
    async def context(services: FakeServiceCaller, clock: FakeClock, tmp_path: Path) -> Any:
        """Load the example automation."""
        path = automation_file(tmp_path, "explorer")
        path.write_text(EXPLORE, encoding="utf-8")
        context = make_context(
            str(path), host=make_host(services=services, clock=clock, files=LocalFileSystem())
        )
        await load_and_run(context)
        return context

    async def test_explore_service(
        self, services: FakeServiceCaller, clock: FakeClock, tmp_path: Path
    ) -> None:
        """The proxy's properties and a successful call."""
        context = await self.context(services, clock, tmp_path)
        assert await context.run_action("explore_service") == [
            "Domain: light",
            "Name: turn_on",
            "Description: Turn on one or more lights",
            "Parameter: entity_id",
            "  Description: Name(s) of entities to turn on",
            "  Required: False",
            "  Example: light.living_room",
            "Parameter: brightness",
            "  Description: Brightness value (0-255)",
            "  Required: False",
            "  Example: 120",
            "Light turned on successfully",
            "Completed in 0.0s",
            True,
        ]

    async def test_explore_a_failing_service(
        self, services: FakeServiceCaller, clock: FakeClock, tmp_path: Path
    ) -> None:
        """The other branch of the example: the error and its code."""
        services.fail("light", "turn_on", "device offline")
        context = await self.context(services, clock, tmp_path)
        lines = await context.run_action("explore_service")
        assert lines[-3:-1] == ["Failed to turn on light: device offline", "Error code: home_assistant_error"]

    async def test_list_services(self, services: FakeServiceCaller, clock: FakeClock, tmp_path: Path) -> None:
        """haa.services() from action code."""
        context = await self.context(services, clock, tmp_path)
        assert await context.run_action("list_services") == [
            "light.turn_off: ",
            "light.turn_on: Turn on one or more lights",
            "weather.get_forecast: ",
        ]

    async def test_missing_service_can_be_caught(
        self, services: FakeServiceCaller, clock: FakeClock, tmp_path: Path
    ) -> None:
        """NonExistingServiceError is importable from haanim and raised in the action."""
        context = await self.context(services, clock, tmp_path)
        assert await context.run_action("missing") == "light.dim does not exist"
