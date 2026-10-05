"""Tests for the event objects actions receive, and for call arguments and return values."""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from haanim import events
from haanim.const import TRIGGER_CRON, TRIGGER_EVENT, TRIGGER_INTERVAL, TRIGGER_STATE, TRIGGER_TIME
from haanim.engine.action_dispatcher import ActionDispatcher
from haanim.engine.action_pool import ActionWorkerPool
from haanim.engine.automation_context import AutomationContext, TriggerDefinition
from haanim.engine.automation_status import AutomationStatusManager
from haanim.engine.callables import event_arguments, signature_problem, takes_event
from haanim.engine.errors import ActionNotFoundError
from haanim.engine.haanim_module import EVENT_CLASSES
from haanim.engine.lifecycle import Automation, AutomationState, NoTriggers
from haanim.engine.triggers import CronTrigger, EventTrigger, IntervalTrigger, StateTrigger, TriggerManager
from haanim.events import (
    ActionEvent,
    AutomationEvent,
    CronEvent,
    EventTriggerEvent,
    IntervalEvent,
    ManualEvent,
    StateEvent,
    TimeEvent,
)
from haanim.testing import FakeClock, FakeEventBus, FakeStateProvider, LocalFileSystem, make_host
from haanim.testing.fakes import DEFAULT_NOW
from tests.engine.helpers import automation_file, make_context

# The event tables of the design's "Event Object API Reference": class -> {property: type}.
BASE_FIELDS = {
    "call_time": datetime,
    "automation_id": str,
    "source": str,
    "caller": (str, type(None)),
    "data": dict,
}
DESIGN_EVENTS: dict[type[ActionEvent], dict[str, Any]] = {
    ActionEvent: {},
    TimeEvent: {"trigger_time": datetime},
    IntervalEvent: {"interval_seconds": float, "execution_count": int},
    CronEvent: {"cron_expression": str, "trigger_time": datetime},
    StateEvent: {"entity_id": str, "old_state": object, "new_state": object},
    EventTriggerEvent: {
        "event_type": str,
        "event_data": dict,
        "time_fired": datetime,
        "user_id": (str, type(None)),
    },
    ManualEvent: {},
    AutomationEvent: {},
}

# A valid value for each field, to build one event of each class.
VALUES: dict[str, Any] = {
    "call_time": DEFAULT_NOW,
    "automation_id": "lights",
    "source": "trigger",
    "trigger_time": DEFAULT_NOW,
    "interval_seconds": 300.0,
    "execution_count": 3,
    "cron_expression": "*/5 * * * *",
    "entity_id": "sensor.temperature",
    "old_state": None,
    "new_state": None,
    "event_type": "doorbell",
    "event_data": {"ring": 2},
    "time_fired": DEFAULT_NOW,
}


def build(event_class: type[ActionEvent], **overrides: Any) -> ActionEvent:
    """Build an event of a class from the standard values."""
    required = [
        field.name
        for field in dataclasses.fields(event_class)
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
    ]
    return event_class(**{**{name: VALUES[name] for name in required}, **overrides})


