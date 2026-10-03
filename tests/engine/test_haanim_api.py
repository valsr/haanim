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
    NonExistingEntityError,
    NonExistingServiceError,
)
from haanim.engine.haanim_api import (
    EntityProxy,
    HAAnim,
    HAAnimAutomationProxy,
    HAAnimServiceCall,
    HAAnimServiceProxy,
    ServiceDomainProxy,
)
from haanim.interfaces import Host
from haanim.testing import FakeAutomationRegistry, FakeServiceCaller, FakeStateProvider, make_host
from tests.engine.helpers import make_context

AUTOMATION_SOURCE = """
@action("Add numbers", description="Adds two numbers")
def add(a, b):
    return a + b

@action
async def greet(name="world"):
    return "hello " + name
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
    return HAAnim(host, "me", registry, str(tmp_path / "storage"))


@pytest.fixture
async def other(registry: FakeAutomationRegistry, tmp_path: Path) -> AutomationContext:
    """A loaded automation called ``other``, added to the registry."""
    path = tmp_path / "other.py"
    path.write_text(AUTOMATION_SOURCE, encoding="utf-8")
    context = make_context(str(path), registry=registry)
    await context.load()
    registry.add(context)
    return context


class TestHAAnimServiceCall:
    """Tests for the service call result object."""

    def test_initial_state(self) -> None:
        """Test a new result is not successful and has no completion time."""
        call_time = datetime(2025, 1, 1, 12, 0)
        result = HAAnimServiceCall("light", "turn_on", call_time)
        assert (result.domain, result.service, result.call_time) == ("light", "turn_on", call_time)
        assert result.success is False
        assert result.complete_time is None
        assert result.error is None
        assert result.error_code is None
        assert result.response_data == {}

    @pytest.mark.parametrize(("response", "expected"), [(None, {}), ({"a": 1}, {"a": 1}), ({}, {})])
    def test_mark_success(self, response: dict[str, Any] | None, expected: dict[str, Any]) -> None:
        """Test mark_success records success, the given completion time and any response."""
        done = datetime(2025, 1, 1, 12, 0, 5)
        result = HAAnimServiceCall("light", "turn_on", datetime(2025, 1, 1, 12, 0))
        result.mark_success(done, response)
        assert result.success is True
        assert result.complete_time == done
        assert result.response_data == expected

    def test_mark_failure(self) -> None:
        """Test mark_failure records the error, code and the given completion time."""
        done = datetime(2025, 1, 1, 12, 0, 5)
        result = HAAnimServiceCall("light", "turn_on", datetime(2025, 1, 1, 12, 0))
        result.mark_failure(done, "boom", "some_code")
        assert result.success is False
        assert result.complete_time == done
        assert (result.error, result.error_code) == ("boom", "some_code")


class TestIdentity:
    """Tests for the automation's own identity."""

    def test_id(self, haa: HAAnim) -> None:
        """Test haa.id is the automation's ID."""
        assert haa.id == "me"


class TestEntityAccess:
    """Tests for reading entities through haa.<domain>."""

    def test_domain_gives_entity_proxy(self, haa: HAAnim) -> None:
        """Test an attribute other than service is an entity proxy for that domain."""
        assert isinstance(haa.sensor, EntityProxy)

    def test_state_by_attribute(self, haa: HAAnim) -> None:
        """Test haa.<domain>.<name> gives the state string."""
        assert haa.sensor.temperature == "21.5"
        assert haa.light.hall == "on"

    def test_missing_entity_state_is_none(self, haa: HAAnim) -> None:
        """Test the state of a missing entity is None."""
        assert haa.sensor.missing is None

    def test_state_and_attributes_by_item(self, haa: HAAnim) -> None:
        """Test haa.<domain>[<name>] gives the state merged with the attributes."""
        assert haa.light["hall"] == {"state": "on", "brightness": 200}

    def test_missing_entity_by_item_raises(self, haa: HAAnim) -> None:
        """Test item access to a missing entity raises NonExistingEntityError."""
        with pytest.raises(NonExistingEntityError) as exc_info:
            haa.sensor["missing"]  # pylint: disable=pointless-statement
        assert exc_info.value.entity_id == "sensor.missing"

    def test_reads_current_state(self, haa: HAAnim, states: FakeStateProvider) -> None:
        """Test each read reflects the entity's state at that moment."""
        states.set_state("sensor.temperature", "30")
        assert haa.sensor.temperature == "30"


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
        metadata = other.get_metadata()
        assert metadata is not None

        assert isinstance(proxy, HAAnimAutomationProxy)
        assert proxy.id == "other"
        assert proxy.file_path == other.automation_path
        assert proxy.load_time == metadata.loaded_at
        assert proxy.actions == ["Add numbers", "greet"]
        assert proxy.state == "off"
        assert proxy.message == ""
        assert proxy.run_time is None
        assert proxy.last_action_time is None
        assert proxy.error_message is None
        assert proxy.is_running() is False
        assert proxy.is_enabled() is True

    async def test_proxy_reflects_metadata_changes(self, haa: HAAnim, other: AutomationContext) -> None:
        """Test a proxy reads the automation's metadata each time."""
        proxy = haa.automation("other")
        metadata = other.get_metadata()
        assert metadata is not None
        started = datetime(2025, 1, 1, 9, 0)

        metadata.state = "on"
        metadata.message = "working"
        metadata.run_time = started
        metadata.last_action_time = started
        metadata.error = "bad thing"
        metadata.enabled = False

        assert proxy.state == "on"
        assert proxy.is_running() is True
        assert proxy.message == "working"
        assert proxy.run_time == started
        assert proxy.last_action_time == started
        assert proxy.error_message == "bad thing"
        assert proxy.is_enabled() is False

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
        assert proxy.is_enabled() is False

    async def test_proxy_for_automation_that_failed_to_load(
        self, registry: FakeAutomationRegistry, tmp_path: Path
    ) -> None:
        """Test a proxy for a context without metadata reports defaults."""
        context = make_context(str(tmp_path / "broken.py"), registry=registry)
        registry.add(context)
        proxy = HAAnimAutomationProxy("broken", registry)
        assert proxy.state == "off"
        assert proxy.message == ""
        assert proxy.load_time is None
        assert proxy.actions == []
        assert proxy.is_enabled() is False


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
        path = tmp_path / "other.py"
        path.write_text(AUTOMATION_SOURCE, encoding="utf-8")
        context = make_context(str(path), registry=registry)
        await context.load()
        registry.add(context)
        own_haa = HAAnim(host, "other", registry, str(tmp_path / "storage"))

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

    @pytest.mark.parametrize("operation", ["enable", "disable", "stop", "restart"])
    async def test_self_control(
        self,
        host: Host,
        other: AutomationContext,
        registry: FakeAutomationRegistry,
        tmp_path: Path,
        operation: str,
    ) -> None:
        """Test haa's own control methods act on the automation that owns the haa instance."""
        own_haa = HAAnim(host, "other", registry, str(tmp_path / "storage"))
        await getattr(own_haa, operation)()
        assert registry.control_calls == [(operation, "other")]


