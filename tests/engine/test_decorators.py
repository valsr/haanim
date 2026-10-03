"""Tests for the decorators and for what an automation defines with them."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from haanim import ActionMode
from haanim.const import TRIGGER_CRON, TRIGGER_EVENT, TRIGGER_INTERVAL, TRIGGER_STATE, TRIGGER_TIME
from haanim.engine import decorators
from haanim.engine.action_pool import ActionWorkerPool
from haanim.engine.automation_context import AutomationContext
from haanim.engine.automation_status import AutomationStatusManager
from haanim.engine.decorators import (
    CONSTRAINT_ARGUMENTS,
    ActionInfo,
    FunctionMetadata,
    TriggerInfo,
    action,
    get_metadata,
    has_metadata,
    on_cron,
    on_event,
    on_interval,
    on_state,
    on_time,
    shutdown,
    startup,
)
from haanim.engine.errors import (
    ActionNotFoundError,
    AutomationDefinitionError,
    AutomationRuntimeError,
    HAAnimError,
)
from haanim.engine.haanim_module import DECORATORS
from haanim.engine.lifecycle import Automation, AutomationState
from haanim.testing import FakeClock, LocalFileSystem, make_host
from tests.engine.helpers import automation_file, load_and_run, make_context

# The decorator surface of the design: the five triggers, the action decorator and the two lifecycle ones.
DESIGN_DECORATORS = [
    "action",
    "startup",
    "shutdown",
    "on_time",
    "on_interval",
    "on_cron",
    "on_event",
    "on_state",
]

# Each trigger decorator with a valid first argument and the kind of trigger it attaches.
TRIGGERS: dict[str, tuple[Any, Any, str]] = {
    "on_time": (on_time, "09:00", TRIGGER_TIME),
    "on_interval": (on_interval, "00:05:00", TRIGGER_INTERVAL),
    "on_cron": (on_cron, "30 8 * * 1-5", TRIGGER_CRON),
    "on_event": (on_event, "doorbell", TRIGGER_EVENT),
    "on_state": (on_state, "sensor.temperature > 30", TRIGGER_STATE),
}

# One valid value for each constraint argument.
CONSTRAINTS = {
    "start_time": "08:00",
    "end_time": "18:00",
    "start_date": "April 1",
    "end_date": "May 19",
    "day_of_week": "weekdays",
    "when": "person.john == 'home'",
    "when_not": "input_boolean.sleep_mode == 'on'",
}


def function() -> Any:
    """Return a fresh function to decorate."""

    def target() -> None:
        pass

    return target


def metadata_of(func: Any) -> FunctionMetadata:
    """Return the metadata of a decorated function."""
    metadata = get_metadata(func)
    assert metadata is not None
    return metadata


async def executed(tmp_path: Path, source: str, name: str = "lights") -> AutomationContext:
    """Write an automation and run its main.py."""
    path = automation_file(tmp_path, name)
    path.write_text(source, encoding="utf-8")
    context = make_context(str(path))
    await load_and_run(context)
    return context


class TestSurface:
    """The decorators an automation can import are the design's."""

    def test_names(self) -> None:
        """Exactly the eight decorators of the design are offered."""
        assert sorted(DECORATORS) == sorted(DESIGN_DECORATORS)

    @pytest.mark.parametrize("name", DESIGN_DECORATORS)
    def test_is_the_engines_decorator(self, name: str) -> None:
        """Each name is the decorator of that name in the engine."""
        assert DECORATORS[name] is getattr(decorators, name)

    def test_trigger_decorators_are_prefixed(self) -> None:
        """No trigger decorator shadows the time module or the conventional event parameter."""
        assert [name for name in DECORATORS if name.startswith("on_")] == sorted(
            TRIGGERS, key=list(DECORATORS).index
        )
        assert not {"time", "event", "state", "interval", "cron"} & set(DECORATORS)

    def test_constraint_arguments_are_the_designs(self) -> None:
        """The constraint keywords are those of the design's Constraints section."""
        assert set(CONSTRAINT_ARGUMENTS) == set(CONSTRAINTS)


