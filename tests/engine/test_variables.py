"""Tests for persistent storage: the variables of an automation.

See "Persistent Storage" in the design.
"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.haanim_api import HAAnim
from haanim.engine.variables import SAVE_DELAY_SECONDS, VariableStore, storage_key
from haanim.testing import FakeClock, FakeStorage
from tests.engine.test_lifecycle import World, world  # noqa: F401  pylint: disable=unused-import


@pytest.fixture
def clock() -> FakeClock:
    """A fake clock."""
    return FakeClock()


@pytest.fixture
def backend() -> FakeStorage:
    """Storage held in memory."""
    return FakeStorage()


@pytest.fixture
def store(backend: FakeStorage, clock: FakeClock) -> VariableStore:
    """The variables of an automation called lights."""
    return VariableStore("lights", backend, clock)


JSON_VALUES: list[Any] = [
    "text",
    "",
    0,
    42,
    -7,
    25.0,
    3.14,
    True,
    False,
    None,
    [],
    ["kitchen", "hall"],
    [1, "two", 3.0, None, True],
    {},
    {"enabled": True, "threshold": 25.0},
    {"rooms": ["kitchen", {"name": "hall", "lights": [1, 2]}], "nested": {"deep": {"deeper": None}}},
]


class Thing:
    """A class instance, which is not a JSON value."""


NOT_JSON: list[tuple[Any, str]] = [
    (datetime(2025, 1, 6), "datetime is not a JSON value"),
    ({1, 2}, "set is not a JSON value"),
    (Thing(), "Thing is not a JSON value"),
    ({1: "a"}, "a dictionary key must be a string, not int"),
    ({("a", "b"): 1}, "a dictionary key must be a string, not tuple"),
    (b"bytes", "bytes is not a JSON value"),
    (["fine", {"inner": {1, 2}}], "set is not a JSON value"),
    ({"outer": {"when": datetime(2025, 1, 6)}}, "datetime is not a JSON value"),
    (lambda: 1, "function is not a JSON value"),
]


class TestTypes:
    """Rule: any JSON value can be stored; anything else raises TypeError and nothing is stored."""

    @pytest.mark.parametrize("value", JSON_VALUES, ids=[repr(value)[:40] for value in JSON_VALUES])
    def test_json_values(self, store: VariableStore, value: Any) -> None:
        """Strings, numbers, booleans, None, lists and dictionaries with string keys."""
        store.set("key", value)
        result = store.get("key")
        assert result == value
        assert type(result) is type(value)

    @pytest.mark.parametrize(("value", "reason"), NOT_JSON, ids=[reason for _, reason in NOT_JSON])
    def test_rejected(self, store: VariableStore, value: Any, reason: str) -> None:
        """TypeError naming the variable and the offending part."""
        with pytest.raises(TypeError, match=reason) as exc_info:
            store.set("config", value)
        assert "variable 'config'" in str(exc_info.value)

    def test_nothing_is_stored_when_rejected(self, store: VariableStore, backend: FakeStorage) -> None:
        """A rejected value leaves the store, and an earlier value, as they were."""
        store.set("config", {"ok": 1})
        with pytest.raises(TypeError):
            store.set("config", {"ok": 1, "bad": {1, 2}})
        with pytest.raises(TypeError):
            store.set("other", datetime(2025, 1, 6))
        assert store.get("config") == {"ok": 1}
        assert store.keys() == ["config"]

    def test_tuples_are_stored_as_lists(self, store: VariableStore) -> None:
        """A tuple comes back as a list, at any depth."""
        store.set("pair", (1, 2))
        store.set("nested", {"points": [(0, 0), (1, 1)]})
        assert store.get("pair") == [1, 2]
        assert store.get("nested") == {"points": [[0, 0], [1, 1]]}

    def test_key_must_be_a_string(self, store: VariableStore) -> None:
        """Variable names are strings."""
        with pytest.raises(TypeError, match="a variable name must be a string, not int"):
            store.set(1, "x")  # type: ignore[arg-type]

    def test_datetime_as_a_string(self, store: VariableStore) -> None:
        """The design's example: datetimes are stored as strings."""
        store.set("last_saved", datetime(2025, 1, 6, 12, 0).isoformat())
        assert store.get("last_saved") == "2025-01-06T12:00:00"