class TestEventClasses:
    """Every event class has the properties of its table in the design."""

    def test_classes_are_the_designs(self) -> None:
        """The eight event classes of the design, all importable by automations."""
        assert {event_class.__name__ for event_class in DESIGN_EVENTS} == {
            "ActionEvent",
            "TimeEvent",
            "IntervalEvent",
            "CronEvent",
            "StateEvent",
            "EventTriggerEvent",
            "ManualEvent",
            "AutomationEvent",
        }
        assert set(DESIGN_EVENTS) <= set(EVENT_CLASSES)

    @pytest.mark.parametrize("event_class", DESIGN_EVENTS, ids=lambda cls: cls.__name__)
    def test_inherits_from_action_event(self, event_class: type[ActionEvent]) -> None:
        """All event types inherit from ActionEvent."""
        assert issubclass(event_class, ActionEvent)

    @pytest.mark.parametrize("event_class", DESIGN_EVENTS, ids=lambda cls: cls.__name__)
    def test_fields_are_exactly_the_tables(self, event_class: type[ActionEvent]) -> None:
        """A class has the base properties and those of its own table, and no others."""
        names = {field.name for field in dataclasses.fields(event_class)}

        assert names == set(BASE_FIELDS) | set(DESIGN_EVENTS[event_class])

    @pytest.mark.parametrize(
        ("event_class", "name"),
        [(cls, name) for cls, own in DESIGN_EVENTS.items() for name in {**BASE_FIELDS, **own}],
        ids=lambda value: value.__name__ if isinstance(value, type) else value,
    )
    def test_each_property(self, event_class: type[ActionEvent], name: str) -> None:
        """Each property of each table is present on an event and has the documented type."""
        expected = {**BASE_FIELDS, **DESIGN_EVENTS[event_class]}[name]

        value = getattr(build(event_class), name)

        assert isinstance(value, expected)

    def test_base_defaults(self) -> None:
        """Without a caller and data an event has caller None and empty data."""
        event = build(ActionEvent)

        assert event.caller is None
        assert event.data == {}
        assert event.call_time == DEFAULT_NOW
        assert event.automation_id == "lights"

    def test_data_is_not_shared_between_events(self) -> None:
        """Each event gets its own empty data dictionary."""
        first, second = build(ActionEvent), build(ActionEvent)

        first.data["x"] = 1

        assert second.data == {}

    def test_sources(self) -> None:
        """The three ways an action is invoked."""
        assert (events.SOURCE_TRIGGER, events.SOURCE_MANUAL, events.SOURCE_AUTOMATION) == (
            "trigger",
            "manual",
            "automation",
        )

    def test_manual_event(self) -> None:
        """ManualEvent has no properties of its own; its source is manual and it has no caller."""
        event = ManualEvent(call_time=DEFAULT_NOW, automation_id="lights")

        assert (event.source, event.caller, event.data) == ("manual", None, {})

    def test_automation_event(self) -> None:
        """AutomationEvent has no properties of its own; it uses caller."""
        event = AutomationEvent(
            call_time=DEFAULT_NOW, automation_id="lights", caller="heating", data={"a": 1}
        )

        assert (event.source, event.caller, event.data) == ("automation", "heating", {"a": 1})

    def test_event_trigger_user_is_optional(self) -> None:
        """An event not caused by a user has no user_id."""
        assert build(EventTriggerEvent).user_id is None  # type: ignore[attr-defined]
        assert build(EventTriggerEvent, user_id="abc").user_id == "abc"  # type: ignore[attr-defined]

    @pytest.mark.parametrize("event_class", DESIGN_EVENTS, ids=lambda cls: cls.__name__)
    def test_events_are_immutable(self, event_class: type[ActionEvent]) -> None:
        """An action cannot change the event it was given."""
        event = build(event_class)

        with pytest.raises(dataclasses.FrozenInstanceError):
            event.source = "changed"  # type: ignore[misc]

    @pytest.mark.parametrize("event_class", DESIGN_EVENTS, ids=lambda cls: cls.__name__)
    def test_fields_are_keyword_only(self, event_class: type[ActionEvent]) -> None:
        """Events are built with named fields."""
        with pytest.raises(TypeError):
            event_class(DEFAULT_NOW, "lights", "trigger")  # type: ignore[misc]


