"""Contract tests: each host interface behaves the same in its fake and Home Assistant forms.

Every test here runs twice, once against the in-memory fake from ``haanim.testing``
and once against the Home Assistant implementation from
``custom_components.haanim.ha``. A test that passes for one and fails for the
other means the fake no longer describes the real thing.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import pytest
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from custom_components.haanim.ha.events import EventManager
from custom_components.haanim.ha.host import HAClock, HAFileSystem, HAServiceCaller, HASunProvider
from custom_components.haanim.ha.state import StateManager
from haanim.engine.errors import ServiceCallError
from haanim.interfaces import Clock, EventBus, FileSystem, ServiceCaller, StateProvider, SunProvider
from haanim.testing import (
    FakeClock,
    FakeEventBus,
    FakeFileSystem,
    FakeServiceCaller,
    FakeStateProvider,
    FakeSunProvider,
)

IMPLEMENTATIONS = ["fake", "home_assistant"]


# --- StateProvider ---------------------------------------------------------------


class SetState(Protocol):
    """Sets an entity's state in the system under test and waits for it to be delivered."""

    async def __call__(self, entity_id: str, state: str, attributes: dict[str, Any] | None = None) -> None:
        """Set the state."""


@dataclass
class StateSetup:
    """A state provider and the way to change states behind it."""

    provider: StateProvider
    set_state: SetState


@pytest.fixture(params=IMPLEMENTATIONS)
async def state_setup(request: pytest.FixtureRequest, hass: HomeAssistant) -> AsyncGenerator[StateSetup]:
    """A state provider in each implementation."""
    if request.param == "fake":
        fake = FakeStateProvider()

        async def set_fake(entity_id: str, state: str, attributes: dict[str, Any] | None = None) -> None:
            fake.set_state(entity_id, state, attributes)

        yield StateSetup(fake, set_fake)
        return

    manager = StateManager(hass)
    await manager.async_setup()

    async def set_real(entity_id: str, state: str, attributes: dict[str, Any] | None = None) -> None:
        hass.states.async_set(entity_id, state, attributes)
        await hass.async_block_till_done()

    yield StateSetup(manager, set_real)
    await manager.async_teardown()


class TestStateProviderContract:
    """Behaviour every StateProvider must have."""

    async def test_missing_entity(self, state_setup: StateSetup) -> None:
        """Test a missing entity does not exist and has state None."""
        provider = state_setup.provider
        assert provider.exists("sensor.contract_missing") is False
        value = provider.get("sensor.contract_missing")
        assert value.state is None
        assert value.entity_id == "sensor.contract_missing"
        assert value.attributes == {}

    async def test_get_existing_entity(self, state_setup: StateSetup) -> None:
        """Test an existing entity is returned with its state, attributes and timestamps."""
        await state_setup.set_state("sensor.contract_temp", "21.5", {"unit": "C"})
        provider = state_setup.provider
        assert provider.exists("sensor.contract_temp") is True
        value = provider.get("sensor.contract_temp")
        assert value.state == "21.5"
        assert value.entity_id == "sensor.contract_temp"
        assert value.attributes == {"unit": "C"}
        assert isinstance(value.last_changed, datetime) and value.last_changed.tzinfo is not None
        assert isinstance(value.last_updated, datetime) and value.last_updated.tzinfo is not None

    async def test_entity_subscription(self, state_setup: StateSetup) -> None:
        """Test an entity subscriber gets each change with old and new state."""
        await state_setup.set_state("sensor.contract_temp", "20")
        queue = state_setup.provider.subscribe("sensor.contract_temp")

        await state_setup.set_state("sensor.contract_temp", "21")

        event = queue.get_nowait()
        assert event is not None
        assert event.entity_id == "sensor.contract_temp"
        assert event.old_state is not None and event.old_state.state == "20"
        assert event.new_state.state == "21"
        assert queue.empty()

    async def test_new_entity_has_no_old_state(self, state_setup: StateSetup) -> None:
        """Test the change that creates an entity has old_state None."""
        queue = state_setup.provider.subscribe("sensor.contract_new")
        await state_setup.set_state("sensor.contract_new", "1")
        event = queue.get_nowait()
        assert event is not None and event.old_state is None

    async def test_entity_subscription_ignores_other_entities(self, state_setup: StateSetup) -> None:
        """Test a subscription to one entity is not notified about another."""
        queue = state_setup.provider.subscribe("sensor.contract_temp")
        await state_setup.set_state("sensor.contract_other", "1")
        assert queue.empty()

    async def test_global_subscription(self, state_setup: StateSetup) -> None:
        """Test a subscription without an entity ID gets changes of every entity."""
        queue = state_setup.provider.subscribe()
        await state_setup.set_state("sensor.contract_a", "1")
        await state_setup.set_state("sensor.contract_b", "2")
        received = []
        while not queue.empty():
            event = queue.get_nowait()
            assert event is not None
            received.append(event.entity_id)
        assert received == ["sensor.contract_a", "sensor.contract_b"]

    @pytest.mark.parametrize("entity_id", ["sensor.contract_temp", None])
    async def test_unsubscribe(self, state_setup: StateSetup, entity_id: str | None) -> None:
        """Test no changes are delivered after unsubscribing."""
        queue = state_setup.provider.subscribe(entity_id)
        state_setup.provider.unsubscribe(queue, entity_id)
        await state_setup.set_state("sensor.contract_temp", "20")
        assert queue.empty()