class TestApi:
    """The four methods."""

    def test_get_default(self, store: VariableStore) -> None:
        """get returns the default if the key is not set; None without a default."""
        assert store.get("missing") is None
        assert store.get("enabled", True) is True
        assert store.get("threshold", 25.0) == 25.0
        assert store.get("rooms", []) == []

    def test_default_is_not_used_for_a_stored_falsy_value(self, store: VariableStore) -> None:
        """A stored False, 0, empty list or None is a value."""
        for value in (False, 0, [], "", None):
            store.set("key", value)
            assert store.get("key", "default") == value

    def test_unset(self, store: VariableStore) -> None:
        """unset removes one variable and does nothing if it is not set."""
        store.set("a", 1)
        store.set("b", 2)
        store.unset("a")
        store.unset("never_set")
        assert (store.get("a"), store.get("b")) == (None, 2)

    def test_clear(self, store: VariableStore) -> None:
        """clear removes everything."""
        store.set("a", 1)
        store.set("b", 2)
        store.clear()
        assert store.keys() == []

    def test_set_replaces(self, store: VariableStore) -> None:
        """Setting a key again replaces its value."""
        store.set("a", [1])
        store.set("a", "text")
        assert store.get("a") == "text"


class TestCopies:
    """Rule: set stores a copy and get returns a copy."""

    def test_set_stores_a_copy(self, store: VariableStore) -> None:
        """Changing the object after set does not change the store."""
        rooms = ["kitchen"]
        store.set("rooms", rooms)
        rooms.append("hall")
        assert store.get("rooms") == ["kitchen"]

    def test_get_returns_a_copy(self, store: VariableStore) -> None:
        """Changing what get returned does not change the store until it is set again."""
        store.set("config", {"rooms": ["kitchen"]})
        config = store.get("config")
        config["rooms"].append("hall")
        config["new"] = 1
        assert store.get("config") == {"rooms": ["kitchen"]}

        store.set("config", config)
        assert store.get("config") == {"rooms": ["kitchen", "hall"], "new": 1}

    def test_two_gets_are_independent(self, store: VariableStore) -> None:
        """Each get is its own copy."""
        store.set("rooms", ["kitchen"])
        first, second = store.get("rooms"), store.get("rooms")
        first.append("x")
        assert second == ["kitchen"]


class TestSynchronousApi:
    """Rule: the four methods return immediately and are not awaited."""

    def test_methods_are_not_coroutines(self) -> None:
        """Neither on the store nor on haa."""
        for name in ("set_variable", "get_variable", "unset_variable", "clear_variables"):
            assert not inspect.iscoroutinefunction(getattr(HAAnim, name))
        for name in ("set", "get", "unset", "clear"):
            assert not inspect.iscoroutinefunction(getattr(VariableStore, name))

    def test_value_is_readable_at_once(self, store: VariableStore, backend: FakeStorage) -> None:
        """A get right after a set sees the value, before anything has been written."""
        store.set("counter", 1)
        store.set("counter", store.get("counter") + 1)
        assert store.get("counter") == 2
        assert backend.saves == []

    async def test_from_automation_code(self, world: World) -> None:
        """The design's example: a def action sets and a @startup reads, with no await."""
        source = (
            "from haanim import action, haa, startup\n\nloaded = {}\n\n"
            "@startup\ndef load_config(event):\n"
            "    loaded['enabled'] = haa.get_variable('enabled', True)\n"
            "    loaded['threshold'] = haa.get_variable('threshold', 25.0)\n"
            "    loaded['rooms'] = haa.get_variable('rooms', [])\n\n"
            "@action\ndef save_config(event):\n"
            "    haa.set_variable('enabled', False)\n"
            "    haa.set_variable('threshold', 21.5)\n"
            "    haa.set_variable('rooms', ['kitchen', 'hall'])\n"
            "    haa.set_variable('last_saved', haa.now().isoformat())\n"
            "    return haa.get_variable('rooms')\n"
        )
        automation = await world.started("config", source)
        assert automation.context.get_symbol("loaded") == {"enabled": True, "threshold": 25.0, "rooms": []}
        assert await automation.call_action("save_config") == ["kitchen", "hall"]

        await automation.stop()
        assert await automation.start()
        assert automation.context.get_symbol("loaded") == {
            "enabled": False,
            "threshold": 21.5,
            "rooms": ["kitchen", "hall"],
        }

    async def test_type_error_in_automation_code(self, world: World) -> None:
        """A value that is not JSON raises TypeError in the action."""
        automation = await world.started(
            "config",
            "from haanim import action, haa\n\n@action\ndef bad(event):\n    haa.set_variable('when', haa.now())\n",
        )
        with pytest.raises(TypeError, match="datetime is not a JSON value"):
            await automation.call_action("bad")