class TestEventParameter:
    """The event parameter is optional, detected from the function's signature."""

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("def f():\n    pass\n", False),
            ("def f(event):\n    pass\n", True),
            ("async def f(event):\n    pass\n", True),
            ("async def f():\n    pass\n", False),
            ("def f(event=None):\n    pass\n", True),
            ("def f(event, /):\n    pass\n", True),
            ("def f(*args):\n    pass\n", True),
            ("def f(**kwargs):\n    pass\n", False),
            ("def f(*, option=1):\n    pass\n", False),
            ("f = lambda: None\n", False),
            ("f = lambda event: None\n", True),
        ],
    )
    def test_takes_event(self, source: str, expected: bool) -> None:
        """A function takes the event exactly when it has a positional parameter for it."""
        namespace: dict[str, Any] = {}
        exec(source, namespace)  # pylint: disable=exec-used
        func = namespace["f"]

        assert takes_event(func) is expected
        assert event_arguments(func, "EVENT") == (("EVENT",) if expected else ())

    def test_callable_without_signature_is_given_the_event(self) -> None:
        """A callable Python cannot inspect is called with the event."""
        assert takes_event(type) is True

    def test_bound_method(self) -> None:
        """For a method, self does not count."""

        class Handler:
            def without(self) -> None:
                """No event."""

            def with_event(self, event: Any) -> None:
                """Takes the event."""

        assert takes_event(Handler().without) is False
        assert takes_event(Handler().with_event) is True

    @pytest.mark.parametrize(
        ("source", "problem"),
        [
            ("def f():\n    pass\n", None),
            ("def f(event):\n    pass\n", None),
            ("def f(event, extra=1):\n    pass\n", None),
            ("def f(*args, **kwargs):\n    pass\n", None),
            ("def f(a, b):\n    pass\n", "it requires the parameters a, b; it can take the event only"),
            (
                "def f(event, room, level):\n    pass\n",
                "it requires the parameters event, room, level; it can take the event only",
            ),
            (
                "def f(event, *, room):\n    pass\n",
                "it requires the keyword argument room; it can take the event only",
            ),
        ],
    )
    def test_signature_problem(self, source: str, problem: str | None) -> None:
        """A function that needs more than the event cannot be an action."""
        namespace: dict[str, Any] = {}
        exec(source, namespace)  # pylint: disable=exec-used

        assert signature_problem(namespace["f"]) == problem


class World:
    """Automations that can call each other, with the clock, pool and registry they share."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.clock = FakeClock()
        self.host = make_host(files=LocalFileSystem(), clock=self.clock)
        self.pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=self.clock)
        self.dispatcher = ActionDispatcher(self.pool)
        self.automations: dict[str, Automation] = {}

    def get_all_contexts(self) -> list[AutomationContext]:
        """Return the contexts of all automations."""
        return [automation.context for automation in self.automations.values()]

    def get_context_by_name(self, automation_id: str) -> AutomationContext | None:
        """Return the context of an automation."""
        automation = self.automations.get(automation_id)
        return automation.context if automation else None

    async def async_call_action(
        self,
        automation_id: str,
        action_name: str,
        data: dict[str, Any] | None = None,
        *,
        caller: str | None = None,
    ) -> Any:
        """Call an action through the automation's lifecycle, as the integration does."""
        return await self.automations[automation_id].call_action(action_name, data, caller=caller)

    async def start(self, name: str, source: str) -> Automation:
        """Write, load and start an automation."""
        path = automation_file(self.root, name)
        path.write_text(source, encoding="utf-8")
        context = make_context(
            str(path), host=self.host, registry=self, storage_path=str(self.root / ".storage")
        )
        automation = Automation(context, dispatcher=self.dispatcher, triggers=NoTriggers())
        self.automations[automation.automation_id] = automation
        await automation.load()
        await automation.start()
        return automation


@pytest.fixture
def world(tmp_path: Path) -> World:
    """A world of automations in a temporary folder."""
    return World(tmp_path)


ACTIONS = """
from haanim import action, on_time, on_state, haa

@action
def no_event():
    return "called without the event"

@action
def with_event(event):
    return event

@action
async def async_with_event(event):
    return event

@action
def set_scene(event):
    level = event.data.get("level", 100)
    room = event.data["room"]
    return f"{room} set to {level}"

@action
async def caller(event):
    return await haa.call("set_scene", room="kitchen", level=40)

@on_time("09:00")
def morning(event):
    return event

@on_state("sensor.temperature > 30")
def hot():
    return "no event taken"
"""


