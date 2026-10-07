"""Tests for the event trigger.

See "Event Trigger" and "EventTriggerEvent" in the design.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.lifecycle import AutomationState
from haanim.engine.triggers.event_trigger import data_matches
from haanim.engine.triggers.manager import TriggerManager
from haanim.events import EventTriggerEvent, ManualEvent
from haanim.testing.fakes import DEFAULT_NOW
from tests.engine.test_lifecycle import World


class EventWorld(World):
    """A world whose triggers are fired by the real trigger manager, with a count of what is dispatched."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.triggers = TriggerManager(self.host, self.dispatcher)  # type: ignore[assignment]
        self.dispatched: list[tuple[str, str]] = []
        original = self.dispatcher.dispatch

        async def counting(automation_id: str, action_name: str, *args: Any, **kwargs: Any) -> Any:
            self.dispatched.append((automation_id, action_name))
            return await original(automation_id, action_name, *args, **kwargs)

        self.dispatcher.dispatch = counting  # type: ignore[method-assign]

    async def fire(self, event_type: str, data: dict[str, Any] | None = None, **kwargs: Any) -> None:
        """Fire an event on the host's bus and let the triggers react."""
        self.host.events.fire(event_type, data, **kwargs)
        await self.clock.settle()


@pytest.fixture
def event_world(tmp_path: Path) -> EventWorld:
    """A world with a real trigger manager."""
    return EventWorld(tmp_path)


def source(decorator: str) -> str:
    """An automation with one event trigger function that logs its event."""
    return f"from haanim import on_event\n\n{decorator}\ndef handle(event):\n    log.append(event)\n"


BUTTON = '@on_event("zha_event", data={"command": "toggle", "device_ieee": "00:11:22:33:44:55:66:77"})'
PRESS = {"command": "toggle", "device_ieee": "00:11:22:33:44:55:66:77"}


class TestUnfiltered:
    """Without a data filter every event of the type fires the trigger."""

    async def test_fires_for_every_event_of_the_type(self, event_world: EventWorld) -> None:
        """The design's example: whenever any service is called."""
        await event_world.started("watcher", source('@on_event("call_service")'))
        await event_world.fire("call_service", {"domain": "light", "service": "turn_on"})
        await event_world.fire("call_service", {"domain": "switch"})
        await event_world.fire("call_service")

        assert [event.event_data.get("domain") for event in event_world.log] == ["light", "switch", None]

    async def test_other_event_types_do_not_fire(self, event_world: EventWorld) -> None:
        """Only the type the trigger names."""
        await event_world.started("watcher", source('@on_event("call_service")'))
        await event_world.fire("state_changed", {"entity_id": "light.a"})
        await event_world.fire("call_service_extra")
        assert event_world.log == []
        assert event_world.dispatched == []

    async def test_event_data_access(self, event_world: EventWorld) -> None:
        """The design's example: event.event_data.get with a default."""
        automation = event_world.add(
            "watcher",
            "from haanim import on_event\n\n@on_event('custom_event')\ndef handle(event):\n"
            "    log.append(event.event_data.get('field_name', 'default'))\n",
        )
        assert await automation.load() and await automation.start()
        event_world.expose(automation)
        await event_world.fire("custom_event", {"field_name": "value"})
        await event_world.fire("custom_event", {"other": 1})
        assert event_world.log == ["value", "default"]


