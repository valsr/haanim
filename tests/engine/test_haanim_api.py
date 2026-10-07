"""Tests for the haa API (engine/haanim_api.py), run against the fake host."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from haanim.engine.automation_context import AutomationContext
from haanim.engine.errors import (
    ActionNotFoundError,
    NonExistingAutomationError,
    NonExistingServiceError,
)
from haanim.engine.haanim_api import (
    HAAnim,
    HAAnimAutomationProxy,
    HAAnimServiceCall,
    HAAnimServiceProxy,
    ServiceDomainProxy,
)
from haanim.interfaces import AutomationTimes, Host
from haanim.testing import FakeAutomationRegistry, FakeServiceCaller, FakeStateProvider, make_host
from tests.engine.helpers import automation_file, load_and_run, make_context

AUTOMATION_SOURCE = """
from haanim import action
@action(name="Add numbers", description="Adds two numbers")
def add(event):
    return event.data["a"] + event.data["b"]

@action
async def greet(event):
    return "hello " + event.data.get("name", "world")
"""


@pytest.fixture
def states() -> FakeStateProvider:
    """Entity states with one sensor and one light."""
    provider = FakeStateProvider()
    provider.set_state("sensor.temperature", "21.5", {"unit_of_measurement": "°C"})
    provider.set_state("light.hall", "on", {"brightness": 200})
    return provider


@pytest.fixture
def services() -> FakeServiceCaller:
    """Services with two light services and one that returns a response."""
    caller = FakeServiceCaller()
    caller.register(
        "light", "turn_on", description="Turn on a light", fields={"brightness": {"required": False}}
    )
    caller.register("light", "turn_off")
    caller.register("weather", "get_forecast", response={"forecast": [1, 2]})
    return caller


@pytest.fixture
def host(states: FakeStateProvider, services: FakeServiceCaller) -> Host:
    """A fake host with the states and services above."""
    return make_host(states=states, services=services)


@pytest.fixture
def registry() -> FakeAutomationRegistry:
    """An empty automation registry."""
    return FakeAutomationRegistry()


@pytest.fixture
def haa(host: Host, registry: FakeAutomationRegistry, tmp_path: Path) -> HAAnim:
    """The haa instance of an automation called ``me``."""
    return HAAnim(host, "me", registry)


@pytest.fixture
async def other(registry: FakeAutomationRegistry, tmp_path: Path) -> AutomationContext:
    """A loaded automation called ``other``, added to the registry."""
    path = automation_file(tmp_path, "other")
    path.write_text(AUTOMATION_SOURCE, encoding="utf-8")
    context = make_context(str(path), registry=registry)
    await load_and_run(context)
    registry.add(context)
    return context


class TestIdentity:
    """Tests for the automation's own identity."""

    def test_id(self, haa: HAAnim) -> None:
        """Test haa.id is the automation's ID."""
        assert haa.id == "me"


class TestServiceAccess:
    """Tests for haa.service and haa.services()."""

    def test_service_accessor_levels(self, haa: HAAnim) -> None:
        """Test haa.service.<domain>.<name> resolves to a service proxy."""
        assert isinstance(haa.service.light, ServiceDomainProxy)
        proxy = haa.service.light.turn_on
        assert isinstance(proxy, HAAnimServiceProxy)
        assert (proxy.domain, proxy.name) == ("light", "turn_on")

    def test_service_via_getattr(self, haa: HAAnim) -> None:
        """Test the service accessor is also reachable through attribute lookup."""
        assert isinstance(getattr(haa, "service").light.turn_on, HAAnimServiceProxy)

    def test_proxy_metadata(self, haa: HAAnim) -> None:
        """Test a proxy carries the service's description and parameter details."""
        proxy = haa.service.light.turn_on
        assert proxy.description == "Turn on a light"
        assert proxy.param_info == {"brightness": {"required": False}}

    def test_proxy_metadata_defaults(self, haa: HAAnim) -> None:
        """Test a service without metadata, or an unknown one, has empty metadata."""
        assert haa.service.light.turn_off.description == ""
        assert haa.service.light.turn_off.param_info == {}
        assert haa.service.light.unknown.description == ""

    def test_services_lists_every_service(self, haa: HAAnim) -> None:
        """Test haa.services() returns a proxy per registered service."""
        proxies = haa.services()
        assert all(isinstance(proxy, HAAnimServiceProxy) for proxy in proxies)
        assert {(proxy.domain, proxy.name) for proxy in proxies} == {
            ("light", "turn_on"),
            ("light", "turn_off"),
            ("weather", "get_forecast"),
        }