class TestAction:
    """@action and its options."""

    def test_without_arguments(self) -> None:
        """@action marks the function and returns it unchanged, with the defaults."""
        func = function()

        assert action(func) is func
        metadata = metadata_of(func)
        assert metadata.is_action
        assert metadata.action_info == ActionInfo()
        assert metadata.action_info == ActionInfo(
            name=None,
            aliases=(),
            description=None,
            execution_mode=ActionMode.DROP,
            timeout=None,
            disabled=False,
        )

    def test_with_empty_parentheses(self) -> None:
        """@action() is the same as @action."""
        func = function()

        assert action()(func) is func
        assert metadata_of(func).action_info == ActionInfo()

    @pytest.mark.parametrize(
        ("option", "value", "stored"),
        [
            ("name", "custom name", "custom name"),
            ("aliases", ["custom alias", "other"], ("custom alias", "other")),
            ("aliases", ("a",), ("a",)),
            ("aliases", [], ()),
            ("description", "This is a custom action.", "This is a custom action."),
            ("execution_mode", ActionMode.QUEUE, ActionMode.QUEUE),
            ("execution_mode", ActionMode.CANCEL, ActionMode.CANCEL),
            ("timeout", 30, 30),
            ("timeout", 0.5, 0.5),
            ("timeout", 0, 0),
            ("disabled", True, True),
        ],
    )
    def test_each_option(self, option: str, value: Any, stored: Any) -> None:
        """Each option is recorded; the others keep their defaults."""
        func = function()

        action(**{option: value})(func)

        info = metadata_of(func).action_info
        assert info is not None
        assert getattr(info, option) == stored
        for other, default in vars(ActionInfo()).items():
            if other != option:
                assert getattr(info, other) == default

    def test_all_options(self) -> None:
        """The design's full example."""
        func = function()

        action(
            name="other name",
            aliases=["custom alias"],
            description="This is a custom action.",
            execution_mode=ActionMode.CANCEL,
            timeout=30,
            disabled=True,
        )(func)

        assert metadata_of(func).action_info == ActionInfo(
            name="other name",
            aliases=("custom alias",),
            description="This is a custom action.",
            execution_mode=ActionMode.CANCEL,
            timeout=30,
            disabled=True,
        )

    @pytest.mark.parametrize(
        ("options", "error", "message"),
        [
            ({"name": ""}, ValueError, "name must not be empty"),
            ({"name": "  "}, ValueError, "name must not be empty"),
            ({"name": 5}, TypeError, "name must be a string, not int"),
            ({"aliases": "alias"}, TypeError, "aliases must be a list of strings"),
            ({"aliases": [5]}, TypeError, "an alias must be a string, not int"),
            ({"aliases": [""]}, ValueError, "an alias must not be empty"),
            ({"description": 5}, TypeError, "description must be a string"),
            ({"execution_mode": "queue"}, TypeError, "execution_mode must be an ActionMode"),
            ({"timeout": "30"}, TypeError, "timeout must be a number of seconds, not str"),
            ({"timeout": True}, TypeError, "timeout must be a number of seconds, not bool"),
            ({"timeout": -1}, ValueError, "timeout must not be negative"),
            ({"disabled": "yes"}, TypeError, "disabled must be True or False"),
        ],
    )
    def test_invalid_option(self, options: dict[str, Any], error: type[Exception], message: str) -> None:
        """A wrong option is refused when the decorator is written, naming the option."""
        with pytest.raises(error, match=message):
            action(**options)

    def test_unknown_option(self) -> None:
        """An option that does not exist is a TypeError, as for any function."""
        with pytest.raises(TypeError, match="queue_size"):
            action(queue_size=10)  # type: ignore[call-overload]

    def test_name_is_keyword_only(self) -> None:
        """@action("name") is not accepted; the name is given as name=."""
        with pytest.raises(
            TypeError, match=r"@action takes keyword arguments only: write @action\(name=...\)"
        ):
            action("custom name")  # type: ignore[call-overload]

    def test_used_twice(self) -> None:
        """Two @action on one function is a mistake: one function is one action."""
        func = action(function())

        with pytest.raises(ValueError, match="@action is used more than once on 'target'"):
            action(name="again")(func)

    def test_must_decorate_a_function(self) -> None:
        """@action(...) applied to something that is not callable is refused."""
        with pytest.raises(TypeError, match="@action must decorate a function, not int"):
            action(name="x")(5)  # type: ignore[type-var]


