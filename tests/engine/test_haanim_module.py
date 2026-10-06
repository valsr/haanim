"""Tests for the per-automation ``haanim`` module."""

from __future__ import annotations

import gc
import importlib
import pkgutil
import types
import weakref
from pathlib import Path
from typing import Any

import pytest

import haanim.engine
from haanim.engine.callables import as_coroutine_function
from haanim.engine import decorators
from haanim.engine.automation_context import AutomationContext
from haanim.engine.decorators import get_metadata
from haanim.engine.errors import PUBLIC_ERRORS
from haanim.engine.haanim_api import HAAnim
from haanim.engine.haanim_module import DECORATORS, EVENT_CLASSES, DecoratorRegistry, build_haanim_module
from haanim.engine.logging_wrapper import LoggerWrapper
from tests.engine.helpers import automation_file, load_and_run, make_context

# Names the engine used to put into every automation's namespace without an import.
FORMERLY_INJECTED = [
    "action",
    "startup",
    "shutdown",
    "on_state",
    "on_time",
    "on_interval",
    "on_cron",
    "on_event",
    "haa",
    "ActionMode",
    "logging",
    "sleep",
]

# The decorator names of before the design's naming; none of them exists any more.
OLD_DECORATORS = [
    "state",
    "state_trigger",
    "time",
    "time_trigger",
    "interval",
    "cron",
    "event",
    "event_trigger",
]
OLD_DECORATORS += ["time_active", "state_active"]


async def loaded(path: Path, source: str, **kwargs: Any) -> AutomationContext:
    """Write an automation file and load it."""
    path.write_text(source, encoding="utf-8")
    context = make_context(str(path), **kwargs)
    await load_and_run(context)
    return context