# --- EventBus --------------------------------------------------------------------


@dataclass
class EventSetup:
    """An event bus and a way to wait for fired events to be delivered."""

    bus: EventBus
    hass: HomeAssistant

    async def settle(self) -> None:
        """Wait until fired events have reached their listeners."""
        await self.hass.async_block_till_done()
        await asyncio.sleep(0)


@pytest.fixture(params=IMPLEMENTATIONS)
async def event_setup(request: pytest.FixtureRequest, hass: HomeAssistant) -> AsyncGenerator[EventSetup]:
    """An event bus in each implementation."""
    if request.param == "fake":
        yield EventSetup(FakeEventBus(), hass)
        return
    manager = EventManager(hass)
    await manager.async_setup()
    yield EventSetup(manager, hass)
    await manager.async_teardown()


class TestEventBusContract:
    """Behaviour every EventBus must have."""

    async def test_typed_subscription(self, event_setup: EventSetup) -> None:
        """Test a typed subscriber gets events of that type with their data."""
        queue = event_setup.bus.subscribe("contract_event")
        event_setup.bus.fire("contract_event", {"n": 1})
        await event_setup.settle()

        event = queue.get_nowait()
        assert event is not None
        assert event.event_type == "contract_event"
        assert event.data == {"n": 1}
        assert event.time_fired.tzinfo is not None
        assert queue.empty()

    async def test_typed_subscription_ignores_other_types(self, event_setup: EventSetup) -> None:
        """Test a typed subscriber does not get events of another type."""
        queue = event_setup.bus.subscribe("contract_event")
        event_setup.bus.fire("contract_other")
        await event_setup.settle()
        assert queue.empty()

    @pytest.mark.parametrize(
        ("data", "delivered"),
        [
            ({"command": "toggle"}, True),
            ({"command": "toggle", "extra": 1}, True),
            ({"command": "on"}, False),
            ({}, False),
        ],
    )
    async def test_filter(self, event_setup: EventSetup, data: dict[str, Any], delivered: bool) -> None:
        """Test a filter delivers only events whose data has every listed key with an equal value."""
        queue = event_setup.bus.subscribe("contract_event", {"command": "toggle"})
        event_setup.bus.fire("contract_event", data)
        await event_setup.settle()
        assert queue.empty() is not delivered

    async def test_fire_without_data(self, event_setup: EventSetup) -> None:
        """Test an event fired without data is delivered with an empty dictionary."""
        queue = event_setup.bus.subscribe("contract_event")
        event_setup.bus.fire("contract_event")
        await event_setup.settle()
        event = queue.get_nowait()
        assert event is not None and event.data == {}

    async def test_unsubscribe(self, event_setup: EventSetup) -> None:
        """Test no events are delivered after unsubscribing."""
        queue = event_setup.bus.subscribe("contract_event")
        event_setup.bus.unsubscribe(queue, "contract_event")
        event_setup.bus.fire("contract_event")
        await event_setup.settle()
        assert queue.empty()

    async def test_listen_once(self, event_setup: EventSetup) -> None:
        """Test a one-time listener runs for the first matching event only."""
        received: list[str] = []

        async def on_event(event: Any) -> None:
            received.append(event.event_type)

        event_setup.bus.listen_once("contract_once", on_event)
        event_setup.bus.fire("contract_unrelated")
        event_setup.bus.fire("contract_once")
        await event_setup.settle()
        event_setup.bus.fire("contract_once")
        await event_setup.settle()

        assert received == ["contract_once"]

    async def test_listen_once_cancel(self, event_setup: EventSetup) -> None:
        """Test a cancelled one-time listener is never called."""
        received: list[str] = []

        async def on_event(event: Any) -> None:
            received.append(event.event_type)

        cancel = event_setup.bus.listen_once("contract_once", on_event)
        cancel()
        event_setup.bus.fire("contract_once")
        await event_setup.settle()

        assert received == []