class TestTriggers:
    """The five trigger decorators."""

    @pytest.mark.parametrize("name", TRIGGERS)
    def test_attaches_a_trigger(self, name: str) -> None:
        """Each decorator records one trigger of its kind and returns the function unchanged."""
        decorator, expr, kind = TRIGGERS[name]
        func = function()

        assert decorator(expr)(func) is func
        metadata = metadata_of(func)
        assert metadata.triggers == [
            TriggerInfo(trigger_type=kind, trigger_expr=expr, kwargs={}, constraints={})
        ]
        assert metadata.is_action
        assert metadata.action_info is None

    @pytest.mark.parametrize("name", TRIGGERS)
    @pytest.mark.parametrize("constraint", CONSTRAINTS)
    def test_accepts_each_constraint(self, name: str, constraint: str) -> None:
        """Every trigger decorator takes every constraint keyword and stores it as written."""
        decorator, expr, _ = TRIGGERS[name]
        func = function()

        decorator(expr, **{constraint: CONSTRAINTS[constraint]})(func)

        (trigger,) = metadata_of(func).triggers
        if name == "on_time" and constraint == "day_of_week":
            # For the time trigger day_of_week is the trigger's own option; it does the same job.
            assert trigger.kwargs == {"day_of_week": "weekdays"}
            assert trigger.constraints == {}
        else:
            assert trigger.constraints == {constraint: CONSTRAINTS[constraint]}
            assert trigger.kwargs == {}

    @pytest.mark.parametrize("name", TRIGGERS)
    def test_all_constraints_together(self, name: str) -> None:
        """All constraints can be given at once."""
        decorator, expr, _ = TRIGGERS[name]
        func = function()

        decorator(expr, **CONSTRAINTS)(func)

        (trigger,) = metadata_of(func).triggers
        stored = {**trigger.constraints, **{k: v for k, v in trigger.kwargs.items() if k == "day_of_week"}}
        assert stored == CONSTRAINTS

    @pytest.mark.parametrize("name", TRIGGERS)
    def test_unknown_keyword(self, name: str) -> None:
        """A keyword that is neither an option nor a constraint is a TypeError."""
        decorator, expr, _ = TRIGGERS[name]

        with pytest.raises(TypeError, match="state_check_now"):
            decorator(expr, state_check_now=True)

    @pytest.mark.parametrize("name", TRIGGERS)
    @pytest.mark.parametrize("constraint", [name for name in CONSTRAINTS if name != "day_of_week"])
    def test_constraint_of_the_wrong_type(self, name: str, constraint: str) -> None:
        """A constraint that is not a string is refused, naming the decorator and the argument."""
        decorator, expr, _ = TRIGGERS[name]

        with pytest.raises(TypeError, match=f"@{name}: {constraint} must be a string, not int"):
            decorator(expr, **{constraint: 5})

    @pytest.mark.parametrize("name", TRIGGERS)
    def test_day_of_week_can_be_an_index(self, name: str) -> None:
        """day_of_week takes a name list or a day index."""
        decorator, expr, _ = TRIGGERS[name]
        func = function()

        decorator(expr, day_of_week=0)(func)
        with pytest.raises(TypeError, match="day_of_week must be a string, not list"):
            decorator(expr, day_of_week=["monday"])

    @pytest.mark.parametrize("name", [name for name in TRIGGERS if name != "on_interval"])
    @pytest.mark.parametrize(
        ("expr", "error"), [("", ValueError), ("   ", ValueError), (5, TypeError), (None, TypeError)]
    )
    def test_invalid_expression(self, name: str, expr: Any, error: type[Exception]) -> None:
        """The first argument has to be a non-empty string."""
        with pytest.raises(error, match=f"@{name}: "):
            TRIGGERS[name][0](expr)

    @pytest.mark.parametrize("name", TRIGGERS)
    def test_must_decorate_a_function(self, name: str) -> None:
        """A trigger decorator applied to something that is not callable is refused."""
        decorator, expr, _ = TRIGGERS[name]

        with pytest.raises(TypeError, match=f"@{name} must decorate a function, not str"):
            decorator(expr)("not a function")

    def test_on_time_options(self) -> None:
        """@on_time takes day_of_week and day_of_month."""
        func = function()

        on_time("09:00:00", day_of_week="monday,wednesday,friday", day_of_month="1,15")(func)

        (trigger,) = metadata_of(func).triggers
        assert trigger.trigger_expr == "09:00:00"
        assert trigger.kwargs == {"day_of_week": "monday,wednesday,friday", "day_of_month": "1,15"}
        with pytest.raises(TypeError, match="day_of_month must be a string, not list"):
            on_time("09:00", day_of_month=[1])  # type: ignore[arg-type]

    @pytest.mark.parametrize("interval", ["00:05:00", 300, 0.5])
    def test_on_interval_options(self, interval: Any) -> None:
        """@on_interval takes seconds or HH:MM:SS, and a delay in the same formats."""
        func = function()

        on_interval(interval, delay="00:01:00")(func)

        (trigger,) = metadata_of(func).triggers
        assert trigger.trigger_expr == interval
        assert trigger.kwargs == {"delay": "00:01:00"}

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            ({"interval": None}, "the interval must be seconds or 'HH:MM:SS', not NoneType"),
            ({"interval": True}, "the interval must be seconds or 'HH:MM:SS', not bool"),
            ({"interval": 5, "delay": [1]}, "delay must be seconds or 'HH:MM:SS', not list"),
        ],
    )
    def test_on_interval_invalid(self, arguments: dict[str, Any], message: str) -> None:
        """A duration of the wrong type is refused."""
        with pytest.raises(TypeError, match=message):
            on_interval(arguments["interval"], delay=arguments.get("delay"))

    def test_on_event_options(self) -> None:
        """@on_event takes a data filter, which is copied."""
        data = {"command": "toggle", "device_ieee": "00:11"}
        func = function()

        on_event("zha_event", data=data)(func)
        data["command"] = "changed afterwards"

        (trigger,) = metadata_of(func).triggers
        assert trigger.trigger_expr == "zha_event"
        assert trigger.kwargs == {"data": {"command": "toggle", "device_ieee": "00:11"}}
        with pytest.raises(TypeError, match="data must be a dict, not list"):
            on_event("zha_event", data=["x"])  # type: ignore[arg-type]

    def test_on_state_options(self) -> None:
        """@on_state takes every_change and hold."""
        func = function()

        on_state("sensor.temperature > 30", every_change=True, hold="00:01:00")(func)

        (trigger,) = metadata_of(func).triggers
        assert trigger.kwargs == {"every_change": True, "hold": "00:01:00"}
        on_state("sensor.a == 'on'", hold=30)(function())
        with pytest.raises(TypeError, match="every_change must be True or False, not str"):
            on_state("sensor.a == 'on'", every_change="yes")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="hold must be seconds or 'HH:MM:SS', not list"):
            on_state("sensor.a == 'on'", hold=[1])  # type: ignore[arg-type]

    def test_edge_triggering_is_the_default(self) -> None:
        """Without every_change the option is not stored: the trigger is edge-triggered."""
        func = function()

        on_state("sensor.a == 'on'")(func)

        assert metadata_of(func).triggers[0].kwargs == {}