class TestPerAutomationInstance:
    """Each automation gets its own module, ``haa`` instance and decorators."""

    SOURCE = (
        "import haanim\nfrom haanim import haa, action, logging\n\n@action\ndef which():\n    return haa.id\n"
    )

    async def test_two_automations_get_distinct_instances(self, tmp_path: Path) -> None:
        """Nothing imported from ``haanim`` is shared between two automations."""
        lights = await loaded(automation_file(tmp_path, "lights"), self.SOURCE)
        heating = await loaded(automation_file(tmp_path, "heating"), self.SOURCE)

        assert isinstance(lights.get_symbol("haa"), HAAnim)
        assert lights.get_symbol("haa") is not heating.get_symbol("haa")
        assert lights.get_symbol("haanim") is not heating.get_symbol("haanim")
        assert lights.get_symbol("action") is not heating.get_symbol("action")
        assert lights.get_symbol("logging") is not heating.get_symbol("logging")

    async def test_haa_id_is_the_importing_automation(self, tmp_path: Path) -> None:
        """``haa.id`` names the automation that imported it."""
        lights = await loaded(automation_file(tmp_path, "lights"), self.SOURCE)
        heating = await loaded(automation_file(tmp_path, "heating"), self.SOURCE)

        assert lights.get_symbol("haa").id == "lights"
        assert heating.get_symbol("haa").id == "heating"
        assert await lights.run_action("which") == "lights"
        assert await heating.run_action("which") == "heating"

    async def test_every_import_gives_the_same_objects(self, tmp_path: Path) -> None:
        """Within one automation, repeated imports give the one instance."""
        context = await loaded(
            automation_file(tmp_path, "auto"),
            "import haanim\nfrom haanim import haa\nfrom haanim import haa as again\n"
            "same = (haa is again, haanim.haa is haa)\n",
        )

        assert context.get_symbol("same") == (True, True)

    async def test_is_not_the_installed_package(self, tmp_path: Path) -> None:
        """The module an automation imports is built for it, not the ``haanim`` distribution."""
        context = await loaded(automation_file(tmp_path, "auto"), "import haanim\n")
        module = context.get_symbol("haanim")

        assert isinstance(module, types.ModuleType)
        assert module is not importlib.import_module("haanim")
        assert module.__name__ == "haanim"

    async def test_logger_is_the_automations(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Records logged through the imported names reach the automation's own logger."""
        source = (
            "from haanim import logging\nlogging.warning('one')\nlogging.warning('two')\nlogging.info('x')\n"
        )

        with caplog.at_level("WARNING"):
            lights = await loaded(automation_file(tmp_path, "lights"), source)
            await loaded(automation_file(tmp_path, "heating"), source)

        assert isinstance(lights.get_symbol("logging"), LoggerWrapper)
        names = [
            record.name.rsplit(".", maxsplit=1)[-1]
            for record in caplog.records
            if record.levelname == "WARNING"
        ]
        assert names == ["lights", "lights", "heating", "heating"]


class TestNothingIsInjected:
    """An automation gets HAAnim names only by importing them."""

    @pytest.mark.parametrize("name", FORMERLY_INJECTED)
    async def test_name_is_not_defined_without_an_import(self, tmp_path: Path, name: str) -> None:
        """Using a HAAnim name without importing it is a NameError."""
        path = automation_file(tmp_path, "auto")
        path.write_text(f"value = {name}\n", encoding="utf-8")
        context = make_context(str(path))

        with pytest.raises(NameError, match=f"name '{name}' is not defined"):
            await load_and_run(context)

    @pytest.mark.parametrize("name", [name for name in FORMERLY_INJECTED if name != "sleep"])
    async def test_name_can_be_imported(self, tmp_path: Path, name: str) -> None:
        """Every such name is available from ``haanim``, except ``sleep``, which is ``haa.sleep()``."""
        context = await loaded(automation_file(tmp_path, "auto"), f"from haanim import {name}\n")

        assert context.get_symbol(name) is not None

    @pytest.mark.parametrize("name", OLD_DECORATORS)
    async def test_old_decorator_names_do_not_exist(self, tmp_path: Path, name: str) -> None:
        """The decorator names of before the design cannot be imported."""
        path = automation_file(tmp_path, "auto")
        path.write_text(f"from haanim import {name}\n", encoding="utf-8")

        with pytest.raises(ImportError, match=f"cannot import name '{name}' from 'haanim'"):
            await load_and_run(make_context(str(path)))

        assert name not in DECORATORS
        assert not hasattr(decorators, name)

    async def test_decorator_without_import_fails_the_load(self, tmp_path: Path) -> None:
        """``@action`` without the import does not load."""
        path = automation_file(tmp_path, "auto")
        path.write_text("@action\ndef go():\n    pass\n", encoding="utf-8")

        with pytest.raises(NameError, match="name 'action' is not defined"):
            await load_and_run(make_context(str(path)))

    async def test_namespace_starts_with_builtins_only(self, tmp_path: Path) -> None:
        """An empty automation defines nothing of HAAnim's."""
        context = await loaded(automation_file(tmp_path, "auto"), "x = 1\n")

        for name in FORMERLY_INJECTED:
            assert context.get_symbol(name) is None


class TestModuleContents:
    """What ``from haanim import ...`` offers."""

    @staticmethod
    def module(registry: DecoratorRegistry | None = None, **kwargs: Any) -> types.ModuleType:
        """Build a module from stand-ins."""
        defaults: dict[str, Any] = {
            "haa": object(),
            "registry": registry or DecoratorRegistry(),
            "logging_wrapper": object(),
            "hass": None,
        }
        defaults.update(kwargs)
        return build_haanim_module(**defaults)

    def test_decorators(self) -> None:
        """Every decorator of the engine is offered under its name."""
        module = self.module()

        for name in DECORATORS:
            assert callable(getattr(module, name))
        assert set(DECORATORS) <= set(module.__all__)

    def test_errors_and_events(self) -> None:
        """The public error classes and the event classes are the engine's own."""
        module = self.module()

        for error_class in PUBLIC_ERRORS:
            assert getattr(module, error_class.__name__) is error_class
        for event_class in EVENT_CLASSES:
            assert getattr(module, event_class.__name__) is event_class

    def test_supplied_objects(self) -> None:
        """``haa``, ``hass`` and ``logging`` are the objects given."""
        haa, hass, wrapper = object(), object(), object()

        module = self.module(haa=haa, hass=hass, logging_wrapper=wrapper)

        assert (module.haa, module.hass, module.logging) == (haa, hass, wrapper)
        for removed in ("log", "log_info", "log_debug", "log_warning", "log_error", "set_status"):
            assert not hasattr(module, removed)

    def test_helpers(self) -> None:
        """Extra names are added and listed."""
        helper = object()

        module = self.module(helpers={"extra": helper})

        assert module.extra is helper
        assert "extra" in module.__all__

    def test_all_lists_every_name(self) -> None:
        """``__all__`` is exactly the public names, sorted."""
        module = self.module()

        assert module.__all__ == sorted(module.__all__)
        assert set(module.__all__) == {name for name in vars(module) if not name.startswith("__")}

    async def test_unknown_name(self, tmp_path: Path) -> None:
        """Importing a name the module does not have fails as in Python."""
        path = automation_file(tmp_path, "auto")
        path.write_text("from haanim import no_such_name\n", encoding="utf-8")

        with pytest.raises(ImportError, match="cannot import name 'no_such_name' from 'haanim'"):
            await load_and_run(make_context(str(path)))


class TestDecoratorRegistry:
    """Decorators register what they decorate to their own automation."""

    def test_direct_form(self) -> None:
        """``@action`` registers the function and returns it."""
        registry = DecoratorRegistry()
        action = registry.bind(decorators.action)

        def go() -> None:
            pass

        assert action(go) is go
        assert registry.functions == [go]
        metadata = get_metadata(go)
        assert metadata is not None and metadata.is_action

    def test_factory_form(self) -> None:
        """``@action(name="Name")`` registers the function when the returned decorator is applied."""
        registry = DecoratorRegistry()
        action = registry.bind(decorators.action)

        def go() -> None:
            pass

        decorator = action(name="Go now", timeout=5)
        assert registry.functions == []
        assert decorator(go) is go
        assert registry.functions == [go]
        metadata = get_metadata(go)
        assert metadata is not None and metadata.action_info is not None
        assert metadata.action_info.name == "Go now"

    @pytest.mark.parametrize("name", ["on_state", "on_time", "on_interval", "on_cron", "on_event"])
    def test_trigger_decorators(self, name: str) -> None:
        """Decorators that always take arguments register too."""
        registry = DecoratorRegistry()
        decorator = registry.bind(DECORATORS[name])

        def go() -> None:
            pass

        argument = {"on_interval": "00:01:00", "on_cron": "* * * * *", "on_event": "my_event"}.get(
            name, "12:00"
        )
        decorator(argument)(go)

        assert registry.functions == [go]

    @pytest.mark.parametrize("name", ["startup", "shutdown"])
    def test_lifecycle_decorators(self, name: str) -> None:
        """``@startup`` and ``@shutdown`` register."""
        registry = DecoratorRegistry()

        def go() -> None:
            pass

        registry.bind(DECORATORS[name])(go)

        assert registry.functions == [go]

    def test_stacked_decorators_register_once(self) -> None:
        """A function under several decorators is one registration, in first-decorated order."""
        registry = DecoratorRegistry()
        action, state = registry.bind(decorators.action), registry.bind(decorators.on_state)

        def first() -> None:
            pass

        def second() -> None:
            pass

        action(state("sensor.a == 'on'")(first))
        action(second)
        state("sensor.b == 'on'")(first)

        assert registry.functions == [first, second]

    def test_registries_are_separate(self) -> None:
        """A decorator bound to one registry does not touch another."""
        one, two = DecoratorRegistry(), DecoratorRegistry()

        def go() -> None:
            pass

        one.bind(decorators.action)(go)

        assert one.functions == [go]
        assert two.functions == []

    def test_functions_is_a_copy(self) -> None:
        """The list handed out cannot change the registry."""
        registry = DecoratorRegistry()
        registry.bind(decorators.action)(lambda: None)

        registry.functions.clear()

        assert len(registry.functions) == 1

    def test_clear(self) -> None:
        """A cleared registry is empty."""
        registry = DecoratorRegistry()
        registry.bind(decorators.action)(lambda: None)

        registry.clear()

        assert registry.functions == []

    def test_bound_decorator_keeps_name_and_doc(self) -> None:
        """A bound decorator still describes itself."""
        bound = DecoratorRegistry().bind(decorators.action)

        assert bound.__name__ == "action"
        assert bound.__doc__ == decorators.action.__doc__

    def test_decorator_returning_a_value(self) -> None:
        """A callable that is not used as a decorator passes its result through."""
        registry = DecoratorRegistry()

        assert registry.bind(lambda *args: 42)("a", "b") == 42
        assert registry.functions == []

    async def test_decorators_register_to_the_importing_automation_only(self, tmp_path: Path) -> None:
        """Two automations with the same code have separate actions."""
        source = "from haanim import action\n\n@action\ndef go():\n    return __name__\n"
        lights = await loaded(automation_file(tmp_path, "lights"), source)
        heating = await loaded(
            automation_file(tmp_path, "heating"), source + "\n@action\ndef extra():\n    pass\n"
        )

        assert [action.name for action in lights.get_actions()] == ["go"]
        assert sorted(action.name for action in heating.get_actions()) == ["extra", "go"]
        lights_go, heating_go = lights.get_action("go"), heating.get_action("go")
        assert lights_go is not None and heating_go is not None
        assert lights_go.func is not heating_go.func
        assert await lights.run_action("go") == "lights"
        assert await heating.run_action("go") == "heating"

    async def test_undecorated_functions_are_not_actions(self, tmp_path: Path) -> None:
        """Only decorated functions become actions; the rest can still be run by name."""
        context = await loaded(
            automation_file(tmp_path, "auto"),
            "from haanim import action\n\ndef helper():\n    return 1\n\n@action\ndef go():\n    return helper()\n",
        )

        assert [action.name for action in context.get_actions()] == ["go"]
        assert await as_coroutine_function(context.get_symbol("helper"))() == 1


class TestSubModules:
    """Files an automation imports share its ``haanim`` module."""

    async def test_sub_module_shares_the_instance(self, tmp_path: Path) -> None:
        """``haa`` in an imported file is the automation's, not a second one."""
        (automation_file(tmp_path, "lights").parent / "helper.py").write_text(
            "import haanim\nfrom haanim import haa\ndef automation_id():\n    return haa.id\n",
            encoding="utf-8",
        )
        context = await loaded(
            automation_file(tmp_path, "lights"),
            "import haanim\nfrom haanim import haa\nfrom . import helper\n"
            "same = (helper.haa is haa, helper.haanim is haanim)\nwho = helper.automation_id()\n",
        )

        assert context.get_symbol("same") == (True, True)
        assert context.get_symbol("who") == "lights"

    async def test_action_in_a_sub_module_is_registered(self, tmp_path: Path) -> None:
        """An action defined in an imported file belongs to the importing automation."""
        (automation_file(tmp_path, "lights").parent / "scenes.py").write_text(
            "from haanim import action, haa\n\n@action\ndef evening():\n    return 'evening of ' + haa.id\n",
            encoding="utf-8",
        )
        context = await loaded(
            automation_file(tmp_path, "lights"),
            "from haanim import action\nfrom . import scenes\n\n@action\ndef morning():\n    return 'morning'\n",
        )

        assert sorted(action.name for action in context.get_actions()) == ["evening", "morning"]
        assert await context.run_action("evening") == "evening of lights"

    async def test_sub_module_does_not_register_elsewhere(self, tmp_path: Path) -> None:
        """Two automations with the same file each get their own copy of its actions."""
        source = "from haanim import action, haa\n\n@action\ndef who():\n    return haa.id\n"
        for name in ("lights", "heating"):
            (automation_file(tmp_path, name).parent / "shared.py").write_text(source, encoding="utf-8")
        lights = await loaded(automation_file(tmp_path, "lights"), "from . import shared\n")
        heating = await loaded(automation_file(tmp_path, "heating"), "from . import shared\n")

        assert await lights.run_action("who") == "lights"
        assert await heating.run_action("who") == "heating"
        assert lights.get_symbol("shared") is not heating.get_symbol("shared")


class TestUnload:
    """The instance is discarded when the automation is unloaded."""

    SOURCE = (
        "import haanim\nfrom haanim import haa, action\n\nclass Thing:\n    pass\n\nthing = Thing()\n\n"
        "@action\ndef go():\n    return haa.id\n"
    )

    async def test_instance_is_discarded(self, tmp_path: Path) -> None:
        """After unload nothing in the engine refers to the automation's objects."""
        context = await loaded(automation_file(tmp_path, "auto"), self.SOURCE)
        references = [
            weakref.ref(context.get_symbol("haa")),
            weakref.ref(context.get_symbol("haanim")),
            weakref.ref(context.get_symbol("thing")),
            weakref.ref(context.get_symbol("go")),
        ]
        assert all(reference() is not None for reference in references)

        context.unload()
        gc.collect()

        assert [reference() for reference in references] == [None, None, None, None]

    async def test_unloaded_context_is_empty(self, tmp_path: Path) -> None:
        """An unloaded automation has no actions, functions or metadata."""
        context = await loaded(automation_file(tmp_path, "auto"), self.SOURCE)

        context.unload()

        assert context.get_actions() == []
        assert context.get_triggers() == []
        assert context.get_metadata() is None
        assert context.get_action("go") is None
        assert context.get_symbol("haa") is None
        assert not context.is_loaded
        assert not context.has_startup and not context.has_shutdown

    async def test_reload_builds_a_new_instance(self, tmp_path: Path) -> None:
        """Loading again after unload gives a fresh instance and registers the actions once."""
        context = await loaded(automation_file(tmp_path, "auto"), self.SOURCE)
        first = weakref.ref(context.get_symbol("haa"))

        context.unload()
        await load_and_run(context)
        gc.collect()

        assert first() is None
        assert isinstance(context.get_symbol("haa"), HAAnim)
        assert [action.name for action in context.get_actions()] == ["go"]
        assert await context.run_action("go") == "auto"

    async def test_unload_before_load(self, tmp_path: Path) -> None:
        """Unloading an automation that was never loaded does nothing."""
        path = automation_file(tmp_path, "auto")
        path.write_text("x = 1\n", encoding="utf-8")
        context = make_context(str(path))

        context.unload()

        assert not context.is_loaded


class TestNoGlobalState:
    """The engine holds no module-level ``haa`` instance or decorator registry."""

    @pytest.mark.parametrize(
        "module_name",
        sorted(module.name for module in pkgutil.walk_packages(haanim.engine.__path__, "haanim.engine.")),
    )
    def test_module_has_no_shared_instance(self, module_name: str) -> None:
        """No engine module keeps an instance that automations would share."""
        module = importlib.import_module(module_name)

        shared = [
            name for name, value in vars(module).items() if isinstance(value, (HAAnim, DecoratorRegistry))
        ]

        assert shared == []
        assert "haa" not in vars(module)

    def test_installed_package_has_no_haa(self) -> None:
        """The importable ``haanim`` package itself offers no ``haa``."""
        assert not hasattr(importlib.import_module("haanim"), "haa")