# --- ServiceCaller ---------------------------------------------------------------


class RegisterService(Protocol):
    """Registers a service in the system under test."""

    def __call__(
        self, domain: str, service: str, *, response: dict[str, Any] | None = None, fail: str | None = None
    ) -> None:
        """Register the service; ``fail`` makes calls to it fail with that reason."""


@dataclass
class ServiceSetup:
    """A service caller, a way to register services, and a view of the calls that reached them."""

    caller: ServiceCaller
    register: RegisterService
    received: Callable[[], list[dict[str, Any]]]
    """Returns the data of every call that reached a registered service, oldest first."""


@pytest.fixture(params=IMPLEMENTATIONS)
def service_setup(request: pytest.FixtureRequest, hass: HomeAssistant) -> ServiceSetup:
    """A service caller in each implementation."""
    if request.param == "fake":
        fake = FakeServiceCaller()

        def register_fake(
            domain: str, service: str, *, response: dict[str, Any] | None = None, fail: str | None = None
        ) -> None:
            fake.register(domain, service, response=response)
            if fail is not None:
                fake.fail(domain, service, fail)

        return ServiceSetup(fake, register_fake, lambda: [call.data for call in fake.calls])

    received: list[dict[str, Any]] = []

    def register_real(
        domain: str, service: str, *, response: dict[str, Any] | None = None, fail: str | None = None
    ) -> None:
        async def handler(call: ServiceCall) -> dict[str, Any] | None:
            received.append(dict(call.data))
            if fail is not None:
                raise HomeAssistantError(fail)
            return response if call.return_response else None

        hass.services.async_register(domain, service, handler, supports_response=SupportsResponse.OPTIONAL)

    return ServiceSetup(HAServiceCaller(hass), register_real, lambda: received)


class TestServiceCallerContract:
    """Behaviour every ServiceCaller must have."""

    def test_has_service(self, service_setup: ServiceSetup) -> None:
        """Test a registered service is found and an unregistered one is not."""
        service_setup.register("contract", "do")
        assert service_setup.caller.has_service("contract", "do") is True
        assert service_setup.caller.has_service("contract", "missing") is False

    def test_services_lists_registered(self, service_setup: ServiceSetup) -> None:
        """Test services() includes every registered service."""
        service_setup.register("contract", "do")
        service_setup.register("contract", "other")
        listed = {(info.domain, info.name) for info in service_setup.caller.services()}
        assert {("contract", "do"), ("contract", "other")} <= listed

    async def test_call_delivers_data(self, service_setup: ServiceSetup) -> None:
        """Test a call reaches the service with its data and returns None by default."""
        service_setup.register("contract", "do", response={"ok": True})
        result = await service_setup.caller.async_call("contract", "do", {"level": 3})
        assert result is None
        assert service_setup.received() == [{"level": 3}]

    async def test_call_without_data(self, service_setup: ServiceSetup) -> None:
        """Test a call without data delivers an empty dictionary."""
        service_setup.register("contract", "do")
        await service_setup.caller.async_call("contract", "do")
        assert service_setup.received() == [{}]

    async def test_call_returns_response_when_requested(self, service_setup: ServiceSetup) -> None:
        """Test the service's response is returned when asked for."""
        service_setup.register("contract", "do", response={"ok": True})
        result = await service_setup.caller.async_call("contract", "do", return_response=True)
        assert result == {"ok": True}

    async def test_failing_service_raises_service_call_error(self, service_setup: ServiceSetup) -> None:
        """Test a failing service raises ServiceCallError carrying the reason."""
        service_setup.register("contract", "do", fail="device offline")
        with pytest.raises(ServiceCallError) as exc_info:
            await service_setup.caller.async_call("contract", "do")
        assert (exc_info.value.domain, exc_info.value.service) == ("contract", "do")
        assert "device offline" in exc_info.value.reason

    async def test_missing_service_raises_service_call_error(self, service_setup: ServiceSetup) -> None:
        """Test calling a service that is not registered raises ServiceCallError."""
        with pytest.raises(ServiceCallError) as exc_info:
            await service_setup.caller.async_call("contract", "missing")
        assert (exc_info.value.domain, exc_info.value.service) == ("contract", "missing")