class TestLifecycleDecorators:
    """@startup and @shutdown."""

    def test_startup(self) -> None:
        """@startup marks the function and returns it."""
        func = function()

        assert startup(func) is func
        metadata = metadata_of(func)
        assert (metadata.is_startup, metadata.is_shutdown, metadata.is_action) == (True, False, False)

    def test_shutdown(self) -> None:
        """@shutdown marks the function and returns it."""
        func = function()

        assert shutdown(func) is func
        metadata = metadata_of(func)
        assert (metadata.is_startup, metadata.is_shutdown, metadata.is_action) == (False, True, False)

    @pytest.mark.parametrize("decorator", [startup, shutdown])
    def test_must_decorate_a_function(self, decorator: Any) -> None:
        """They are used without parentheses, on a function."""
        with pytest.raises(TypeError, match="must decorate a function"):
            decorator("name")


class TestStacking:
    """One function is one action, however its decorators are stacked."""

    def test_action_above_trigger(self) -> None:
        """@action on top of a trigger configures the trigger function's action."""
        func = action(name="heat", timeout=30)(on_state("sensor.t > 30")(function()))

        metadata = metadata_of(func)
        assert metadata.action_info == ActionInfo(name="heat", timeout=30)
        assert [trigger.trigger_type for trigger in metadata.triggers] == [TRIGGER_STATE]

    def test_action_below_trigger(self) -> None:
        """The order of the decorators does not matter."""
        above = metadata_of(action(name="heat", timeout=30)(on_state("sensor.t > 30")(function())))
        below = metadata_of(on_state("sensor.t > 30")(action(name="heat", timeout=30)(function())))

        assert above == below

    def test_several_triggers_in_source_order(self) -> None:
        """Stacked triggers are all kept, top decorator first."""
        func = on_time("09:00")(on_interval(60)(on_event("doorbell")(function())))

        assert [trigger.trigger_type for trigger in metadata_of(func).triggers] == [
            TRIGGER_TIME,
            TRIGGER_INTERVAL,
            TRIGGER_EVENT,
        ]

    def test_same_trigger_twice(self) -> None:
        """A function can have the same kind of trigger more than once."""
        func = on_time("09:00")(on_time("18:00")(function()))

        assert [trigger.trigger_expr for trigger in metadata_of(func).triggers] == ["09:00", "18:00"]

    def test_constraints_belong_to_their_trigger(self) -> None:
        """With stacked triggers each decorator's constraints apply to that trigger only."""
        func = on_time("09:00", when="person.john == 'home'")(
            on_event("doorbell", start_time="08:00")(function())
        )

        first, second = metadata_of(func).triggers
        assert first.constraints == {"when": "person.john == 'home'"}
        assert second.constraints == {"start_time": "08:00"}

    def test_trigger_function_without_action_has_the_defaults(self) -> None:
        """Without @action a trigger function is an action with no configuration of its own."""
        metadata = metadata_of(on_time("09:00")(function()))

        assert metadata.is_action
        assert metadata.action_info is None

    def test_startup_and_action_on_one_function(self) -> None:
        """A lifecycle handler can also be an action."""
        metadata = metadata_of(startup(action(function())))

        assert metadata.is_startup and metadata.is_action


