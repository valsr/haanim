"""Tests for the state trigger.

See "State Trigger" in the design: Firing rules and Edge Cases.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from haanim.const import TRIGGER_STATE
from haanim.engine.automation_context import TriggerDefinition
from haanim.engine.errors import AutomationSyntaxError
from haanim.engine.lifecycle import AutomationState
from haanim.engine.triggers import StateTrigger
from haanim.engine.triggers.manager import TriggerManager
from haanim.events import ManualEvent, StateEvent
from haanim.testing.fakes import DEFAULT_NOW
from tests.engine.test_lifecycle import World


class StateWorld(World):
    """A world whose triggers are fired by the real trigger manager."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.triggers = TriggerManager(self.host, self.dispatcher)  # type: ignore[assignment]

    async def set(self, entity_id: str, state: str, **attributes: Any) -> None:
        """Change an entity and let the triggers react."""
        self.host.states.set_state(entity_id, state, attributes)
        await self.clock.settle()

    def changes(self) -> list[tuple[str, str | None, str | None]]:
        """Return the logged events as (entity, old state, new state)."""
        return [
            (
                event.entity_id,
                event.old_state.state if event.old_state is not None else None,
                event.new_state.state if event.new_state is not None else None,
            )
            for event in self.log
        ]


@pytest.fixture
def state_world(tmp_path: Path) -> StateWorld:
    """A world with a real trigger manager."""
    return StateWorld(tmp_path)


def source(decorator: str) -> str:
    """An automation with one state trigger function that logs its event."""
    return f"from haanim import on_state\n\n{decorator}\ndef react(event):\n    log.append(event)\n"


LIGHT = "@on_state(\"light.living_room == 'on'\")"
HOT = '@on_state("sensor.temperature > 25")'


class TestReEvaluation:
    """Rule: re-evaluated when the state or an attribute of a referenced entity changes; never otherwise."""

    async def test_state_change_of_a_referenced_entity(self, state_world: StateWorld) -> None:
        """The design's example: the light turns on."""
        await state_world.set("light.living_room", "off")
        await state_world.started("lights", source(LIGHT))

        await state_world.set("light.living_room", "on")
        assert state_world.changes() == [("light.living_room", "off", "on")]

    async def test_attribute_change_re_evaluates(self, state_world: StateWorld) -> None:
        """A change of an attribute alone causes an evaluation."""
        await state_world.set("light.living_room", "on", brightness=50)
        await state_world.started("lights", source("@on_state(\"light.living_room['brightness'] > 100\")"))

        await state_world.set("light.living_room", "on", brightness=200)
        assert state_world.changes() == [("light.living_room", "on", "on")]
        assert state_world.log[0].new_state.attributes == {"brightness": 200}

    async def test_unrelated_entity_does_not_re_evaluate(self, state_world: StateWorld) -> None:
        """Changes to other entities never cause an evaluation."""
        await state_world.set("light.living_room", "off")
        automation = await state_world.started("lights", source(LIGHT))
        (trigger_id,) = state_world.triggers.get_trigger_ids("lights")  # type: ignore[attr-defined]
        trigger = state_world.triggers.get_trigger(trigger_id)  # type: ignore[attr-defined]
        evaluations: list[str] = []
        original = trigger._on_change  # pylint: disable=protected-access
        trigger._on_change = lambda change: (evaluations.append(change.entity_id), original(change))[1]

        await state_world.set("light.kitchen", "on")
        await state_world.set("sensor.temperature", "30")
        assert evaluations == []
        await state_world.set("light.living_room", "on")
        assert evaluations == ["light.living_room"]
        assert automation.state is AutomationState.ON

    async def test_subscribes_only_to_referenced_entities(self, state_world: StateWorld) -> None:
        """The trigger listens to the entities of its expression and to nothing else."""
        await state_world.started(
            "climate", source('@on_state("sensor.temperature1 > 75 or sensor.temperature2 < 65")')
        )
        states = state_world.host.states
        assert states.subscriber_count("sensor.temperature1") == 1
        assert states.subscriber_count("sensor.temperature2") == 1
        assert states.subscriber_count("sensor.other") == 0
        assert states.subscriber_count() == 0

    async def test_one_evaluation_per_change(self, state_world: StateWorld) -> None:
        """The design's example with two entities: each change is one evaluation."""
        await state_world.set("sensor.temperature1", "70")
        await state_world.set("sensor.temperature2", "70")
        await state_world.started(
            "climate", source('@on_state("sensor.temperature1 > 75 or sensor.temperature2 < 65")')
        )
        await state_world.set("sensor.temperature1", "80")
        await state_world.set("sensor.temperature2", "60")  # still true: no second fire
        await state_world.set("sensor.temperature1", "70")  # still true through temperature2
        await state_world.set("sensor.temperature2", "70")  # false
        await state_world.set("sensor.temperature2", "60")  # true again

        assert state_world.changes() == [
            ("sensor.temperature1", "70", "80"),
            ("sensor.temperature2", "70", "60"),
        ]


