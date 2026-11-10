"""Tests for the device store and registry: declared entities, their state and its storage."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from haanim.engine.device_entities import (
    EntityDeclaration,
    button_entity,
    get_declaration,
    number_entity,
    select_entity,
    sensor_entity,
    switch_entity,
)
from haanim.engine.devices import DeviceRegistry
from haanim.engine.variables import SAVE_DELAY_SECONDS
from haanim.testing import FakeClock, FakeEntitySink, FakeStorage


def decl(decorator: Callable[[type], type], name: str) -> EntityDeclaration:
    """Declare a class called ``name`` with a decorator and return its declaration."""
    declaration = get_declaration(decorator(type(name, (), {})))
    assert declaration is not None
    return declaration


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def sink() -> FakeEntitySink:
    return FakeEntitySink()


@pytest.fixture
def registry(storage: FakeStorage, clock: FakeClock, sink: FakeEntitySink) -> DeviceRegistry:
    return DeviceRegistry(storage, clock, sink)


async def test_new_declaration_gets_initial_state_and_is_saved(
    registry: DeviceRegistry, storage: FakeStorage, clock: FakeClock
) -> None:
    store = registry.store("climate")
    store.reconcile([decl(switch_entity(initial=True), "boost")])
    entity = store.get("boost")
    assert entity is not None
    assert entity.state is True
    assert entity.declared
    assert entity.entity_id("climate") == "switch.haanim_climate_boost"
    assert entity.unique_id("climate") == "haanim_climate.boost"

    await clock.advance(seconds=SAVE_DELAY_SECONDS)
    saved = storage.peek("device.climate")
    assert saved["version"] == 1
    assert saved["entities"]["boost"]["state"] is True
    assert saved["entities"]["boost"]["platform"] == "switch"
    assert saved["entities"]["boost"]["declared"] is True
    assert storage.peek("devices") == ["climate"]


async def test_existing_entity_keeps_state_and_takes_new_options(registry: DeviceRegistry) -> None:
    store = registry.store("climate")
    store.reconcile([decl(sensor_entity(unit="°C", initial=1), "temp")])
    store.set_state("temp", 21.5)
    store.reconcile([decl(sensor_entity(unit="°C", initial=1, name="Temperature"), "temp")])
    entity = store.get("temp")
    assert entity is not None
    assert entity.state == 21.5
    assert entity.options["name"] == "Temperature"


async def test_undeclared_becomes_leftover(registry: DeviceRegistry) -> None:
    store = registry.store("climate")
    store.reconcile([decl(switch_entity(), "boost")])
    store.reconcile([])
    entity = store.get("boost")
    assert entity is not None
    assert not entity.declared
    with pytest.raises(ValueError, match="no longer declared"):
        store.set_state("boost", True)


async def test_platform_change_keeps_old_as_leftover(registry: DeviceRegistry) -> None:
    store = registry.store("climate")
    store.reconcile([decl(sensor_entity(), "x")])
    store.set_state("x", "old")
    store.reconcile([decl(number_entity(), "x")])
    new, old = store.get("x"), store.get("x@sensor")
    assert new is not None and old is not None
    assert (new.platform, new.declared, new.state) == ("number", True, None)
    assert (old.platform, old.declared, old.state, old.object_id) == ("sensor", False, "old", "x")
    assert old.entity_id("climate") == "sensor.haanim_climate_x"


async def test_platform_change_back_redeclares_the_leftover(registry: DeviceRegistry) -> None:
    store = registry.store("climate")
    store.reconcile([decl(sensor_entity(), "x")])
    store.set_state("x", "kept")
    store.reconcile([decl(number_entity(), "x")])
    store.reconcile([decl(sensor_entity(), "x")])
    entity = store.get("x")
    assert entity is not None
    assert (entity.platform, entity.declared, entity.state) == ("sensor", True, "kept")
    leftover = store.get("x@number")
    assert leftover is not None and not leftover.declared


async def test_incompatible_stored_state_resets_with_warning(registry: DeviceRegistry) -> None:
    store = registry.store("climate")
    store.reconcile([decl(sensor_entity(), "temp")])
    store.set_state("temp", "warm")
    warnings = store.reconcile([decl(sensor_entity(unit="°C", initial=20), "temp")])
    entity = store.get("temp")
    assert entity is not None
    assert entity.state == 20.0
    assert len(warnings) == 1 and "temp" in warnings[0]


async def test_option_removed_from_select_resets(registry: DeviceRegistry) -> None:
    store = registry.store("climate")
    store.reconcile([decl(select_entity(options=["a", "b"]), "mode")])
    store.set_state("mode", "b")
    warnings = store.reconcile([decl(select_entity(options=["a"], initial="a"), "mode")])
    entity = store.get("mode")
    assert entity is not None and entity.state == "a"
    assert warnings


async def test_set_attributes_merges_and_removes(registry: DeviceRegistry) -> None:
    store = registry.store("climate")
    store.reconcile([decl(sensor_entity(attributes={"a": 1, "b": 2}), "temp")])
    store.set_attributes("temp", b=None, c=3)
    entity = store.get("temp")
    assert entity is not None and entity.attributes == {"a": 1, "c": 3}


async def test_set_state_validates(registry: DeviceRegistry) -> None:
    store = registry.store("climate")
    store.reconcile([decl(number_entity(min=0, max=10), "level")])
    with pytest.raises(ValueError):
        store.set_state("level", 11)
    with pytest.raises(KeyError):
        store.set_state("nope", 1)


async def test_last_changed_moves_only_on_change(registry: DeviceRegistry, clock: FakeClock) -> None:
    store = registry.store("climate")
    store.reconcile([decl(sensor_entity(), "temp")])
    store.set_state("temp", "a")
    first = store.get("temp").last_changed  # type: ignore[union-attr]
    await clock.advance(seconds=5)
    store.set_state("temp", "a")
    assert store.get("temp").last_changed == first  # type: ignore[union-attr]
    store.set_state("temp", "b")
    assert store.get("temp").last_changed != first  # type: ignore[union-attr]


async def test_purge_resets_to_initial(registry: DeviceRegistry) -> None:
    store = registry.store("climate")
    store.reconcile([decl(number_entity(initial=3, attributes={"x": 1}), "level")])
    store.set_state("level", 9)
    store.set_attributes("level", x=2, y=3)
    store.purge("level")
    entity = store.get("level")
    assert entity is not None
    assert (entity.state, entity.attributes) == (3.0, {"x": 1})


async def test_purge_refuses_leftover_and_unknown(registry: DeviceRegistry) -> None:
    store = registry.store("climate")
    store.reconcile([decl(switch_entity(), "boost")])
    store.reconcile([])
    with pytest.raises(ValueError):
        store.purge("boost")
    with pytest.raises(KeyError):
        store.purge("nope")


async def test_remove_refuses_declared(registry: DeviceRegistry, sink: FakeEntitySink) -> None:
    store = registry.store("climate")
    store.reconcile([decl(switch_entity(), "boost")])
    with pytest.raises(ValueError, match="declared"):
        store.remove("boost")
    store.reconcile([])
    store.remove("boost")
    assert store.get("boost") is None
    assert ("removed", "climate", "boost") in sink.changes
    with pytest.raises(KeyError):
        store.remove("boost")


async def test_pending_save_does_not_resurrect_removed(
    registry: DeviceRegistry, storage: FakeStorage, clock: FakeClock
) -> None:
    store = registry.store("climate")
    store.reconcile([decl(switch_entity(), "boost")])
    await clock.advance(seconds=SAVE_DELAY_SECONDS)
    store.reconcile([])
    store.remove("boost")
    await clock.advance(seconds=SAVE_DELAY_SECONDS)
    assert storage.peek("device.climate")["entities"] == {}


async def test_purge_before_pending_save_is_what_is_saved(
    registry: DeviceRegistry, storage: FakeStorage, clock: FakeClock
) -> None:
    store = registry.store("climate")
    store.reconcile([decl(number_entity(initial=1), "level")])
    store.set_state("level", 7)
    store.purge("level")
    await clock.advance(seconds=SAVE_DELAY_SECONDS)
    assert storage.peek("device.climate")["entities"]["level"]["state"] == 1.0


async def test_two_automations_are_independent(registry: DeviceRegistry) -> None:
    a, b = registry.store("a"), registry.store("b")
    a.reconcile([decl(switch_entity(), "boost")])
    b.reconcile([decl(switch_entity(), "boost")])
    a.set_state("boost", True)
    assert b.get("boost").state is None  # type: ignore[union-attr]
    assert registry.store("a") is a


async def test_load_all_reads_index(storage: FakeStorage, clock: FakeClock) -> None:
    first = DeviceRegistry(storage, clock, None)
    first.store("a").reconcile([decl(switch_entity(initial=True), "boost")])
    first.store("b").reconcile([decl(sensor_entity(), "temp")])
    await first.flush()

    second = DeviceRegistry(storage, clock, None)
    await second.load_all()
    assert second.automation_ids() == ["a", "b"]
    assert second.store("a").get("boost").state is True  # type: ignore[union-attr]
    assert [e.key for e in second.store("b").entities()] == ["temp"]


async def test_load_all_tells_sink(storage: FakeStorage, clock: FakeClock) -> None:
    first = DeviceRegistry(storage, clock, None)
    first.store("a").reconcile([decl(switch_entity(), "boost")])
    await first.flush()
    sink = FakeEntitySink()
    second = DeviceRegistry(storage, clock, sink)
    await second.load_all()
    assert sink.changes == [("changed", "a", "boost")]


async def test_empty_store_is_not_indexed(registry: DeviceRegistry, storage: FakeStorage) -> None:
    registry.store("quiet")
    await registry.flush()
    assert registry.automation_ids() == []
    assert storage.peek("devices") is None


async def test_remove_device_drops_document_and_index(
    registry: DeviceRegistry, storage: FakeStorage, sink: FakeEntitySink
) -> None:
    registry.store("a").reconcile([decl(switch_entity(), "boost")])
    registry.store("b").reconcile([decl(switch_entity(), "boost")])
    await registry.flush()
    await registry.remove_device("a")
    assert storage.peek("device.a") is None
    assert storage.peek("devices") == ["b"]
    assert registry.automation_ids() == ["b"]
    assert ("device_removed", "a", "") in sink.changes


async def test_sink_told_of_every_change(registry: DeviceRegistry, sink: FakeEntitySink) -> None:
    store = registry.store("climate")
    store.reconcile([decl(sensor_entity(), "temp")])
    store.set_state("temp", "a")
    store.set_attributes("temp", x=1)
    assert sink.changes == [("changed", "climate", "temp")] * 3


async def test_flush_one_automation(registry: DeviceRegistry, storage: FakeStorage) -> None:
    registry.store("a").reconcile([decl(switch_entity(), "boost")])
    await registry.flush("a")
    assert storage.peek("device.a") is not None


def test_stored_values_are_copies(registry: DeviceRegistry) -> None:
    store = registry.store("climate")
    store.reconcile([decl(sensor_entity(), "temp")])
    value: dict[str, Any] = {"a": [1]}
    store.set_state("temp", value)
    value["a"].append(2)
    assert store.get("temp").state == {"a": [1]}  # type: ignore[union-attr]


# --- Final review fixes -----------------------------------------------------------


def test_unique_id_cannot_collide_across_automations(registry: DeviceRegistry) -> None:
    """Automation 'a' with entity 'b_c' and automation 'a_b' with entity 'c' get different unique IDs."""
    registry.store("a").reconcile([decl(sensor_entity(), "b_c")])
    registry.store("a_b").reconcile([decl(sensor_entity(), "c")])
    first, second = registry.store("a").get("b_c"), registry.store("a_b").get("c")
    assert first is not None and second is not None
    assert first.unique_id("a") != second.unique_id("a_b")
    assert first.unique_id("a") == "haanim_a.b_c"


async def test_stored_button_is_not_reset_on_reconcile(registry: DeviceRegistry, clock: FakeClock) -> None:
    store = registry.store("climate")
    store.reconcile([decl(button_entity(), "ring")])
    first = store.get("ring").last_changed  # type: ignore[union-attr]
    await clock.advance(seconds=5)
    assert store.reconcile([decl(button_entity(), "ring")]) == []
    assert store.get("ring").last_changed == first  # type: ignore[union-attr]


class RaisingSink(FakeEntitySink):
    """A sink whose host fails to show a change."""

    def entity_changed(self, automation_id: str, key: str) -> None:
        raise ValueError("Home Assistant refused the state")


def test_a_failing_sink_does_not_reach_the_automation(
    storage: FakeStorage, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    registry = DeviceRegistry(storage, clock, RaisingSink())
    store = registry.store("climate")
    store.reconcile([decl(sensor_entity(), "temp")])
    store.set_state("temp", "a")
    assert store.get("temp").state == "a"  # type: ignore[union-attr]
    assert "Home Assistant refused the state" in caplog.text