class TestCallingActions:
    """Arguments go in as event.data; the return value comes back to the caller."""

    async def test_action_without_parameters(self, world: World) -> None:
        """A function declared without parameters is called without the event."""
        automation = await world.start("lights", ACTIONS)

        assert await automation.call_action("no_event") == "called without the event"
        assert await automation.call_action("no_event", {"ignored": True}) == "called without the event"

    @pytest.mark.parametrize("name", ["with_event", "async_with_event"])
    async def test_manual_call(self, world: World, name: str) -> None:
        """A call without a caller delivers a ManualEvent."""
        automation = await world.start("lights", ACTIONS)

        event = await automation.call_action(name)

        assert type(event) is ManualEvent
        assert (event.source, event.caller, event.data) == ("manual", None, {})
        assert event.automation_id == "lights"
        assert event.call_time == world.clock.now()

    async def test_call_from_an_automation(self, world: World) -> None:
        """A call from an automation delivers an AutomationEvent naming the caller."""
        target = await world.start("lights", ACTIONS)

        event = await target.call_action("with_event", {"level": 5}, caller="heating")

        assert type(event) is AutomationEvent
        assert (event.source, event.caller, event.data) == ("automation", "heating", {"level": 5})
        assert event.automation_id == "lights"

    async def test_call_time_is_the_time_of_the_call(self, world: World) -> None:
        """call_time is read from the clock when the call is made."""
        automation = await world.start("lights", ACTIONS)
        await world.clock.advance(minutes=90)

        event = await automation.call_action("with_event")

        assert event.call_time == DEFAULT_NOW + timedelta(minutes=90)

    async def test_design_example(self, world: World) -> None:
        """The design's set_scene example: data in through haa.call(), result out."""
        automation = await world.start("lights", ACTIONS)

        assert await automation.call_action("caller") == "kitchen set to 40"
        assert await automation.call_action("set_scene", {"room": "hall"}) == "hall set to 100"

    async def test_missing_data_raises_the_original_error(self, world: World) -> None:
        """A KeyError in the action propagates to the caller as it is."""
        automation = await world.start("lights", ACTIONS)

        with pytest.raises(KeyError, match="room"):
            await automation.call_action("set_scene", {"level": 5})

    async def test_data_is_empty_without_arguments(self, world: World) -> None:
        """event.data is {} when the action is called without arguments."""
        automation = await world.start("lights", ACTIONS)

        assert (await automation.call_action("with_event")).data == {}
        assert (await automation.call_action("with_event", {})).data == {}
        assert (await automation.call_action("with_event", None)).data == {}

    async def test_data_is_passed_by_reference(self, world: World) -> None:
        """Between automations any object may be passed; it is not copied."""
        automation = await world.start("lights", ACTIONS)
        payload = object()
        shared: list[int] = []
        data = {"payload": payload, "shared": shared}

        event = await automation.call_action("with_event", data, caller="heating")

        assert event.data is data
        assert event.data["payload"] is payload
        assert event.data["shared"] is shared

    @pytest.mark.parametrize("value", [None, 5, "text", [1, 2], {"a": 1}, object()])
    async def test_return_value_reaches_the_caller(self, world: World, value: Any) -> None:
        """Whatever the action returns is returned to the caller, the object itself."""
        automation = await world.start(
            "lights",
            "from haanim import action\n\n@action\ndef give(event):\n    return event.data['value']\n",
        )

        assert await automation.call_action("give", {"value": value}) is value

    async def test_call_between_automations_through_haa(self, world: World) -> None:
        """haa.automation(id).call(name, **data) delivers the data and names the calling automation."""
        await world.start("lights", ACTIONS)
        other = await world.start(
            "heating",
            "from haanim import action, haa\n\n@action\nasync def relay():\n"
            "    event = await haa.automation('lights').call('with_event', room='hall', level=7)\n"
            "    return (type(event).__name__, event.source, event.caller, event.automation_id, event.data)\n",
        )

        assert await other.call_action("relay") == (
            "AutomationEvent",
            "automation",
            "heating",
            "lights",
            {"room": "hall", "level": 7},
        )

    async def test_own_action_through_haa(self, world: World) -> None:
        """haa.call() on the automation's own action is a call from an automation too: caller is itself."""
        automation = await world.start(
            "lights",
            "from haanim import action, haa\n\n@action\ndef inner(event):\n    return (event.source, event.caller)\n\n"
            "@action\nasync def outer():\n    return await haa.call('inner')\n",
        )

        assert await automation.call_action("outer") == ("automation", "lights")

    async def test_arguments_are_never_bound_to_parameters(self, world: World) -> None:
        """The data is not spread over the function's parameters."""
        automation = await world.start(
            "lights",
            "from haanim import action\n\n@action\ndef show(event, room='default'):\n    return (event.data, room)\n",
        )

        assert await automation.call_action("show", {"room": "kitchen"}) == ({"room": "kitchen"}, "default")

    async def test_unknown_action(self, world: World) -> None:
        """Calling an action that does not exist names it."""
        automation = await world.start("lights", ACTIONS)

        with pytest.raises(ActionNotFoundError):
            await automation.call_action("missing", {"a": 1})