# --- Clock -----------------------------------------------------------------------


@pytest.fixture(params=IMPLEMENTATIONS)
def clock(request: pytest.FixtureRequest) -> Clock:
    """A clock in each implementation."""
    return FakeClock() if request.param == "fake" else HAClock()


class TestClockContract:
    """Behaviour every Clock must have."""

    def test_now_is_timezone_aware(self, clock: Clock) -> None:
        """Test now() returns a datetime with a time zone."""
        now = clock.now()
        assert isinstance(now, datetime)
        assert now.tzinfo is not None

    def test_now_does_not_go_backwards(self, clock: Clock) -> None:
        """Test a later read is never earlier than an earlier one."""
        first = clock.now()
        assert clock.now() >= first


# --- SunProvider -----------------------------------------------------------------


@pytest.fixture(params=IMPLEMENTATIONS)
def sun(request: pytest.FixtureRequest, hass: HomeAssistant) -> SunProvider:
    """A sun provider in each implementation."""
    return FakeSunProvider() if request.param == "fake" else HASunProvider(hass)


class TestSunProviderContract:
    """Behaviour every SunProvider must have."""

    @pytest.mark.parametrize("event", ["sunrise", "sunset"])
    def test_next_event_is_after_and_within_a_day(self, sun: SunProvider, event: str) -> None:
        """Test the next event is timezone-aware, after the given time, and at most a day later."""
        after = HAClock().now()
        result = sun.next_event(event, after)
        assert result is not None
        assert result.tzinfo is not None
        assert after < result
        assert (result - after).total_seconds() <= 24 * 60 * 60 + 60

    def test_events_advance(self, sun: SunProvider) -> None:
        """Test asking again from the returned time gives a later event."""
        first = sun.next_event("sunrise", HAClock().now())
        assert first is not None
        second = sun.next_event("sunrise", first)
        assert second is not None and second > first


# --- FileSystem ------------------------------------------------------------------


@dataclass
class FileSetup:
    """A file system, a directory in it, and a way to create files."""

    files: FileSystem
    root: Path
    fake: FakeFileSystem | None

    def write(self, name: str, content: str) -> Path:
        """Create a file under the root and return its path."""
        path = self.root / name
        if self.fake is not None:
            self.fake.write(path, content)
        else:
            path.write_text(content, encoding="utf-8")
        return path


@pytest.fixture(params=IMPLEMENTATIONS)
def file_setup(request: pytest.FixtureRequest, hass: HomeAssistant, tmp_path: Path) -> FileSetup:
    """A file system in each implementation."""
    if request.param == "fake":
        fake = FakeFileSystem()
        return FileSetup(fake, Path("/contract"), fake)
    return FileSetup(HAFileSystem(hass), tmp_path, None)


class TestFileSystemContract:
    """Behaviour every FileSystem must have."""

    async def test_existing_file(self, file_setup: FileSetup) -> None:
        """Test an existing file is found, read as text, and has a modification time."""
        path = file_setup.write("main.py", "x = 1\n# héllo")
        assert file_setup.files.exists(path) is True
        assert await file_setup.files.read_text(path) == "x = 1\n# héllo"
        assert isinstance(file_setup.files.modified_time(path), datetime)

    async def test_missing_file(self, file_setup: FileSetup) -> None:
        """Test a missing file is not found and raises OSError when read or inspected."""
        path = file_setup.root / "missing.py"
        assert file_setup.files.exists(path) is False
        with pytest.raises(OSError):
            await file_setup.files.read_text(path)
        with pytest.raises(OSError):
            file_setup.files.modified_time(path)

    async def test_empty_file(self, file_setup: FileSetup) -> None:
        """Test an empty file is read as an empty string."""
        path = file_setup.write("empty.py", "")
        assert await file_setup.files.read_text(path) == ""