class TestDataFilter:
    """The trigger fires only when every key of the filter is in the event data with an equal value."""

    async def test_match(self, event_world: EventWorld) -> None:
        """The design's example: the matching button press fires."""
        await event_world.started("buttons", source(BUTTON))
        await event_world.fire("zha_event", dict(PRESS))
        assert len(event_world.log) == 1

    async def test_extra_keys_of_the_event_are_ignored(self, event_world: EventWorld) -> None:
        """Keys of the event that the filter does not list do not matter."""
        await event_world.started("buttons", source(BUTTON))
        await event_world.fire("zha_event", {**PRESS, "endpoint_id": 1, "args": [1, 2]})
        assert len(event_world.log) == 1
        assert event_world.log[0].event_data["endpoint_id"] == 1

    async def test_mismatch(self, event_world: EventWorld) -> None:
        """A different value for a filtered key does not fire."""
        await event_world.started("buttons", source(BUTTON))
        await event_world.fire("zha_event", {**PRESS, "command": "on"})
        await event_world.fire("zha_event", {**PRESS, "device_ieee": "ff:ff:ff:ff:ff:ff:ff:ff"})
        assert event_world.log == []

    async def test_missing_key(self, event_world: EventWorld) -> None:
        """An event without a filtered key does not fire."""
        await event_world.started("buttons", source(BUTTON))
        await event_world.fire("zha_event", {"command": "toggle"})
        await event_world.fire("zha_event", {})
        await event_world.fire("zha_event")
        assert event_world.log == []

    async def test_missing_key_is_not_none(self, event_world: EventWorld) -> None:
        """A filter value of None matches a key that is present and None, not a key that is absent."""
        await event_world.started("watcher", source('@on_event("custom_event", data={"zone": None})'))
        await event_world.fire("custom_event", {"other": 1})
        assert event_world.log == []
        await event_world.fire("custom_event", {"zone": None})
        assert len(event_world.log) == 1

    async def test_nested_values_must_be_equal_as_a_whole(self, event_world: EventWorld) -> None:
        """Nested dictionaries and lists are compared with ==."""
        await event_world.started(
            "watcher",
            source('@on_event("custom_event", data={"args": [1, 2], "meta": {"a": 1, "b": {"c": 2}}})'),
        )
        await event_world.fire("custom_event", {"args": [1, 2], "meta": {"a": 1, "b": {"c": 2}}})
        assert len(event_world.log) == 1

        for data in (
            {"args": [1, 2, 3], "meta": {"a": 1, "b": {"c": 2}}},
            {"args": [2, 1], "meta": {"a": 1, "b": {"c": 2}}},
            {"args": [1, 2], "meta": {"a": 1}},
            {"args": [1, 2], "meta": {"a": 1, "b": {"c": 2}, "extra": True}},
            {"args": [1, 2], "meta": {"a": 1, "b": {"c": 3}}},
        ):
            await event_world.fire("custom_event", data)
        assert len(event_world.log) == 1

    async def test_values_are_compared_with_equality(self, event_world: EventWorld) -> None:
        """1 and 1.0 are equal; 1 and '1' are not."""
        await event_world.started("watcher", source('@on_event("custom_event", data={"count": 1})'))
        await event_world.fire("custom_event", {"count": 1.0})
        await event_world.fire("custom_event", {"count": "1"})
        assert [event.event_data["count"] for event in event_world.log] == [1.0]

    async def test_empty_filter_is_no_filter(self, event_world: EventWorld) -> None:
        """data={} fires for every event of the type."""
        await event_world.started("watcher", source('@on_event("custom_event", data={})'))
        await event_world.fire("custom_event", {"anything": 1})
        assert len(event_world.log) == 1

    def test_data_matches(self) -> None:
        """The filter function on its own."""
        assert data_matches(None, {"a": 1}) is True
        assert data_matches({}, {}) is True
        assert data_matches({"a": 1}, {"a": 1, "b": 2}) is True
        assert data_matches({"a": 1, "b": 2}, {"a": 1}) is False
        assert data_matches({"a": [1, {"b": 2}]}, {"a": [1, {"b": 2}]}) is True
        assert data_matches({"a": None}, {}) is False


class TestFilterBeforeDispatch:
    """Done when: a non-matching event dispatches nothing."""

    async def test_non_matching_event_dispatches_nothing(self, event_world: EventWorld) -> None:
        """The filter is applied before an action is requested: the dispatcher is not asked."""
        automation = await event_world.started("buttons", source(BUTTON))
        for data in ({"command": "on"}, {"command": "toggle"}, {}, {**PRESS, "command": "off"}):
            await event_world.fire("zha_event", data)

        assert event_world.dispatched == []
        assert event_world.dispatcher.is_idle()
        assert event_world.pool.active_count == 0
        assert automation.last_error is None

    async def test_matching_event_dispatches_once(self, event_world: EventWorld) -> None:
        """One matching event is one request."""
        await event_world.started("buttons", source(BUTTON))
        await event_world.fire("zha_event", {"command": "on"})
        await event_world.fire("zha_event", dict(PRESS))
        assert event_world.dispatched == [("buttons", "handle")]

    async def test_every_matching_event_dispatches(self, event_world: EventWorld) -> None:
        """Note of the design: every matching event dispatches an action."""
        await event_world.started("watcher", source('@on_event("custom_event")'))
        for number in range(5):
            await event_world.fire("custom_event", {"n": number})
        assert len(event_world.dispatched) == 5
        assert [event.event_data["n"] for event in event_world.log] == [0, 1, 2, 3, 4]