class TestServiceCalls:
    """Tests for calling services."""

    async def test_call_success(self, haa: HAAnim, services: FakeServiceCaller) -> None:
        """Test a successful call reaches the host and reports success."""
        result = await haa.service.light.turn_on.call(entity_id="light.hall", brightness=120)

        assert result.success is True
        assert result.error is None
        assert (result.domain, result.service) == ("light", "turn_on")
        assert result.complete_time is not None
        (record,) = services.calls
        assert record.data == {"entity_id": "light.hall", "brightness": 120}
        assert record.return_response is True

    async def test_direct_call(self, haa: HAAnim, services: FakeServiceCaller) -> None:
        """Test calling the proxy itself is the same as call()."""
        result = await haa.service.light.turn_off(entity_id="light.hall")
        assert result.success is True
        assert services.calls_to("light", "turn_off")[0].data == {"entity_id": "light.hall"}

    async def test_response_data(self, haa: HAAnim) -> None:
        """Test response data from the service is on the result."""
        result = await haa.service.weather.get_forecast()
        assert result.response_data == {"forecast": [1, 2]}

    async def test_no_response_data(self, haa: HAAnim) -> None:
        """Test a service without a response gives an empty dictionary."""
        result = await haa.service.light.turn_on()
        assert result.response_data == {}

    async def test_missing_service_raises(self, haa: HAAnim, services: FakeServiceCaller) -> None:
        """Test calling a service that does not exist raises and makes no call."""
        with pytest.raises(NonExistingServiceError) as exc_info:
            await haa.service.light.dim()
        assert (exc_info.value.domain, exc_info.value.service) == ("light", "dim")
        assert services.calls == []

    async def test_failed_service_is_reported_not_raised(
        self, haa: HAAnim, services: FakeServiceCaller
    ) -> None:
        """Test a failing service gives an unsuccessful result with the reason."""
        services.fail("light", "turn_on", "device offline")
        result = await haa.service.light.turn_on()
        assert result.success is False
        assert result.error == "device offline"
        assert result.error_code == "home_assistant_error"
        assert result.complete_time is not None

    async def test_unexpected_error_is_reported_not_raised(
        self, haa: HAAnim, services: FakeServiceCaller
    ) -> None:
        """Test an unexpected exception from the host gives an unsuccessful result."""
        with patch.object(services, "async_call", side_effect=RuntimeError("kaboom")):
            result = await haa.service.light.turn_on()
        assert result.success is False
        assert result.error == "kaboom"
        assert result.error_code == "unknown_error"


class TestOtherAutomations:
    """Tests for haa.automation() and haa.automations()."""

    def test_unknown_automation_raises(self, haa: HAAnim) -> None:
        """Test asking for an automation that does not exist raises."""
        with pytest.raises(NonExistingAutomationError) as exc_info:
            haa.automation("nope")
        assert exc_info.value.automation_id == "nope"

    def test_automations_empty(self, haa: HAAnim) -> None:
        """Test an empty registry gives no proxies."""
        assert haa.automations() == []

    async def test_automation_proxy(self, haa: HAAnim, other: AutomationContext) -> None:
        """Test a proxy describes the loaded automation."""
        proxy = haa.automation("other")
        assert isinstance(proxy, HAAnimAutomationProxy)
        assert proxy.id == "other"
        assert proxy.file_path == other.automation_path
        assert proxy.load_time is None
        assert proxy.actions == ["Add numbers", "greet"]
        assert proxy.state == "on"
        assert proxy.message == ""
        assert proxy.run_time is None
        assert proxy.last_action_time is None
        assert proxy.error_message is None
        assert proxy.is_running() is True
        assert proxy.is_enabled() is True

    async def test_proxy_reflects_changes(
        self, haa: HAAnim, other: AutomationContext, registry: FakeAutomationRegistry
    ) -> None:
        """Test a proxy asks the registry and the automation's metadata each time."""
        proxy = haa.automation("other")
        metadata = other.get_metadata()
        assert metadata is not None
        started = datetime(2025, 1, 1, 9, 0)

        registry.states["other"] = "error"
        registry.messages["other"] = "bad thing"
        registry.disabled.add("other")
        metadata.message = "working"
        registry.times["other"] = AutomationTimes(
            load_time=started, run_time=started, last_action_time=started
        )

        assert proxy.state == "error"
        assert proxy.is_running() is False
        assert proxy.message == "working"
        assert (proxy.load_time, proxy.run_time, proxy.last_action_time) == (started, started, started)
        assert proxy.error_message == "bad thing"
        assert proxy.is_enabled() is False

        registry.states["other"] = "on"
        registry.disabled.clear()
        assert proxy.is_running() is True
        assert proxy.is_enabled() is True

    async def test_automations_lists_all(self, haa: HAAnim, other: AutomationContext) -> None:
        """Test haa.automations() returns a proxy per loaded automation."""
        assert [proxy.id for proxy in haa.automations()] == ["other"]

    def test_proxy_for_unloaded_automation(self, registry: FakeAutomationRegistry) -> None:
        """Test a proxy whose automation has gone reports it as unavailable."""
        proxy = HAAnimAutomationProxy("gone", registry)
        assert proxy.state == "unavailable"
        assert proxy.message == ""
        assert proxy.file_path == ""
        assert proxy.load_time is None
        assert proxy.run_time is None
        assert proxy.actions == []
        assert proxy.last_action_time is None
        assert proxy.error_message is None
        assert proxy.is_running() is False
        # An automation HAAnim has never seen is enabled: that is what a new folder gets.
        assert proxy.is_enabled() is True

    async def test_proxy_for_automation_that_failed_to_load(
        self, registry: FakeAutomationRegistry, tmp_path: Path
    ) -> None:
        """Test a proxy for a context without metadata reports defaults."""
        context = make_context(str(automation_file(tmp_path, "broken")), registry=registry)
        registry.add(context)
        registry.states["broken"] = "error"
        registry.messages["broken"] = "main.py:1: invalid syntax"
        proxy = HAAnimAutomationProxy("broken", registry)
        assert proxy.state == "error"
        assert proxy.error_message == "main.py:1: invalid syntax"
        assert proxy.message == ""
        assert proxy.load_time is None
        assert proxy.actions == []
        assert proxy.is_running() is False