class TestEdgeTriggered:
    """Rule: fires when the result changes from false to true, and not again while it stays true."""

    async def test_fires_on_false_to_true(self, state_world: StateWorld) -> None:
        """Crossing the threshold fires once."""
        await state_world.set("sensor.temperature", "20")
        await state_world.started("climate", source(HOT))
        await state_world.set("sensor.temperature", "26")
        assert len(state_world.log) == 1

    async def test_does_not_fire_again_while_true(self, state_world: StateWorld) -> None:
        """Further changes that leave the expression true do not fire."""
        await state_world.set("sensor.temperature", "20")
        await state_world.started("climate", source(HOT))
        for reading in ("26", "27", "30", "26.5"):
            await state_world.set("sensor.temperature", reading)
        assert state_world.changes() == [("sensor.temperature", "20", "26")]

    async def test_must_become_false_first(self, state_world: StateWorld) -> None:
        """After going false, becoming true fires again."""
        await state_world.set("sensor.temperature", "20")
        await state_world.started("climate", source(HOT))
        for reading in ("26", "24", "28", "22", "30"):
            await state_world.set("sensor.temperature", reading)
        assert state_world.changes() == [
            ("sensor.temperature", "20", "26"),
            ("sensor.temperature", "24", "28"),
            ("sensor.temperature", "22", "30"),
        ]

    async def test_true_to_false_does_not_fire(self, state_world: StateWorld) -> None:
        """The falling edge is not a fire."""
        await state_world.set("sensor.temperature", "20")
        await state_world.started("climate", source(HOT))
        await state_world.set("sensor.temperature", "26")
        await state_world.set("sensor.temperature", "20")
        assert len(state_world.log) == 1

    async def test_state_event(self, state_world: StateWorld) -> None:
        """The design's example: old and new state of the change, and the common fields."""
        await state_world.set("sensor.temperature", "24.5")
        await state_world.started("climate", source(HOT))
        await state_world.set("sensor.temperature", "26")

        (event,) = state_world.log
        assert type(event) is StateEvent
        assert event.entity_id == "sensor.temperature"
        assert float(event.new_state.state) - float(event.old_state.state) == 1.5
        assert (event.automation_id, event.source, event.caller, event.data) == (
            "climate",
            "trigger",
            None,
            {},
        )
        assert event.call_time == DEFAULT_NOW

    async def test_direct_call_is_not_a_state_event(self, state_world: StateWorld) -> None:
        """Called by hand, the function gets a ManualEvent."""
        automation = await state_world.started("climate", source(HOT))
        await automation.call_action("react")
        assert type(state_world.log[0]) is ManualEvent