class TestTriggerFunctionCalledDirectly:
    """A trigger function run by hand or called by an automation gets that event, not the trigger's."""

    async def test_run_by_hand(self, world: World) -> None:
        """From the GUI a trigger function receives a ManualEvent without trigger fields."""
        automation = await world.start("lights", ACTIONS)

        event = await automation.call_action("morning", {"note": "by hand"})

        assert type(event) is ManualEvent
        assert event.data == {"note": "by hand"}
        assert not hasattr(event, "trigger_time")

    async def test_called_by_an_automation(self, world: World) -> None:
        """From another automation a trigger function receives an AutomationEvent."""
        automation = await world.start("lights", ACTIONS)

        event = await automation.call_action("morning", caller="heating")

        assert type(event) is AutomationEvent
        assert event.caller == "heating"
        assert not isinstance(event, TimeEvent)

    async def test_trigger_function_without_event_parameter(self, world: World) -> None:
        """A trigger function may take no event at all."""
        automation = await world.start("lights", ACTIONS)

        assert await automation.call_action("hot") == "no event taken"

    async def test_direct_run_through_the_context(self, world: World) -> None:
        """The context's own run_action builds the same events."""
        automation = await world.start("lights", ACTIONS)

        manual = await automation.context.run_action("with_event", {"a": 1})
        called = await automation.context.run_action("with_event", caller="heating")

        assert (type(manual), manual.data) == (ManualEvent, {"a": 1})
        assert (type(called), called.caller) == (AutomationEvent, "heating")
        with pytest.raises(ActionNotFoundError):
            await automation.context.run_action("missing")


class TestLifecycleHandlers:
    """@startup and @shutdown receive an ActionEvent, if they take one."""

    async def test_handlers_with_event(self, world: World) -> None:
        """The handlers are given a plain ActionEvent with source trigger."""
        automation = await world.start(
            "lights",
            "from haanim import startup, shutdown, haa\nseen = []\n\n@startup\ndef on_start(event):\n    seen.append(event)\n\n"
            "@shutdown\nasync def on_stop(event):\n    await haa.set_variable('stopped_by', event.source)\n",
        )
        (event,) = automation.context.get_symbol("seen")

        assert type(event) is ActionEvent
        assert (event.source, event.caller, event.data, event.automation_id) == (
            "trigger",
            None,
            {},
            "lights",
        )

        await automation.stop()
        assert automation.last_error is None

    async def test_handlers_without_event(self, world: World) -> None:
        """The event parameter is optional for the handlers too."""
        automation = await world.start(
            "lights",
            "from haanim import startup, shutdown\nseen = []\n\n@startup\ndef on_start():\n    seen.append('started')\n\n@shutdown\ndef on_stop():\n    pass\n",
        )

        assert automation.state is AutomationState.ON
        assert automation.context.get_symbol("seen") == ["started"]
        await automation.stop()
        assert automation.last_error is None