class TestMetadataHelpers:
    """Reading what the decorators recorded."""

    def test_undecorated_function(self) -> None:
        """A plain function has no metadata."""
        func = function()

        assert has_metadata(func) is False
        assert get_metadata(func) is None

    def test_decorated_function(self) -> None:
        """A decorated function has."""
        func = action(function())

        assert has_metadata(func) is True
        assert isinstance(get_metadata(func), FunctionMetadata)

    def test_defaults(self) -> None:
        """Empty metadata describes a function that is nothing yet."""
        metadata = FunctionMetadata()

        assert metadata.action_info is None
        assert metadata.triggers == []
        assert (metadata.is_startup, metadata.is_shutdown, metadata.is_action) == (False, False, False)


class TestDefinitions:
    """What an executed automation defines."""

    async def test_names_and_aliases(self, tmp_path: Path) -> None:
        """An action is addressed by its name, or the function name without one, and by each alias."""
        context = await executed(
            tmp_path,
            "from haanim import action\n\n@action\ndef plain():\n    return 'plain'\n\n"
            "@action(name='custom name', aliases=['alias one', 'two'])\ndef renamed():\n    return 'renamed'\n",
        )

        assert [definition.name for definition in context.get_actions()] == ["plain", "custom name"]
        renamed = context.get_action("custom name")
        assert renamed is not None
        assert renamed.names == ("custom name", "alias one", "two")
        assert context.get_action("alias one") is renamed
        assert context.get_action("two") is renamed
        assert context.get_action("plain") is not None
        # The function name does not address an action that was given another name.
        assert context.get_action("renamed") is None
        assert context.get_action("unknown") is None
        assert await context.run_action("alias one") == "renamed"

    async def test_options_reach_the_definition(self, tmp_path: Path) -> None:
        """Every option of @action is on the action's definition."""
        context = await executed(
            tmp_path,
            "from haanim import action, ActionMode\n\n@action(name='n', aliases=['a'], description='d',"
            " execution_mode=ActionMode.QUEUE, timeout=12, disabled=True)\ndef configured():\n    pass\n",
        )

        definition = context.get_action("n")
        assert definition is not None
        assert (definition.func_name, definition.description, definition.aliases) == (
            "configured",
            "d",
            ("a",),
        )
        assert (definition.execution_mode, definition.timeout, definition.disabled) == (
            ActionMode.QUEUE,
            12,
            True,
        )
        assert definition.automation_id == "lights"

    async def test_defaults_without_action(self, tmp_path: Path) -> None:
        """A trigger function without @action is an action with the function name and the defaults."""
        context = await executed(
            tmp_path, "from haanim import on_time\n\n@on_time('09:00')\ndef morning():\n    return 'done'\n"
        )

        definition = context.get_action("morning")
        assert definition is not None
        assert (definition.name, definition.aliases, definition.description) == ("morning", (), None)
        assert (definition.execution_mode, definition.timeout, definition.disabled) == (
            ActionMode.DROP,
            None,
            False,
        )
        assert await context.run_action("morning") == "done"

    @pytest.mark.parametrize(
        "decorators_text",
        [
            "@action(name='heat', timeout=30)\n@on_state('sensor.t > 30')",
            "@on_state('sensor.t > 30')\n@action(name='heat', timeout=30)",
        ],
        ids=["action above", "action below"],
    )
    async def test_stacked_in_either_order_is_one_action(self, tmp_path: Path, decorators_text: str) -> None:
        """A function with @action and a trigger is one action and one trigger."""
        context = await executed(
            tmp_path, f"from haanim import action, on_state\n\n{decorators_text}\ndef react():\n    pass\n"
        )

        (definition,) = context.get_actions()
        (trigger,) = context.get_triggers()
        assert (definition.name, definition.timeout) == ("heat", 30)
        assert (trigger.trigger_type, trigger.trigger_expr, trigger.func_name) == (
            TRIGGER_STATE,
            "sensor.t > 30",
            "react",
        )
        assert trigger.func is definition.func

    async def test_trigger_definition_carries_options_and_constraints(self, tmp_path: Path) -> None:
        """The trigger's options and its constraints are kept apart, as written."""
        context = await executed(
            tmp_path,
            "from haanim import on_state, on_event\n\n"
            "@on_state('sensor.t > 30', every_change=True, hold=5, when='person.john == \"home\"', day_of_week='weekdays')\n"
            "@on_event('doorbell', data={'ring': 2}, start_time='08:00', end_time='18:00')\n"
            "def react():\n    pass\n",
        )

        state, event = context.get_triggers()
        assert state.kwargs == {"every_change": True, "hold": 5}
        assert state.constraints == {"when": 'person.john == "home"', "day_of_week": "weekdays"}
        assert (event.trigger_expr, event.kwargs) == ("doorbell", {"data": {"ring": 2}})
        assert event.constraints == {"start_time": "08:00", "end_time": "18:00"}
        assert state.automation_id == event.automation_id == "lights"

    @pytest.mark.parametrize(
        ("first", "second", "name"),
        [
            ("@action\ndef go():", "@action(name='go')\ndef other():", "go"),
            ("@action(name='same')\ndef one():", "@action(name='same')\ndef two():", "same"),
            ("@action(aliases=['x'])\ndef one():", "@action(aliases=['x'])\ndef two():", "x"),
            ("@action(name='x')\ndef one():", "@action(aliases=['x'])\ndef two():", "x"),
            ("@action(aliases=['two'])\ndef one():", "@action\ndef two():", "two"),
            ("@on_time('09:00')\ndef morning():", "@action(name='morning')\ndef other():", "morning"),
        ],
        ids=[
            "function name and name",
            "two names",
            "two aliases",
            "name and alias",
            "alias and function name",
            "trigger function",
        ],
    )
    async def test_duplicate_name(self, tmp_path: Path, first: str, second: str, name: str) -> None:
        """A name or alias used by two actions is an error naming the name and both functions."""
        source = f"from haanim import action, on_time\n\n{first}\n    pass\n\n{second}\n    pass\n"
        functions = [line.split("def ")[1].rstrip("():") for line in (first, second)]

        with pytest.raises(AutomationDefinitionError) as raised:
            await executed(tmp_path, source)

        assert (
            str(raised.value) == f"Action name '{name}' is used by both '{functions[0]}' and '{functions[1]}'"
        )
        assert issubclass(AutomationDefinitionError, HAAnimError)

    async def test_alias_repeating_the_actions_own_name_is_not_a_duplicate(self, tmp_path: Path) -> None:
        """An alias equal to the action's own name is harmless."""
        context = await executed(
            tmp_path, "from haanim import action\n\n@action(aliases=['go', 'go'])\ndef go():\n    pass\n"
        )

        assert len(context.get_actions()) == 1

    async def test_duplicate_across_files(self, tmp_path: Path) -> None:
        """Names must be unique within the automation, whichever file the actions are in."""
        path = automation_file(tmp_path, "lights")
        path.write_text(
            "from haanim import action\nfrom . import scenes\n\n@action\ndef evening():\n    pass\n",
            encoding="utf-8",
        )
        (path.parent / "scenes.py").write_text(
            "from haanim import action\n\n@action\ndef evening():\n    pass\n", encoding="utf-8"
        )

        with pytest.raises(AutomationDefinitionError, match="Action name 'evening' is used by both"):
            await load_and_run(make_context(str(path)))

    @pytest.mark.parametrize("kind", ["startup", "shutdown"])
    async def test_more_than_one_lifecycle_handler(self, tmp_path: Path, kind: str) -> None:
        """Two @startup, or two @shutdown, is an error naming both functions."""
        source = f"from haanim import {kind}\n\n@{kind}\ndef first():\n    pass\n\n@{kind}\ndef second():\n    pass\n"

        with pytest.raises(AutomationDefinitionError) as raised:
            await executed(tmp_path, source)

        assert str(raised.value) == f"More than one @{kind} handler: 'first' and 'second'"

    async def test_one_of_each_lifecycle_handler(self, tmp_path: Path) -> None:
        """One @startup and one @shutdown are fine, and may be the same function."""
        context = await executed(
            tmp_path, "from haanim import startup, shutdown\n\n@startup\n@shutdown\ndef both():\n    pass\n"
        )

        assert context.get_startup_func() is context.get_shutdown_func()

    async def test_invalid_decorator_argument_fails_the_execution(self, tmp_path: Path) -> None:
        """A wrong decorator argument stops the automation's code where it is written."""
        with pytest.raises(AutomationRuntimeError, match="@action: timeout must not be negative"):
            await executed(
                tmp_path, "from haanim import action\n\n@action(timeout=-5)\ndef go():\n    pass\n"
            )

    async def test_failed_execution_leaves_no_definitions(self, tmp_path: Path) -> None:
        """After a duplicate the automation has no actions; nothing half-defined remains."""
        path = automation_file(tmp_path, "lights")
        path.write_text(
            "from haanim import action\n\n@action\ndef go():\n    pass\n\n@action(name='go')\ndef again():\n    pass\n",
            encoding="utf-8",
        )
        context = make_context(str(path))

        with pytest.raises(AutomationDefinitionError):
            await load_and_run(context)

        assert context.get_actions() == []
        assert context.get_action("go") is None
        assert not context.is_executed