class TestCallingActions:
    """Tests for calling actions through haa and through a proxy."""

    async def test_proxy_call(self, haa: HAAnim, other: AutomationContext) -> None:
        """Test a proxy calls an action of its automation and returns the result."""
        assert await haa.automation("other").call("greet", name="there") == "hello there"

    async def test_proxy_call_unknown_action(self, haa: HAAnim, other: AutomationContext) -> None:
        """Test calling an action that does not exist raises."""
        with pytest.raises(ActionNotFoundError):
            await haa.automation("other").call("missing")

    async def test_call_own_action(
        self, registry: FakeAutomationRegistry, host: Host, tmp_path: Path
    ) -> None:
        """Test haa.call() calls an action of the automation that owns the haa instance."""
        path = automation_file(tmp_path, "other")
        path.write_text(AUTOMATION_SOURCE, encoding="utf-8")
        context = make_context(str(path), registry=registry)
        await load_and_run(context)
        registry.add(context)
        own_haa = HAAnim(host, "other", registry)

        assert await own_haa.call("greet") == "hello world"


class TestControl:
    """Tests for controlling automations."""

    @pytest.mark.parametrize("operation", ["enable", "disable", "start", "stop", "restart"])
    async def test_proxy_control(
        self, haa: HAAnim, other: AutomationContext, registry: FakeAutomationRegistry, operation: str
    ) -> None:
        """Test each proxy control method is passed to the registry for that automation."""
        await getattr(haa.automation("other"), operation)()
        assert registry.control_calls == [(operation, "other")]

    def test_no_self_enable(self, haa: HAAnim) -> None:
        """Test haa has no enable(): a disabled automation is not running and cannot enable itself."""
        assert not hasattr(HAAnim, "enable")
        assert "enable" not in dir(haa)

    @pytest.mark.parametrize("operation", ["disable", "stop", "restart"])
    async def test_self_control(
        self,
        host: Host,
        other: AutomationContext,
        registry: FakeAutomationRegistry,
        tmp_path: Path,
        operation: str,
    ) -> None:
        """Test haa's own control methods act on the automation that owns the haa instance."""
        own_haa = HAAnim(host, "other", registry)
        await getattr(own_haa, operation)()
        assert registry.control_calls == [(operation, "other")]


class TestStatusMessage:
    """Tests for haa.set_message()."""

    async def test_set_message(
        self, host: Host, other: AutomationContext, registry: FakeAutomationRegistry, tmp_path: Path
    ) -> None:
        """Test the message is stored on the automation and visible through a proxy."""
        own_haa = HAAnim(host, "other", registry)
        own_haa.set_message("Starting task...")
        assert own_haa.automation("other").message == "Starting task..."

    def test_set_message_without_context(self, haa: HAAnim) -> None:
        """Test setting a message for an automation that is not registered does nothing."""
        haa.set_message("ignored")