class TestSignatureErrors:
    """A function that needs more than the event is refused when the automation starts."""

    @pytest.mark.parametrize(
        ("source", "message"),
        [
            (
                "from haanim import action\n\n@action\ndef add(a, b):\n    return a + b\n",
                "'add' cannot be called: it requires the parameters a, b; it can take the event only",
            ),
            (
                "from haanim import on_time\n\n@on_time('09:00')\ndef morning(event, *, room):\n    pass\n",
                "'morning' cannot be called: it requires the keyword argument room; it can take the event only",
            ),
            (
                "from haanim import startup\n\n@startup\ndef on_start(event, config):\n    pass\n",
                "'on_start' cannot be called: it requires the parameters event, config; it can take the event only",
            ),
        ],
        ids=["action", "trigger", "startup"],
    )
    async def test_start_error(self, world: World, source: str, message: str) -> None:
        """The automation ends in error with a message naming the function and its parameters."""
        automation = await world.start("lights", source)

        assert automation.state is AutomationState.ERROR
        assert automation.message == message

    async def test_undecorated_helpers_may_take_anything(self, world: World) -> None:
        """Only actions, triggers and lifecycle handlers are restricted; helpers are ordinary functions."""
        automation = await world.start(
            "lights",
            "from haanim import action\n\ndef helper(a, b, *, c):\n    return a + b + c\n\n@action\ndef go():\n    return helper(1, 2, c=3)\n",
        )

        assert await automation.call_action("go") == 6


def definition(trigger_type: str, expr: str, func: Any, **kwargs: Any) -> TriggerDefinition:
    """Build a trigger definition for a test function."""
    return TriggerDefinition(
        trigger_type=trigger_type,
        trigger_expr=expr,
        func_name="on_trigger",
        func=func,
        kwargs=kwargs,
        automation_id="lights",
    )