class TestBaseline:
    """Rule: at start the expression is evaluated once without firing."""

    async def test_already_true_at_start_does_not_fire(self, state_world: StateWorld) -> None:
        """An automation started while the expression is true does not fire for that."""
        await state_world.set("sensor.temperature", "30")
        await state_world.started("climate", source(HOT))
        await state_world.clock.settle()
        assert state_world.log == []

    async def test_fires_after_false_then_true(self, state_world: StateWorld) -> None:
        """It fires only after the expression has become false and then true again."""
        await state_world.set("sensor.temperature", "30")
        await state_world.started("climate", source(HOT))
        await state_world.set("sensor.temperature", "31")
        assert state_world.log == []

        await state_world.set("sensor.temperature", "20")
        await state_world.set("sensor.temperature", "28")
        assert state_world.changes() == [("sensor.temperature", "20", "28")]

    async def test_false_at_start_fires_on_the_first_true(self, state_world: StateWorld) -> None:
        """With a false baseline the first change to true fires."""
        await state_world.set("sensor.temperature", "20")
        await state_world.started("climate", source(HOT))
        await state_world.set("sensor.temperature", "30")
        assert len(state_world.log) == 1

    async def test_baseline_is_re_established_on_restart(self, state_world: StateWorld) -> None:
        """Edge case: after stop and start, the current result is the new baseline."""
        await state_world.set("sensor.temperature", "20")
        automation = await state_world.started("climate", source(HOT))
        await automation.stop()
        await state_world.set("sensor.temperature", "30")  # while stopped: seen by nobody

        assert await automation.start()
        state_world.expose(automation)
        await state_world.set("sensor.temperature", "31")
        assert state_world.log == []  # already true at the restart

        await state_world.set("sensor.temperature", "20")
        await state_world.set("sensor.temperature", "30")
        assert len(state_world.log) == 1

    async def test_stop_unsubscribes(self, state_world: StateWorld) -> None:
        """A stopped automation no longer listens."""
        automation = await state_world.started("climate", source(HOT))
        assert state_world.host.states.subscriber_count("sensor.temperature") == 1
        await automation.stop()
        assert state_world.host.states.subscriber_count("sensor.temperature") == 0


class TestEveryChange:
    """Rule: every_change=True fires on every re-evaluation whose result is true."""

    SOURCE = source('@on_state("sensor.temperature > 30", every_change=True)')

    async def test_fires_on_every_true_evaluation(self, state_world: StateWorld) -> None:
        """The design's example: every reading above 30, not only the first."""
        await state_world.set("sensor.temperature", "20")
        await state_world.started("climate", self.SOURCE)
        for reading in ("31", "32", "29", "33", "34"):
            await state_world.set("sensor.temperature", reading)
        assert [new for _, _, new in state_world.changes()] == ["31", "32", "33", "34"]

    async def test_first_evaluation_after_load_fires_if_true(self, state_world: StateWorld) -> None:
        """Already true at start: the first change that leaves it true fires, with no false in between."""
        await state_world.set("sensor.temperature", "35")
        await state_world.started("climate", self.SOURCE)
        await state_world.clock.settle()
        assert state_world.log == []  # the baseline itself does not fire

        await state_world.set("sensor.temperature", "36")
        assert state_world.changes() == [("sensor.temperature", "35", "36")]

    async def test_false_evaluations_do_not_fire(self, state_world: StateWorld) -> None:
        """Readings that leave the expression false fire nothing."""
        await state_world.set("sensor.temperature", "20")
        await state_world.started("climate", self.SOURCE)
        for reading in ("21", "22", "30"):
            await state_world.set("sensor.temperature", reading)
        assert state_world.log == []

    async def test_attribute_change_counts_as_a_change(self, state_world: StateWorld) -> None:
        """A re-evaluation caused by an attribute fires too."""
        await state_world.set("sensor.temperature", "35", unit="C")
        await state_world.started("climate", self.SOURCE)
        await state_world.set("sensor.temperature", "35", unit="F")
        assert len(state_world.log) == 1