class TestWritingToDisk:
    """Rule: written shortly after a change, several changes together, and always on stop."""

    async def test_written_within_one_second(
        self, store: VariableStore, backend: FakeStorage, clock: FakeClock
    ) -> None:
        """Nothing is written at once; the write comes when the delay has passed."""
        store.set("a", 1)
        assert backend.saves == []
        assert store.is_dirty

        await clock.advance(seconds=SAVE_DELAY_SECONDS - 0.01)
        assert backend.saves == []
        await clock.advance(seconds=0.01)
        assert backend.saves == [storage_key("lights")]
        assert backend.peek("automation.lights") == {"a": 1}
        assert not store.is_dirty

    async def test_changes_within_the_delay_are_written_together(
        self, store: VariableStore, backend: FakeStorage, clock: FakeClock
    ) -> None:
        """Several changes in that second are one write."""
        store.set("a", 1)
        await clock.advance(seconds=0.4)
        store.set("b", 2)
        store.unset("a")
        store.set("c", [3])
        await clock.advance(seconds=0.6)

        assert backend.saves == ["automation.lights"]
        assert backend.peek("automation.lights") == {"b": 2, "c": [3]}

    async def test_later_change_is_a_later_write(
        self, store: VariableStore, backend: FakeStorage, clock: FakeClock
    ) -> None:
        """A change after a write schedules the next write."""
        store.set("a", 1)
        await clock.advance(seconds=1)
        store.set("a", 2)
        await clock.advance(seconds=1)
        assert len(backend.saves) == 2
        assert backend.peek("automation.lights") == {"a": 2}

    async def test_no_write_without_a_change(
        self, store: VariableStore, backend: FakeStorage, clock: FakeClock
    ) -> None:
        """Reading, unsetting a missing key and clearing an empty store write nothing."""
        store.get("a")
        store.unset("a")
        store.clear()
        await clock.advance(seconds=5)
        assert backend.saves == []
        assert clock.pending_timers == 0

    async def test_flush_writes_at_once(
        self, store: VariableStore, backend: FakeStorage, clock: FakeClock
    ) -> None:
        """flush writes pending changes without waiting and leaves no timer."""
        store.set("a", 1)
        await store.flush()
        assert backend.peek("automation.lights") == {"a": 1}
        assert clock.pending_timers == 0

        await clock.advance(seconds=5)
        assert len(backend.saves) == 1

    async def test_flush_without_changes_writes_nothing(
        self, store: VariableStore, backend: FakeStorage
    ) -> None:
        """Nothing changed, nothing written."""
        await store.flush()
        assert backend.saves == []

    async def test_written_when_the_automation_stops(self, world: World) -> None:
        """Stopping the automation writes what is pending, a change made by @shutdown included."""
        automation = await world.started(
            "config",
            "from haanim import action, haa, shutdown\n\n@action\ndef remember(event):\n"
            "    haa.set_variable('kept', 'yes')\n\n@shutdown\ndef on_stop(event):\n"
            "    haa.set_variable('stopped', True)\n",
        )
        await automation.call_action("remember")
        assert world.host.storage.peek("automation.config") is None

        await automation.stop()
        assert world.host.storage.peek("automation.config") == {"kept": "yes", "stopped": True}
        assert world.clock.pending_timers == 0

    async def test_save_failure_is_logged_and_retried(
        self, store: VariableStore, backend: FakeStorage, clock: FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A failed write does not lose the change: it stays pending for the next write."""
        original = backend.save
        failing = True

        async def save(key: str, data: Any) -> None:
            if failing:
                raise OSError("disk full")
            await original(key, data)

        backend.save = save  # type: ignore[method-assign]
        store.set("a", 1)
        with caplog.at_level(logging.ERROR, logger="haanim.engine.variables"):
            await clock.advance(seconds=1)
        assert "Failed to save the variables of 'lights': disk full" in caplog.text
        assert store.is_dirty and store.get("a") == 1

        failing = False
        await store.flush()
        assert backend.peek("automation.lights") == {"a": 1}


class TestIsolation:
    """Rule: storage is per automation."""

    async def test_automations_cannot_read_each_others_data(
        self, backend: FakeStorage, clock: FakeClock
    ) -> None:
        """Two automations with the same variable name have their own values."""
        lights, heating = VariableStore("lights", backend, clock), VariableStore("heating", backend, clock)
        lights.set("mode", "evening")
        heating.set("mode", "eco")
        await lights.flush()
        await heating.flush()

        assert (lights.get("mode"), heating.get("mode")) == ("evening", "eco")
        assert backend.peek("automation.lights") == {"mode": "evening"}
        assert backend.peek("automation.heating") == {"mode": "eco"}

    def test_location(self) -> None:
        """The store of an automation is the document automation.<id> of the integration's storage."""
        assert storage_key("lights") == "automation.lights"

    async def test_between_running_automations(self, world: World) -> None:
        """From automation code, another automation's variables are not visible."""
        source = (
            "from haanim import action, haa\n\n@action\ndef put(event):\n    haa.set_variable('x', event.data['v'])\n\n"
            "@action\ndef get(event):\n    return haa.get_variable('x')\n"
        )
        first = await world.started("first", source)
        second = await world.started("second", source)
        await first.call_action("put", {"v": 1})
        assert await first.call_action("get") == 1
        assert await second.call_action("get") is None


SOURCE = (
    "from haanim import action, haa\n\n@action\ndef put(event):\n    haa.set_variable('kept', event.data['v'])\n\n"
    "@action\ndef get(event):\n    return haa.get_variable('kept')\n"
)


class TestLifetime:
    """Rule: the data is tied to the automation ID."""

    async def test_survives_a_new_store(self, backend: FakeStorage, clock: FakeClock) -> None:
        """What was written is read back by load()."""
        first = VariableStore("lights", backend, clock)
        first.set("a", {"b": [1, 2]})
        await first.flush()

        second = VariableStore("lights", backend, clock)
        assert second.get("a") is None  # not loaded yet
        await second.load()
        assert second.get("a") == {"b": [1, 2]}

    async def test_survives_restart(self, world: World) -> None:
        """Stop and start: the value is still there."""
        automation = await world.started("config", SOURCE)
        await automation.call_action("put", {"v": "yes"})
        await automation.stop()
        assert await automation.start()
        assert await automation.call_action("get") == "yes"

    async def test_survives_unload_and_reload(self, world: World) -> None:
        """Unload, load and start again: the value is still there."""
        automation = await world.started("config", SOURCE)
        await automation.call_action("put", {"v": [1, 2]})
        await automation.unload()
        assert await automation.load() and await automation.start()
        assert await automation.call_action("get") == [1, 2]

    async def test_survives_removing_and_re_adding_the_folder(self, world: World) -> None:
        """A new automation object with the same ID finds the old data."""
        automation = await world.started("config", SOURCE)
        await automation.call_action("put", {"v": "old data"})
        await automation.unload()
        del world.automations["config"]

        again = await world.started("config", SOURCE)
        assert again is not automation
        assert await again.call_action("get") == "old data"

    async def test_renamed_folder_starts_empty(self, world: World) -> None:
        """A different ID is a different store."""
        automation = await world.started("config", SOURCE)
        await automation.call_action("put", {"v": "old data"})
        await automation.unload()

        renamed = await world.started("settings", SOURCE)
        assert await renamed.call_action("get") is None

    async def test_load_replaces_memory(self, backend: FakeStorage, clock: FakeClock) -> None:
        """load() reads the saved state; a damaged document gives an empty store."""
        store = VariableStore("lights", backend, clock)
        await backend.save("automation.lights", ["not", "a", "dictionary"])
        await store.load()
        assert store.keys() == []