class TestTriggerFiredEvents:
    """Each kind of trigger delivers its own event type with source trigger and empty data."""

    @staticmethod
    def check_base(event: ActionEvent, clock: FakeClock) -> None:
        """Assert the base properties of a trigger-fired event."""
        assert (event.source, event.caller, event.data, event.automation_id) == (
            "trigger",
            None,
            {},
            "lights",
        )
        assert event.call_time == clock.now()

    async def test_interval_event(self) -> None:
        """IntervalEvent carries the interval in seconds and the count of executions."""
        clock = FakeClock()
        fired: list[IntervalEvent] = []
        trigger = IntervalTrigger(
            make_host(clock=clock), definition(TRIGGER_INTERVAL, "00:05:00", fired.append)
        )
        await trigger.async_start()

        await clock.advance(minutes=5)
        self.check_base(fired[0], clock)
        await clock.advance(minutes=10)
        await trigger.async_stop()

        assert [type(event) for event in fired] == [IntervalEvent] * 3
        assert [event.interval_seconds for event in fired] == [300.0, 300.0, 300.0]
        assert all(isinstance(event.interval_seconds, float) for event in fired)
        assert [event.execution_count for event in fired] == [1, 2, 3]

    async def test_cron_event(self) -> None:
        """CronEvent carries the expression and the time that matched it."""
        clock = FakeClock()
        fired: list[CronEvent] = []
        trigger = CronTrigger(make_host(clock=clock), definition(TRIGGER_CRON, "*/5 * * * *", fired.append))
        await trigger.async_start()

        await clock.advance(minutes=5)
        await trigger.async_stop()

        (event,) = fired
        assert type(event) is CronEvent
        assert event.cron_expression == "*/5 * * * *"
        assert event.trigger_time == DEFAULT_NOW + timedelta(minutes=5)
        self.check_base(event, clock)

    async def test_event_trigger_event(self) -> None:
        """EventTriggerEvent carries the event's type, data, time and user."""
        clock = FakeClock()
        bus = FakeEventBus(clock)
        fired: list[EventTriggerEvent] = []
        trigger = EventTrigger(
            make_host(clock=clock, events=bus), definition(TRIGGER_EVENT, "doorbell", fired.append)
        )
        await trigger.async_start()
        await clock.settle()

        bus.fire("doorbell", {"ring": 2})
        await clock.settle()
        await trigger.async_stop()

        (event,) = fired
        assert type(event) is EventTriggerEvent
        assert (event.event_type, event.event_data) == ("doorbell", {"ring": 2})
        assert event.time_fired == clock.now()
        assert event.user_id is None
        self.check_base(event, clock)

    async def test_state_event_from_the_trigger_class(self) -> None:
        """StateEvent carries the entity and its old and new state."""
        clock = FakeClock()
        states = FakeStateProvider(clock)
        states.set_state("sensor.temperature", "20")
        fired: list[StateEvent] = []
        trigger = StateTrigger(
            make_host(clock=clock, states=states),
            definition(TRIGGER_STATE, "sensor.temperature > 30", fired.append),
        )
        await trigger.async_start()
        await clock.settle()

        states.set_state("sensor.temperature", "35")
        await clock.settle()
        await trigger.async_stop()

        (event,) = fired
        assert type(event) is StateEvent
        assert event.entity_id == "sensor.temperature"
        assert event.old_state is not None and event.old_state.state == "20"
        assert event.new_state is not None and event.new_state.state == "35"
        self.check_base(event, clock)

    async def test_events_from_the_trigger_manager(self) -> None:
        """The manager that fires registered triggers builds StateEvent and TimeEvent."""
        clock = FakeClock()
        states = FakeStateProvider(clock)
        host = make_host(clock=clock, states=states)
        manager = TriggerManager(
            host, ActionDispatcher(ActionWorkerPool(status_manager=AutomationStatusManager(), clock=clock))
        )
        states.set_state("sensor.temperature", "20")
        old = states.get("sensor.temperature")
        states.set_state("sensor.temperature", "35")
        change = type(
            "Change",
            (),
            {
                "entity_id": "sensor.temperature",
                "old_state": old,
                "new_state": states.get("sensor.temperature"),
            },
        )()
        fired: list[ActionEvent] = []
        state_id = await manager.register_trigger(
            definition(TRIGGER_STATE, "sensor.temperature > 30", fired.append)
        )
        time_definition = definition(TRIGGER_TIME, "09:00", fired.append)
        time_definition.func_name = "at_nine"
        time_id = await manager.register_trigger(time_definition)

        await manager._execute_trigger(state_id, change)  # pylint: disable=protected-access
        await manager._execute_trigger(time_id)  # pylint: disable=protected-access

        state_event, time_event = fired
        assert type(state_event) is StateEvent
        assert (state_event.entity_id, state_event.old_state, state_event.new_state.state) == (
            "sensor.temperature",
            old,
            "35",
        )
        assert type(time_event) is TimeEvent
        assert time_event.trigger_time == clock.now()
        for event in fired:
            self.check_base(event, clock)

    async def test_trigger_function_without_event_parameter_is_called_without_it(self) -> None:
        """A trigger function declared without parameters is fired without the event."""
        clock = FakeClock()
        calls: list[str] = []

        def on_trigger() -> None:
            calls.append("fired")

        trigger = IntervalTrigger(make_host(clock=clock), definition(TRIGGER_INTERVAL, "60", on_trigger))
        await trigger.async_start()
        await clock.advance(seconds=60)
        await trigger.async_stop()

        assert calls == ["fired"]

    async def test_trigger_fired_action_can_be_awaited_with_the_event(self) -> None:
        """An async trigger function receives the event as well."""
        clock = FakeClock()
        fired: list[Any] = []

        async def on_trigger(event: IntervalEvent) -> None:
            await asyncio.sleep(0)
            fired.append(event.execution_count)

        trigger = IntervalTrigger(make_host(clock=clock), definition(TRIGGER_INTERVAL, "60", on_trigger))
        await trigger.async_start()
        await clock.advance(seconds=120)
        await trigger.async_stop()

        assert fired == [1, 2]