class TestHold:
    """Rule: with hold, the trigger fires once the expression has been true for that long."""

    SOURCE = source('@on_state("binary_sensor.front_door == \'on\'", hold="00:05:00")')

    async def test_fires_after_the_duration(self, state_world: StateWorld) -> None:
        """The design's example: the door has been open for five minutes."""
        await state_world.set("binary_sensor.front_door", "off")
        await state_world.started("door", self.SOURCE)
        await state_world.set("binary_sensor.front_door", "on")

        await state_world.clock.advance(minutes=4, seconds=59)
        assert state_world.log == []
        await state_world.clock.advance(seconds=1)
        assert len(state_world.log) == 1

    async def test_discarded_when_false_before_the_duration(self, state_world: StateWorld) -> None:
        """Closing the door in time discards the pending fire."""
        await state_world.set("binary_sensor.front_door", "off")
        await state_world.started("door", self.SOURCE)
        await state_world.set("binary_sensor.front_door", "on")
        await state_world.clock.advance(minutes=4)
        await state_world.set("binary_sensor.front_door", "off")

        await state_world.clock.advance(minutes=10)
        assert state_world.log == []
        assert state_world.clock.pending_timers == 0

    async def test_duration_starts_again_after_a_false(self, state_world: StateWorld) -> None:
        """The expression must be true continuously: an interruption restarts the count."""
        await state_world.set("binary_sensor.front_door", "off")
        await state_world.started("door", self.SOURCE)
        await state_world.set("binary_sensor.front_door", "on")
        await state_world.clock.advance(minutes=4)
        await state_world.set("binary_sensor.front_door", "off")
        await state_world.set("binary_sensor.front_door", "on")

        await state_world.clock.advance(minutes=4)
        assert state_world.log == []
        await state_world.clock.advance(minutes=1)
        assert len(state_world.log) == 1

    async def test_changes_while_true_do_not_restart_the_duration(self, state_world: StateWorld) -> None:
        """A change that leaves the expression true does not reset the hold."""
        await state_world.set("binary_sensor.front_door", "off")
        await state_world.started("door", self.SOURCE)
        await state_world.set("binary_sensor.front_door", "on")
        await state_world.clock.advance(minutes=3)
        await state_world.set("binary_sensor.front_door", "on", battery=80)

        await state_world.clock.advance(minutes=2)
        assert len(state_world.log) == 1

    async def test_fires_once_per_period_of_being_true(self, state_world: StateWorld) -> None:
        """Staying true after the fire does not fire again."""
        await state_world.set("binary_sensor.front_door", "off")
        await state_world.started("door", self.SOURCE)
        await state_world.set("binary_sensor.front_door", "on")
        await state_world.clock.advance(minutes=30)
        assert len(state_world.log) == 1

    async def test_event_describes_the_change_that_made_it_true(self, state_world: StateWorld) -> None:
        """Edge case: the event is of the change that made the expression true; call_time is when the hold elapsed."""
        await state_world.set("binary_sensor.front_door", "off")
        await state_world.started("door", self.SOURCE)
        await state_world.set("binary_sensor.front_door", "on")
        await state_world.clock.advance(minutes=2)
        await state_world.set("binary_sensor.front_door", "on", battery=80)  # a later change while true
        await state_world.clock.advance(minutes=3)

        (event,) = state_world.log
        assert (event.entity_id, event.old_state.state, event.new_state.state) == (
            "binary_sensor.front_door",
            "off",
            "on",
        )
        assert event.new_state.attributes == {}
        assert (event.call_time - DEFAULT_NOW).total_seconds() == 300

    async def test_already_true_at_start_does_not_start_a_hold(self, state_world: StateWorld) -> None:
        """The baseline applies with hold too."""
        await state_world.set("binary_sensor.front_door", "on")
        await state_world.started("door", self.SOURCE)
        await state_world.clock.advance(minutes=10)
        assert state_world.log == []

    async def test_stop_discards_the_pending_hold(self, state_world: StateWorld) -> None:
        """Edge case: pending hold timers are discarded when the automation stops."""
        await state_world.set("binary_sensor.front_door", "off")
        automation = await state_world.started("door", self.SOURCE)
        await state_world.set("binary_sensor.front_door", "on")
        assert state_world.clock.pending_timers == 1

        await automation.stop()
        assert state_world.clock.pending_timers == 0
        await state_world.clock.advance(minutes=10)
        assert state_world.log == []

    async def test_hold_in_seconds(self, state_world: StateWorld) -> None:
        """hold takes the duration formats: here a number of seconds."""
        await state_world.set("binary_sensor.front_door", "off")
        await state_world.started("door", source("@on_state(\"binary_sensor.front_door == 'on'\", hold=30)"))
        await state_world.set("binary_sensor.front_door", "on")
        await state_world.clock.advance(seconds=30)
        assert len(state_world.log) == 1

    async def test_cannot_be_combined_with_every_change(self, state_world: StateWorld) -> None:
        """hold with every_change=True is an error when the automation starts."""
        automation = state_world.add(
            "door", source("@on_state(\"binary_sensor.front_door == 'on'\", hold=30, every_change=True)")
        )
        assert await automation.load()
        assert not await automation.start()
        assert automation.message == "ValueError: @on_state: hold cannot be combined with every_change=True"

    def test_trigger_rejects_the_combination(self, state_world: StateWorld) -> None:
        """The trigger itself refuses the combination too."""
        definition = TriggerDefinition(
            trigger_type=TRIGGER_STATE,
            trigger_expr="sensor.a > 1",
            func_name="react",
            func=lambda: None,
            kwargs={"hold": 5, "every_change": True},
            automation_id="auto",
        )
        with pytest.raises(ValueError, match="hold cannot be combined with every_change=True"):
            StateTrigger(state_world.host, definition, state_world.dispatcher)