class RecordingTriggers:
    """A registrar that records the functions whose triggers are registered."""

    def __init__(self) -> None:
        self.registered: list[str] = []

    async def register_trigger(self, trigger_def: Any, constraints: Any = None) -> str:
        """Record a trigger."""
        self.registered.append(trigger_def.func_name)
        return trigger_def.func_name

    async def unregister_automation_triggers(self, automation_id: str) -> int:
        """Forget everything."""
        self.registered.clear()
        return 0


async def started(tmp_path: Path, source: str, name: str = "lights") -> tuple[Automation, RecordingTriggers]:
    """Write an automation and take it through load and start."""
    path = automation_file(tmp_path, name)
    path.write_text(source, encoding="utf-8")
    clock = FakeClock()
    host = make_host(files=LocalFileSystem(), clock=clock)
    triggers = RecordingTriggers()
    pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=clock)
    automation = Automation(
        make_context(str(path), host=host, storage_path=str(tmp_path / ".storage")),
        pool=pool,
        triggers=triggers,
    )
    await automation.load()
    await automation.start()
    return automation, triggers


class TestAtStart:
    """Definition errors and disabled actions when an automation starts."""

    DISABLED = (
        "from haanim import action, on_time, on_state\n\n"
        "@action(disabled=True)\n@on_time('09:00')\ndef off_for_now():\n    return 'ran'\n\n"
        "@action(name='other name', aliases=['custom alias'], disabled=True)\ndef renamed():\n    return 'ran'\n\n"
        "@on_state(\"sensor.a == 'on'\")\ndef active():\n    return 'ran'\n"
    )

    async def test_disabled_action_is_listed(self, tmp_path: Path) -> None:
        """A disabled action appears in the automation's actions, marked disabled."""
        automation, _ = await started(tmp_path, self.DISABLED)

        listed = {definition.name: definition.disabled for definition in automation.context.get_actions()}
        assert listed == {"off_for_now": True, "other name": True, "active": False}

    @pytest.mark.parametrize("name", ["off_for_now", "other name", "custom alias"])
    async def test_disabled_action_cannot_be_called(self, tmp_path: Path, name: str) -> None:
        """Calling a disabled action, by name or alias, raises ActionNotFoundError."""
        automation, _ = await started(tmp_path, self.DISABLED)

        with pytest.raises(ActionNotFoundError) as raised:
            await automation.call_action(name)

        assert (raised.value.automation_id, raised.value.action_name) == ("lights", name)
        with pytest.raises(HAAnimError, match=f"Action '{name}' not found"):
            await automation.context.run_action(name)
        assert await automation.call_action("active") == "ran"

    async def test_triggers_of_a_disabled_action_are_not_registered(self, tmp_path: Path) -> None:
        """Only the triggers of enabled actions are registered."""
        automation, triggers = await started(tmp_path, self.DISABLED)

        assert automation.state is AutomationState.ON
        assert triggers.registered == ["active"]
        assert [trigger.func_name for trigger in automation.context.get_triggers()] == ["active"]

    async def test_name_of_a_disabled_action_is_still_taken(self, tmp_path: Path) -> None:
        """A disabled action keeps its names: another action cannot use them."""
        automation, _ = await started(
            tmp_path,
            "from haanim import action\n\n@action(disabled=True)\ndef go():\n    pass\n\n@action(name='go')\ndef other():\n    pass\n",
        )

        assert automation.state is AutomationState.ERROR
        assert automation.message == "Action name 'go' is used by both 'go' and 'other'"

    @pytest.mark.parametrize(
        ("source", "message"),
        [
            (
                "from haanim import action\n\n@action\ndef go():\n    pass\n\n@action(aliases=['go'])\ndef other():\n    pass\n",
                "Action name 'go' is used by both 'go' and 'other'",
            ),
            (
                "from haanim import startup\n\n@startup\ndef a():\n    pass\n\n@startup\ndef b():\n    pass\n",
                "More than one @startup handler: 'a' and 'b'",
            ),
            (
                "from haanim import shutdown\n\n@shutdown\ndef a():\n    pass\n\n@shutdown\ndef b():\n    pass\n",
                "More than one @shutdown handler: 'a' and 'b'",
            ),
        ],
        ids=["duplicate name", "two startup", "two shutdown"],
    )
    async def test_definition_error_is_a_start_error(self, tmp_path: Path, source: str, message: str) -> None:
        """The automation ends in error with the message; nothing is registered and nothing ran."""
        automation, triggers = await started(tmp_path, source)

        assert automation.state is AutomationState.ERROR
        assert automation.message == message
        assert triggers.registered == []
        assert not automation.context.is_executed

    async def test_wrong_decorator_argument_is_a_start_error(self, tmp_path: Path) -> None:
        """A decorator argument of the wrong type puts the automation in error, naming the argument."""
        automation, _ = await started(
            tmp_path,
            "from haanim import on_state\n\n@on_state('sensor.a > 1', hold=[5])\ndef go():\n    pass\n",
        )

        assert automation.state is AutomationState.ERROR
        assert "@on_state: hold must be seconds or 'HH:MM:SS', not list" in (automation.message or "")

    async def test_example_automation_starts(self, tmp_path: Path) -> None:
        """The example in the repository uses the decorators as they are now."""
        example = Path(__file__).parents[2] / "examples" / "demo"
        shutil.copytree(example, tmp_path / "demo")
        clock = FakeClock()
        host = make_host(files=LocalFileSystem(), clock=clock)
        triggers = RecordingTriggers()
        pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=clock)
        context = make_context(str(tmp_path / "demo"), host=host, storage_path=str(tmp_path / ".storage"))
        automation = Automation(context, pool=pool, triggers=triggers)

        assert await automation.load(), automation.message
        await automation.context.execute()

        assert len(automation.context.get_actions()) >= 10
        kinds = {trigger.trigger_type for trigger in automation.context.get_triggers()}
        assert kinds == {TRIGGER_TIME, TRIGGER_STATE, TRIGGER_INTERVAL, TRIGGER_CRON, TRIGGER_EVENT}