class TestStatusMessage:
    """Tests for haa.set_message()."""

    async def test_set_message(
        self, host: Host, other: AutomationContext, registry: FakeAutomationRegistry, tmp_path: Path
    ) -> None:
        """Test the message is stored on the automation and visible through a proxy."""
        own_haa = HAAnim(host, "other", registry, str(tmp_path / "storage"))
        own_haa.set_message("Starting task...")
        assert own_haa.automation("other").message == "Starting task..."

    def test_set_message_without_context(self, haa: HAAnim) -> None:
        """Test setting a message for an automation that is not registered does nothing."""
        haa.set_message("ignored")


class TestStorage:
    """Tests for persistent variables."""

    def test_storage_directory_created(self, haa: HAAnim, tmp_path: Path) -> None:
        """Test creating a haa instance creates the storage directory."""
        assert haa.id == "me"
        assert (tmp_path / "storage").is_dir()

    def test_get_default(self, haa: HAAnim) -> None:
        """Test an unset variable gives the default, or None."""
        assert haa.get_variable("missing") is None
        assert haa.get_variable("missing", "fallback") == "fallback"

    async def test_set_and_get(self, haa: HAAnim) -> None:
        """Test a set variable is returned."""
        await haa.set_variable("threshold", "25.0")
        assert haa.get_variable("threshold") == "25.0"
        assert haa.get_variable("threshold", "other") == "25.0"

    async def test_written_to_file(self, haa: HAAnim, tmp_path: Path) -> None:
        """Test variables are written to the automation's JSON file."""
        await haa.set_variable("a", "1")
        stored = json.loads((tmp_path / "storage" / "me.json").read_text(encoding="utf-8"))
        assert stored == {"a": "1"}

    async def test_survives_new_instance(
        self, haa: HAAnim, host: Host, registry: FakeAutomationRegistry, tmp_path: Path
    ) -> None:
        """Test a new haa instance for the same automation sees stored variables."""
        await haa.set_variable("a", "1")
        again = HAAnim(host, "me", registry, str(tmp_path / "storage"))
        assert again.get_variable("a") == "1"

    async def test_isolated_per_automation(
        self, haa: HAAnim, host: Host, registry: FakeAutomationRegistry, tmp_path: Path
    ) -> None:
        """Test another automation does not see the variables."""
        await haa.set_variable("a", "1")
        other_haa = HAAnim(host, "someone_else", registry, str(tmp_path / "storage"))
        assert other_haa.get_variable("a") is None

    async def test_unset(self, haa: HAAnim, tmp_path: Path) -> None:
        """Test unset removes one variable and tolerates a missing one."""
        await haa.set_variable("a", "1")
        await haa.set_variable("b", "2")
        await haa.unset_variable("a")
        await haa.unset_variable("never_set")
        assert haa.get_variable("a") is None
        assert haa.get_variable("b") == "2"
        assert json.loads((tmp_path / "storage" / "me.json").read_text(encoding="utf-8")) == {"b": "2"}

    async def test_clear(self, haa: HAAnim, tmp_path: Path) -> None:
        """Test clear removes every variable."""
        await haa.set_variable("a", "1")
        await haa.set_variable("b", "2")
        await haa.clear_variables()
        assert haa.get_variable("a") is None
        assert json.loads((tmp_path / "storage" / "me.json").read_text(encoding="utf-8")) == {}

    def test_corrupt_file_starts_empty(
        self, host: Host, registry: FakeAutomationRegistry, tmp_path: Path
    ) -> None:
        """Test an unreadable storage file is treated as empty."""
        storage = tmp_path / "storage"
        storage.mkdir()
        (storage / "me.json").write_text("{not json", encoding="utf-8")
        haa = HAAnim(host, "me", registry, str(storage))
        assert haa.get_variable("a") is None

    async def test_save_failure_is_logged_not_raised(
        self, haa: HAAnim, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test a failed write keeps the value in memory and logs an error."""
        with patch("haanim.engine.haanim_api.open", side_effect=OSError("disk full"), create=True):
            await haa.set_variable("a", "1")
        assert haa.get_variable("a") == "1"
        assert "Failed to save storage" in caplog.text