class TestEdgeCases:
    """The Edge Cases of the design."""

    async def test_empty_entity_state(self, state_world: StateWorld) -> None:
        """The empty string is a state and is evaluated as such."""
        await state_world.set("sensor.label", "something")
        await state_world.started("labels", source("@on_state(\"sensor.label == ''\")"))
        await state_world.set("sensor.label", "")
        assert state_world.changes() == [("sensor.label", "something", "")]

    async def test_non_existent_entity_does_not_fire(self, state_world: StateWorld) -> None:
        """An entity that does not exist makes the expression false; the automation runs."""
        automation = await state_world.started("climate", source(HOT))
        await state_world.clock.settle()
        assert state_world.log == []
        assert automation.state is AutomationState.ON

    async def test_entity_created_later_fires(self, state_world: StateWorld) -> None:
        """A missing entity that appears with a matching state is a false-to-true change; old_state is None."""
        await state_world.started("climate", source(HOT))
        await state_world.set("sensor.temperature", "30")

        (event,) = state_world.log
        assert event.old_state is None
        assert event.new_state.state == "30"

    @pytest.mark.parametrize("state", ["unavailable", "unknown"])
    async def test_unavailable_or_unknown_does_not_fire(self, state_world: StateWorld, state: str) -> None:
        """The whole expression is false while the value is unusable."""
        await state_world.set("sensor.temperature", "20")
        await state_world.started("climate", source(HOT))
        await state_world.set("sensor.temperature", state)
        assert state_world.log == []

    @pytest.mark.parametrize("state", ["unavailable", "unknown"])
    async def test_unusable_to_usable_fires(self, state_world: StateWorld, state: str) -> None:
        """Unusable counts as false: becoming available with a true expression fires."""
        await state_world.set("sensor.temperature", state)
        await state_world.started("climate", source(HOT))
        await state_world.set("sensor.temperature", "30")

        assert state_world.changes() == [("sensor.temperature", state, "30")]

    async def test_true_then_unavailable_then_true_fires_again(self, state_world: StateWorld) -> None:
        """Going unavailable is going false: the return to a true value is a new edge."""
        await state_world.set("sensor.temperature", "20")
        await state_world.started("climate", source(HOT))
        for reading in ("30", "unavailable", "31"):
            await state_world.set("sensor.temperature", reading)
        assert [new for _, _, new in state_world.changes()] == ["30", "31"]

    async def test_negated_expression_does_not_fire_on_unavailable(self, state_world: StateWorld) -> None:
        """not (...) is false too while the value is unusable."""
        await state_world.set("sensor.temperature", "30")
        await state_world.started("climate", source('@on_state("not (sensor.temperature > 25)")'))
        await state_world.set("sensor.temperature", "unavailable")
        assert state_world.log == []
        await state_world.set("sensor.temperature", "20")
        assert len(state_world.log) == 1

    async def test_handler_sees_unavailable_in_old_state(self, state_world: StateWorld) -> None:
        """old_state.state can be 'unavailable'; handlers must check before converting."""
        await state_world.set("sensor.temperature", "unavailable")
        await state_world.started("climate", source(HOT))
        await state_world.set("sensor.temperature", "30")
        assert state_world.log[0].old_state.state == "unavailable"

    async def test_event_describes_the_change_that_fired(self, state_world: StateWorld) -> None:
        """With several entities, the event is of the change whose evaluation fired."""
        await state_world.set("sensor.indoor", "20")
        await state_world.set("sensor.outdoor", "25")
        await state_world.started("climate", source('@on_state("sensor.indoor > sensor.outdoor")'))

        await state_world.set("sensor.outdoor", "22")  # still false
        await state_world.set("sensor.outdoor", "18")  # true, because the outdoor value dropped
        assert state_world.changes() == [("sensor.outdoor", "22", "18")]

        await state_world.set("sensor.indoor", "10")  # false
        await state_world.set("sensor.indoor", "30")  # true, because the indoor value rose
        assert state_world.changes()[-1] == ("sensor.indoor", "10", "30")

    async def test_quick_changes_are_each_evaluated(self, state_world: StateWorld) -> None:
        """Changes that arrive before the trigger has run are evaluated one by one, in order."""
        await state_world.set("light.living_room", "off")
        await state_world.started(
            "lights",
            "from haanim import ActionMode, action, on_state\n\n"
            + LIGHT
            + "\n@action(execution_mode=ActionMode.QUEUE)\ndef react(event):\n    log.append(event)\n",
        )
        for state in ("on", "off", "on"):
            state_world.host.states.set_state("light.living_room", state)
        await state_world.clock.settle()
        # Both edges are seen, although only the last state would be found by looking now
        assert state_world.changes() == [
            ("light.living_room", "off", "on"),
            ("light.living_room", "off", "on"),
        ]

    async def test_slow_action_follows_its_execution_mode(self, state_world: StateWorld) -> None:
        """A second edge while the action still runs is dropped by the default mode and recorded."""
        await state_world.set("light.living_room", "off")
        automation = state_world.add(
            "lights",
            "from haanim import on_state, sleep\n\n"
            + LIGHT
            + "\nasync def react(event):\n    await sleep(60)\n",
        )
        assert await automation.load() and await automation.start()
        for state in ("on", "off", "on"):
            await state_world.set("light.living_room", state)

        assert automation.last_error is not None
        assert automation.last_error.error_type == "ActionDroppedError"
        await state_world.clock.advance(seconds=60)

    async def test_invalid_expression_is_a_start_error(self, state_world: StateWorld) -> None:
        """An expression that cannot be parsed stops the start."""
        automation = state_world.add("broken", source('@on_state("sensor.temperature >")'))
        assert await automation.load()
        assert not await automation.start()
        assert automation.message is not None and "Invalid state expression" in automation.message

    def test_trigger_rejects_an_invalid_expression(self, state_world: StateWorld) -> None:
        """The trigger itself parses its expression."""
        definition = TriggerDefinition(
            trigger_type=TRIGGER_STATE,
            trigger_expr="temperature > 25",
            func_name="react",
            func=lambda: None,
            automation_id="auto",
        )
        with pytest.raises(AutomationSyntaxError):
            StateTrigger(state_world.host, definition, state_world.dispatcher)

    async def test_constraint_on_a_state_trigger(self, state_world: StateWorld) -> None:
        """A when constraint is evaluated when the trigger fires."""
        await state_world.set("light.living_room", "off")
        await state_world.set("person.john", "work")
        await state_world.started(
            "lights", source("@on_state(\"light.living_room == 'on'\", when=\"person.john == 'home'\")")
        )
        await state_world.set("light.living_room", "on")
        assert state_world.log == []

        await state_world.set("light.living_room", "off")
        await state_world.set("person.john", "home")
        await state_world.set("light.living_room", "on")
        assert len(state_world.log) == 1