class TestEventTriggerEvent:
    """Every row of the EventTriggerEvent table."""

    async def test_fields(self, event_world: EventWorld) -> None:
        """event_type, event_data, time_fired and user_id."""
        await event_world.started("watcher", source('@on_event("custom_event")'))
        await event_world.clock.advance(minutes=7)
        await event_world.fire("custom_event", {"field_name": "value"}, user_id="user-42")

        (event,) = event_world.log
        assert type(event) is EventTriggerEvent
        assert event.event_type == "custom_event"
        assert event.event_data == {"field_name": "value"}
        assert event.time_fired == DEFAULT_NOW + timedelta(minutes=7)
        assert event.user_id == "user-42"

    async def test_user_id_is_none_without_a_user(self, event_world: EventWorld) -> None:
        """An event no user caused has no user_id."""
        await event_world.started("watcher", source('@on_event("custom_event")'))
        await event_world.fire("custom_event")
        assert event_world.log[0].user_id is None
        assert event_world.log[0].event_data == {}

    async def test_common_fields(self, event_world: EventWorld) -> None:
        """The fields every trigger-fired event has."""
        await event_world.started("watcher", source('@on_event("custom_event")'))
        await event_world.fire("custom_event", {"a": 1})
        (event,) = event_world.log
        assert (event.automation_id, event.source, event.caller, event.data) == (
            "watcher",
            "trigger",
            None,
            {},
        )
        assert event.call_time == DEFAULT_NOW

    async def test_direct_call_is_not_an_event_trigger_event(self, event_world: EventWorld) -> None:
        """Called by hand, the function gets a ManualEvent."""
        automation = await event_world.started("watcher", source('@on_event("custom_event")'))
        await automation.call_action("handle")
        assert type(event_world.log[0]) is ManualEvent


class TestLifetime:
    """The trigger listens while the automation runs."""

    async def test_stop_unsubscribes(self, event_world: EventWorld) -> None:
        """Events fired after stop do nothing."""
        automation = await event_world.started("watcher", source('@on_event("custom_event")'))
        await automation.stop()
        await event_world.fire("custom_event")
        assert event_world.log == []
        assert event_world.dispatched == []

    async def test_restart_listens_again(self, event_world: EventWorld) -> None:
        """A restarted automation gets the events fired after the restart, and none from before."""
        automation = await event_world.started("watcher", source('@on_event("custom_event")'))
        await automation.stop()
        await event_world.fire("custom_event", {"n": 1})
        assert await automation.start()
        event_world.expose(automation)
        await event_world.fire("custom_event", {"n": 2})
        assert [event.event_data["n"] for event in event_world.log] == [2]

    async def test_two_automations_on_one_event(self, event_world: EventWorld) -> None:
        """Each automation's trigger fires for the same event."""
        await event_world.started("first", source('@on_event("custom_event")'))
        await event_world.started("second", source('@on_event("custom_event", data={"n": 2})'))
        await event_world.fire("custom_event", {"n": 1})
        await event_world.fire("custom_event", {"n": 2})
        assert sorted(event_world.dispatched) == [
            ("first", "handle"),
            ("first", "handle"),
            ("second", "handle"),
        ]

    async def test_slow_action_does_not_hold_up_later_events(self, event_world: EventWorld) -> None:
        """Events are requested as they come; what happens to them is the execution mode's business."""
        automation = event_world.add(
            "watcher",
            "from haanim import ActionMode, action, on_event, haa\n\n@on_event('custom_event')\n"
            "@action(execution_mode=ActionMode.QUEUE)\nasync def handle(event):\n"
            "    log.append(event.event_data['n'])\n    await haa.sleep(10)\n",
        )
        assert await automation.load() and await automation.start()
        event_world.expose(automation)
        for number in range(3):
            await event_world.fire("custom_event", {"n": number})

        assert len(event_world.dispatched) == 3
        assert event_world.log == [0]
        await event_world.clock.advance(seconds=30)
        assert event_world.log == [0, 1, 2]

    async def test_constraint_on_an_event_trigger(self, event_world: EventWorld) -> None:
        """The design's example: not during sleep mode."""
        event_world.host.states.set_state("input_boolean.sleep_mode", "on")
        automation = await event_world.started(
            "door", source('@on_event("doorbell", when_not="input_boolean.sleep_mode == \'on\'")')
        )
        await event_world.fire("doorbell")
        assert event_world.log == []

        event_world.host.states.set_state("input_boolean.sleep_mode", "off")
        await event_world.fire("doorbell")
        assert len(event_world.log) == 1
        assert automation.state is AutomationState.ON

    async def test_data_must_be_a_dictionary(self, event_world: EventWorld) -> None:
        """A filter that is not a dictionary stops the start."""
        automation = event_world.add("broken", source('@on_event("custom_event", data=["x"])'))
        assert await automation.load()
        assert not await automation.start()
        assert automation.message == "TypeError: @on_event: data must be a dict, not list"
