"""Tests that the import, builtin and member restrictions match the design's Imports section."""

from __future__ import annotations

import asyncio
import builtins
import logging
import time
from pathlib import Path
from typing import Any

import pytest

from haanim.const import (
    DEFAULT_IMPORT_ALLOWLIST,
    DISABLED_LOOP_MEMBERS,
    DISABLED_MODULE_MEMBERS,
    RESTRICTED_BUILTINS,
)
from haanim.engine.ast_evaluator import AstEvaluator
from haanim.engine.automation_module import AutomationModule
from haanim.engine.errors import AutomationRuntimeError, AutomationSecurityError, AutomationSyntaxError
from haanim.engine.guards import Guarded, guard_loop, guard_module
from haanim.engine.import_controller import ImportController
from haanim.engine.logging_wrapper import LoggerWrapper
from haanim.engine.safe_builtins import SafeBuiltins
from haanim.engine.symbol_table import SymbolTable
from haanim.engine.validation import check_source, find_disallowed, validate_files, validate_source
from haanim.testing import FakeFileSystem, make_host
from tests.engine.helpers import make_context

# The lists of the design's Imports section, written out here on purpose:
# the code must be changed together with the design, not on its own.
DESIGN_ALLOWED_MODULES = [
    "asyncio",
    "datetime",
    "json",
    "logging",
    "math",
    "random",
    "re",
    "time",
    "typing",
    "collections",
    "functools",
    "itertools",
    "operator",
    "statistics",
    "decimal",
    "fractions",
    "enum",
    "dataclasses",
    "hass",
    "haanim",
]
DESIGN_DISABLED_BUILTINS = [
    "eval",
    "exec",
    "compile",
    "__import__",
    "open",
    "input",
    "breakpoint",
    "globals",
    "locals",
]
DESIGN_NEWLY_ALLOWED_BUILTINS = ["getattr", "setattr", "delattr", "dir", "vars", "type", "memoryview"]
DESIGN_DISABLED_MEMBERS = [
    "time.sleep",
    "asyncio.run",
    "asyncio.new_event_loop",
    "asyncio.set_event_loop",
    "asyncio.to_thread",
    "asyncio.create_subprocess_exec",
    "asyncio.create_subprocess_shell",
]
DESIGN_DISABLED_LOOP_MEMBERS = ["run_forever", "run_until_complete", "run_in_executor"]

# Standard modules of the allowlist; "hass" and "haanim" are supplied by the engine.
STANDARD_MODULES = [name for name in DESIGN_ALLOWED_MODULES if name not in ("hass", "haanim", "logging")]


def controller() -> ImportController:
    """Build an import controller with the engine-supplied modules registered, as a context does."""
    imports = ImportController()
    imports.register_virtual_module("haanim", object())
    imports.register_virtual_module("logging", object())
    imports.register_virtual_module("hass", object())
    return imports


async def load(source: str, **kwargs: Any) -> dict[str, Any]:
    """Run a source in the interpreter and return its module-level names."""
    evaluator = AstEvaluator(name="test", **kwargs)
    evaluator.parse(source, filename="main.py")
    return await evaluator.execute()


async def run_main(source: str, **kwargs: Any) -> Any:
    """Run a source and return what its ``main()`` returns."""
    return await (await load(source, **kwargs))["main"]()


class TestListsMatchTheDesign:
    """The lists in code are identical to the design's."""

    def test_import_allowlist(self) -> None:
        """The default allowlist is the design's, in the design's order."""
        assert DEFAULT_IMPORT_ALLOWLIST == DESIGN_ALLOWED_MODULES

    def test_disabled_builtins(self) -> None:
        """Exactly the nine builtins of the design are disabled."""
        assert RESTRICTED_BUILTINS == set(DESIGN_DISABLED_BUILTINS)
        assert len(DESIGN_DISABLED_BUILTINS) == 9

    def test_disabled_members(self) -> None:
        """Exactly the module members of the design are disabled."""
        in_code = {
            f"{module}.{member}" for module, members in DISABLED_MODULE_MEMBERS.items() for member in members
        }

        assert in_code == set(DESIGN_DISABLED_MEMBERS)
        assert set(DISABLED_LOOP_MEMBERS) == set(DESIGN_DISABLED_LOOP_MEMBERS)

    def test_every_disabled_name_exists(self) -> None:
        """Each disabled name is a real builtin or member, so the guard is not vacuous."""
        for name in DESIGN_DISABLED_BUILTINS:
            assert hasattr(builtins, name)
        assert hasattr(time, "sleep")
        for member in DISABLED_MODULE_MEMBERS["asyncio"]:
            assert hasattr(asyncio, member)
        for member in DISABLED_LOOP_MEMBERS:
            assert hasattr(asyncio.AbstractEventLoop, member)


class TestAllowedImports:
    """Every module on the allowlist imports; everything else is rejected at load."""

    @pytest.mark.parametrize("module", STANDARD_MODULES)
    async def test_standard_module_imports(self, module: str) -> None:
        """An allowed standard module can be imported in both forms."""
        symbols = await load(f"import {module}\nimport {module} as alias\nname = {module}.__name__\n")

        assert symbols["name"] == module
        assert symbols["alias"].__name__ == module

    @pytest.mark.parametrize("module", DESIGN_ALLOWED_MODULES)
    def test_allowed_module_passes_the_static_check(self, module: str) -> None:
        """No allowed module is reported at load."""
        validate_source(f"import {module}\nfrom {module} import something\n", imports=controller())

    @pytest.mark.parametrize(
        "module", ["os", "sys", "subprocess", "socket", "threading", "pathlib", "homeassistant"]
    )
    def test_other_module_is_rejected_at_load(self, module: str) -> None:
        """A module that is not on the allowlist is a load error with file and line."""
        with pytest.raises(AutomationSecurityError) as raised:
            validate_source(f"x = 1\nimport {module}\n", filename="main.py", imports=controller())

        assert str(raised.value) == f"main.py:2: import of module '{module}' is not allowed"
        assert raised.value.lineno == 2
        assert raised.value.filename == "main.py"

    @pytest.mark.parametrize(
        "source",
        [
            "import os.path\n",
            "import json, os\n",
            "from os import path\n",
            "from os.path import join as j\n",
            "def f():\n    import os\n",
            "class A:\n    def m(self):\n        from subprocess import run\n",
            "try:\n    import os\nexcept ImportError:\n    pass\n",
        ],
        ids=["submodule", "second of two", "from", "from submodule", "in function", "in method", "in try"],
    )
    def test_every_form_of_import_is_checked(self, source: str) -> None:
        """A disallowed import is found wherever and however it is written."""
        with pytest.raises(AutomationSecurityError, match="is not allowed"):
            validate_source(source, imports=controller())

    def test_submodule_of_an_allowed_module(self) -> None:
        """Allowing a package allows its submodules."""
        imports = controller()

        assert imports.is_allowed("collections.abc")
        assert imports.is_allowed("asyncio.tasks")
        assert not imports.is_allowed("collections_extra")
        assert not imports.is_allowed("os.path")

    async def test_import_of_a_submodule_binds_the_package(self) -> None:
        """``import a.b`` binds ``a``; ``import a.b as c`` binds the submodule."""
        symbols = await load("import collections.abc\nimport collections.abc as abc_module\n")

        assert symbols["collections"].OrderedDict is __import__("collections").OrderedDict
        assert symbols["abc_module"].__name__ == "collections.abc"

    def test_wildcard_import_is_rejected(self) -> None:
        """A wildcard import is a load error."""
        with pytest.raises(AutomationSecurityError, match=r"main.py:1: wildcard imports are not allowed"):
            validate_source("from math import *\n", filename="main.py", imports=controller())

    async def test_blocked_import_does_not_run_anything(self) -> None:
        """Nothing in the file runs when any import in it is disallowed."""
        evaluator = AstEvaluator(name="test")

        with pytest.raises(AutomationSecurityError):
            evaluator.parse("ran = True\n\ndef later():\n    import os\n")

        assert not evaluator.get_global_symbols().exists("ran")

    async def test_missing_name_is_an_import_error(self) -> None:
        """Importing a name the module does not have fails as in Python."""
        with pytest.raises(AutomationRuntimeError) as raised:
            await load("from math import no_such_name\n")

        assert isinstance(raised.value.__cause__, ImportError)
        assert "cannot import name 'no_such_name' from 'math'" in str(raised.value)

    def test_blocked_import_at_run_time(self) -> None:
        """An import the static check did not see is still refused when it runs."""
        with pytest.raises(AutomationSecurityError, match="Import of module 'os' is not allowed"):
            ImportController().safe_import("os")

    def test_allowed_module_that_does_not_exist(self) -> None:
        """An allowed module that cannot be imported raises ImportError, not a security error."""
        with pytest.raises(ModuleNotFoundError):
            ImportController(additional=["no_such_module_xyz"]).safe_import("no_such_module_xyz")

    def test_all_problems_are_reported_together(self) -> None:
        """One error lists every disallowed import and builtin."""
        source = "import os\nimport json\nimport sys\nopen('f')\n"

        with pytest.raises(AutomationSecurityError) as raised:
            validate_source(
                source, filename="main.py", imports=controller(), restricted_builtins=RESTRICTED_BUILTINS
            )

        assert [problem.lineno for problem in raised.value.problems] == [1, 3, 4]
        assert all(problem.security for problem in raised.value.problems)
        assert len(str(raised.value).splitlines()) == 3

    def test_syntax_problems_take_precedence(self) -> None:
        """A file that is not valid supported Python is reported as that, without the security problems."""
        with pytest.raises(AutomationSyntaxError) as raised:
            validate_source("import os\ndef gen():\n    yield 1\n", filename="main.py", imports=controller())

        assert [problem.lineno for problem in raised.value.problems] == [2 + 1]

        _, problems = check_source("import os\ndef gen():\n    yield 1\n", "main.py", controller())
        assert [(problem.lineno, problem.security) for problem in problems] == [(1, True), (3, False)]

    def test_imports_are_not_checked_without_rules(self) -> None:
        """The validator alone does not judge imports."""
        assert find_disallowed(validate_source("import os\n"), "main.py") == []

    async def test_validate_files_checks_imports(self) -> None:
        """The check covers every file of an automation."""
        files = FakeFileSystem()
        files.write(Path("/a/main.py"), "import json\n")
        files.write(Path("/a/helper.py"), "\nimport os\n")

        with pytest.raises(AutomationSecurityError, match=r"^helper.py:2: import of module 'os'"):
            await validate_files(files, [Path("/a/main.py"), Path("/a/helper.py")], imports=controller())


class TestImportOptions:
    """The two options of the integration are honoured."""

    def test_additional_imports_extend_the_default(self) -> None:
        """Additional modules are allowed on top of the default allowlist."""
        imports = ImportController(additional=["colorsys", "homeassistant"])

        assert imports.is_allowed("colorsys")
        assert imports.is_allowed("homeassistant.const")
        assert imports.is_allowed("json")
        assert not imports.is_allowed("os")

    def test_allow_all(self) -> None:
        """With allow-all every module is allowed."""
        imports = ImportController(allow_all=True)

        assert imports.is_allowed("os")
        assert imports.safe_import("colorsys").__name__ == "colorsys"

    async def test_additional_import_in_an_automation(self, tmp_path: Path) -> None:
        """An automation can import a module added through the option, and no other."""
        path = tmp_path / "auto.py"
        path.write_text("import colorsys\nvalue = colorsys.rgb_to_hls(1, 0, 0)[0]\n", encoding="utf-8")

        with pytest.raises(AutomationSecurityError, match=r"^auto.py:1: import of module 'colorsys'"):
            await make_context(str(path)).load()

        context = make_context(str(path), additional_imports=["colorsys"])
        await context.load()
        assert context.get_symbol("value") == 0.0

    async def test_allow_all_in_an_automation(self, tmp_path: Path) -> None:
        """With allow-all an automation can import anything."""
        path = tmp_path / "auto.py"
        path.write_text("import os.path\nname = os.path.basename('/a/b')\n", encoding="utf-8")
        context = make_context(str(path), allow_all_imports=True)

        await context.load()

        assert context.get_symbol("name") == "b"

    async def test_allow_all_keeps_the_member_guards(self) -> None:
        """Allow-all lifts the import allowlist only; blocking members stay disabled."""
        with pytest.raises(AutomationSecurityError, match="'time.sleep' is not available"):
            await load("import time\ntime.sleep(0)\n", import_controller=ImportController(allow_all=True))


class TestDisabledBuiltins:
    """The nine disabled builtins are rejected; everything else works."""

    @pytest.mark.parametrize("name", DESIGN_DISABLED_BUILTINS)
    def test_rejected_at_load(self, name: str) -> None:
        """Using a disabled builtin is a load error with file and line."""
        evaluator = AstEvaluator(name="test")

        with pytest.raises(AutomationSecurityError) as raised:
            evaluator.parse(f"x = 1\n\ndef f():\n    return {name}\n", filename="main.py")

        assert str(raised.value) == f"main.py:4: builtin '{name}' is not available in automations"

    @pytest.mark.parametrize("name", DESIGN_DISABLED_BUILTINS)
    def test_not_in_the_namespace(self, name: str) -> None:
        """A disabled builtin is not among the names an automation starts with."""
        assert name not in SafeBuiltins().get_builtins()
        assert name in SafeBuiltins().restricted

    @pytest.mark.parametrize("name", DESIGN_DISABLED_BUILTINS)
    async def test_rejected_when_reached_at_run_time(self, name: str) -> None:
        """A disabled builtin that the static check cannot see still raises when used."""
        evaluator = AstEvaluator(name="test")
        evaluator.parse("def f(name):\n    return name\n")
        await evaluator.execute()
        node = __import__("ast").parse(name, mode="eval").body

        with pytest.raises(AutomationSecurityError, match=f"Builtin '{name}' is not available"):
            await evaluator.aeval(node, evaluator.get_global_symbols())

    @pytest.mark.parametrize(
        "source",
        [
            "def open(path):\n    return path\nr = open('x')\n",
            "open = len\nr = open('abc')\n",
            "def f(input):\n    return input\nr = f(1)\n",
            "class A:\n    def compile(self):\n        return 1\nr = A().compile()\n",
            "for exec in [1]:\n    r = exec\n",
            "d = {'eval': 1}\nr = d['eval'] + len('open')\n",
        ],
        ids=["def", "assignment", "parameter", "method", "loop variable", "string"],
    )
    async def test_own_name_is_not_the_builtin(self, source: str) -> None:
        """A name the automation defines itself is not a use of the disabled builtin."""
        assert "r" in await load(source)

    @pytest.mark.parametrize("name", DESIGN_NEWLY_ALLOWED_BUILTINS)
    def test_allowed_builtin_is_available(self, name: str) -> None:
        """The builtins the design names as available are the real ones."""
        assert SafeBuiltins().get_builtins()[name] is getattr(builtins, name)

    async def test_allowed_builtins_work(self) -> None:
        """Each newly allowed builtin does what it does in Python."""
        symbols = await load(
            "class A:\n    x = 1\n"
            "a = A()\n"
            "setattr(a, 'y', 2)\n"
            "got = (getattr(a, 'x'), getattr(a, 'y'), getattr(a, 'missing', 'default'))\n"
            "delattr(a, 'y')\n"
            "has_y = hasattr(a, 'y')\n"
            "a.z = 3\n"
            "instance_vars = vars(a)\n"
            "listed = 'x' in dir(a)\n"
            "kind = type(a).__name__\n"
            "view = bytes(memoryview(b'abc')[1:])\n"
        )

        assert symbols["got"] == (1, 2, "default")
        assert symbols["has_y"] is False
        assert symbols["instance_vars"] == {"z": 3}
        assert symbols["listed"] is True
        assert symbols["kind"] == "A"
        assert symbols["view"] == b"bc"

    async def test_dir_and_vars_without_arguments_describe_the_calling_scope(self) -> None:
        """In a function they give the function's own names, as in Python."""
        symbols = await load(
            "def f(a):\n    b = 2\n    return (dir(), vars())\nlisted, mapping = f(1)\nat_module_level = 'f' in dir()\n"
        )

        assert symbols["listed"] == ["a", "b"]
        assert symbols["mapping"] == {"a": 1, "b": 2}
        assert symbols["at_module_level"] is True

    def test_every_other_public_builtin_is_available(self) -> None:
        """Nothing beyond the nine is withheld."""
        available = set(SafeBuiltins().get_builtins())
        public = {name for name in dir(builtins) if not name.startswith("_")}

        assert public - available == set(DESIGN_DISABLED_BUILTINS) - {"__import__"}


class TestDisabledMembers:
    """Blocking members of allowed modules raise when used."""

    @pytest.mark.parametrize("member", DESIGN_DISABLED_MEMBERS)
    async def test_raises_when_called(self, member: str) -> None:
        """Calling a disabled member raises AutomationSecurityError naming it."""
        module = member.split(".")[0]

        with pytest.raises(AutomationSecurityError, match=f"'{member}' is not available in automations: "):
            await run_main(f"import {module}\nasync def main():\n    {member}()\n")

    @pytest.mark.parametrize("member", DESIGN_DISABLED_MEMBERS)
    async def test_raises_when_imported_by_name(self, member: str) -> None:
        """``from module import member`` loads, and the member raises when called."""
        module, name = member.split(".")

        with pytest.raises(AutomationSecurityError, match=f"'{member}' is not available"):
            await run_main(f"from {module} import {name}\nasync def main():\n    {name}(1)\n")

    @pytest.mark.parametrize("member", DESIGN_DISABLED_MEMBERS)
    async def test_is_not_rejected_at_load(self, member: str) -> None:
        """Mentioning a disabled member does not stop the automation from loading."""
        module = member.split(".")[0]

        symbols = await load(f"import {module}\ndef never_called():\n    {member}()\n")

        assert "never_called" in symbols

    async def test_time_sleep_names_the_replacement(self) -> None:
        """The error tells the author what to use instead."""
        with pytest.raises(AutomationSecurityError, match=r"use 'await haa.sleep\(\)'"):
            await run_main("import time\nasync def main():\n    time.sleep(1)\n")

    @pytest.mark.parametrize("getter", ["get_running_loop", "get_event_loop"])
    @pytest.mark.parametrize("member", DESIGN_DISABLED_LOOP_MEMBERS)
    async def test_loop_member_raises(self, getter: str, member: str) -> None:
        """The loop an automation gets from asyncio cannot be run or used with threads."""
        with pytest.raises(AutomationSecurityError, match=f"'loop.{member}' is not available"):
            await run_main(f"import asyncio\nasync def main():\n    asyncio.{getter}().{member}(None)\n")

    async def test_rest_of_the_loop_works(self) -> None:
        """Everything else on the loop is the real loop's."""
        result = await run_main(
            "import asyncio\n"
            "async def main():\n"
            "    loop = asyncio.get_running_loop()\n"
            "    future = loop.create_future()\n"
            "    loop.call_soon(future.set_result, 'done')\n"
            "    return (await future, loop.is_running(), loop.time() >= 0)\n"
        )

        assert result == ("done", True, True)

    async def test_rest_of_the_modules_work(self) -> None:
        """The other members of time and asyncio are the real ones."""
        result = await run_main(
            "import asyncio\nimport time\nfrom asyncio import gather, CancelledError\n"
            "async def one():\n    return 1\n"
            "async def main():\n"
            "    values = await gather(one(), asyncio.wait_for(one(), 1))\n"
            "    return (values, time.monotonic() > 0, isinstance(time.time(), float), issubclass(CancelledError, BaseException),\n"
            "            isinstance(asyncio.Event(), asyncio.Event), asyncio.__name__)\n"
        )

        assert result == ([1, 1], True, True, True, True, "asyncio")

    def test_unguarded_module_is_returned_as_is(self) -> None:
        """A module without disabled members is the real module."""
        import json  # pylint: disable=import-outside-toplevel

        assert guard_module("json", json) is json
        assert ImportController().safe_import("json") is json

    def test_guarded_object(self) -> None:
        """A stand-in forwards everything but its disabled members."""

        class Target:
            value = 1

            def blocked(self) -> str:
                return "ran"

            def made(self) -> int:
                return 2

        target = Target()
        guarded = Guarded(target, "thing", {"blocked": "do not"}, {"made": lambda result: result * 10})

        assert guarded.value == 1
        assert guarded.made() == 20
        assert guarded.blocked.__name__ == "blocked"
        with pytest.raises(
            AutomationSecurityError, match="'thing.blocked' is not available in automations: do not"
        ):
            guarded.blocked()
        guarded.value = 5
        assert target.value == 5
        guarded.extra = 1
        del guarded.extra
        assert not hasattr(target, "extra")
        assert "made" in dir(guarded)
        assert repr(guarded).startswith("<guarded ")
        with pytest.raises(AttributeError):
            _ = guarded.missing

    async def test_guard_loop(self) -> None:
        """The loop stand-in keeps the loop usable."""
        loop = guard_loop(asyncio.get_running_loop())

        assert loop.is_running()
        with pytest.raises(AutomationSecurityError, match="'loop.run_in_executor'"):
            loop.run_in_executor(None, print)


class TestEngineSuppliedModules:
    """``haanim``, ``logging`` and ``hass`` come from the engine, not from Python."""

    async def test_logging_is_the_automation_logger(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Both spellings give the wrapper, and records reach the automation's logger."""
        path = tmp_path / "lights.py"
        path.write_text(
            "import logging\nfrom haanim import logging as from_haanim\n"
            "same = logging is from_haanim\n"
            "logging.info('hello from %s', 'lights')\n",
            encoding="utf-8",
        )
        context = make_context(str(path))

        with caplog.at_level(logging.INFO):
            await context.load()

        assert context.get_symbol("same") is True
        assert isinstance(context.get_symbol("logging"), LoggerWrapper)
        record = next(record for record in caplog.records if record.getMessage() == "hello from lights")
        assert record.name.endswith(".lights")

    async def test_hass_is_the_hosts_instance(self, tmp_path: Path) -> None:
        """``import hass`` gives the object the host supplies."""
        instance = object()
        path = tmp_path / "auto.py"
        path.write_text(
            "import hass\nfrom haanim import hass as from_haanim\nsame = hass is from_haanim\n",
            encoding="utf-8",
        )
        context = make_context(str(path), host=make_host(files=_disk(), hass=instance))

        await context.load()

        assert context.get_symbol("hass") is instance
        assert context.get_symbol("same") is True

    async def test_hass_without_an_instance(self, tmp_path: Path) -> None:
        """A host with no instance to offer makes the import fail at load, as a missing module."""
        path = tmp_path / "auto.py"
        path.write_text("import hass\n", encoding="utf-8")
        context = make_context(str(path))

        with pytest.raises(AutomationRuntimeError, match="No module named 'hass'"):
            await context.load()

    async def test_haanim_module_is_supplied(self, tmp_path: Path) -> None:
        """``from haanim import ...`` gives the automation's own objects."""
        path = tmp_path / "auto.py"
        path.write_text(
            "from haanim import haa, action\nimport haanim\nsame = haanim.haa is haa\n", encoding="utf-8"
        )
        context = make_context(str(path))

        await context.load()

        assert context.get_symbol("same") is True

    def test_virtual_module_takes_precedence(self) -> None:
        """A registered module is what is imported, even if a real module has the name."""
        imports = ImportController()
        supplied = object()
        imports.register_virtual_module("json", supplied)
        imports.register_virtual_module("not_on_the_list", supplied)

        assert imports.safe_import("json") is supplied
        assert imports.is_allowed("not_on_the_list")


class TestRelativeImports:
    """An automation can import its own files."""

    @staticmethod
    def evaluator(files: FakeFileSystem, path: str = "/auto/main.py") -> AstEvaluator:
        """Build an evaluator for a file of a fake file system."""
        return AstEvaluator(name="auto", files=files, path=Path(path))

    async def run(self, files: FakeFileSystem, path: str = "/auto/main.py") -> dict[str, Any]:
        """Run a file of a fake file system and return its module-level names."""
        evaluator = self.evaluator(files, path)
        evaluator.parse(await files.read_text(Path(path)), filename=Path(path).name)
        return await evaluator.execute()

    async def test_from_dot_import_module(self) -> None:
        """``from . import helper`` gives the file as a module."""
        files = FakeFileSystem()
        files.write(Path("/auto/main.py"), "from . import helper\nr = helper.double(2)\n")
        files.write(Path("/auto/helper.py"), "def double(v):\n    return v * 2\n")

        symbols = await self.run(files)

        assert symbols["r"] == 4
        assert isinstance(symbols["helper"], AutomationModule)

    async def test_from_module_import_name(self) -> None:
        """``from .helper import name`` gives names of the file, with aliases."""
        files = FakeFileSystem()
        files.write(Path("/auto/main.py"), "from .helper import double as twice, LIMIT\nr = twice(LIMIT)\n")
        files.write(Path("/auto/helper.py"), "LIMIT = 5\ndef double(v):\n    return v * 2\n")

        assert (await self.run(files))["r"] == 10

    async def test_package_and_parent(self) -> None:
        """Sub-folders and ``..`` work within the automation."""
        files = FakeFileSystem()
        files.write(
            Path("/auto/main.py"),
            "from .lights.scenes import evening\nfrom .lights import NAME\nr = (evening(), NAME)\n",
        )
        files.write(Path("/auto/lights/__init__.py"), "NAME = 'lights'\n")
        files.write(
            Path("/auto/lights/scenes.py"), "from ..common import LEVEL\ndef evening():\n    return LEVEL\n"
        )
        files.write(Path("/auto/common.py"), "LEVEL = 40\n")

        assert (await self.run(files))["r"] == (40, "lights")

    async def test_module_is_loaded_once_and_shared(self) -> None:
        """Every import of a file gives the same module, executed once."""
        files = FakeFileSystem()
        files.write(
            Path("/auto/main.py"),
            "from . import state\nfrom .other import bump\nbump()\nbump()\nr = (state.count, state.loads)\n",
        )
        files.write(Path("/auto/state.py"), "count = 0\nloads = []\nloads.append('loaded')\n")
        files.write(
            Path("/auto/other.py"), "from . import state\ndef bump():\n    state.loads.append('bump')\n"
        )

        assert (await self.run(files))["r"] == (0, ["loaded", "bump", "bump"])

    async def test_module_attributes_are_live(self) -> None:
        """A module attribute reflects later changes made inside the module."""
        files = FakeFileSystem()
        files.write(Path("/auto/main.py"), "from . import counter\ncounter.bump()\nr = counter.value\n")
        files.write(Path("/auto/counter.py"), "value = 0\ndef bump():\n    global value\n    value += 1\n")

        assert (await self.run(files))["r"] == 1

    async def test_circular_import(self) -> None:
        """Two files importing each other load, as in Python."""
        files = FakeFileSystem()
        files.write(Path("/auto/main.py"), "from . import a\nr = a.call_b()\n")
        files.write(
            Path("/auto/a.py"),
            "from . import b\ndef call_b():\n    return b.answer()\ndef base():\n    return 20\n",
        )
        files.write(Path("/auto/b.py"), "from . import a\ndef answer():\n    return a.base() + 1\n")

        assert (await self.run(files))["r"] == 21

    async def test_missing_module(self) -> None:
        """Importing a file that does not exist fails as in Python."""
        files = FakeFileSystem()
        files.write(Path("/auto/main.py"), "from . import nothing\n")

        with pytest.raises(
            AutomationRuntimeError, match="No module named '.nothing' in automation 'auto'"
        ) as raised:
            await self.run(files)

        assert isinstance(raised.value.__cause__, ModuleNotFoundError)

    async def test_missing_name(self) -> None:
        """Importing a name the file does not define fails as in Python."""
        files = FakeFileSystem()
        files.write(Path("/auto/main.py"), "from .helper import nothing\n")
        files.write(Path("/auto/helper.py"), "x = 1\n")

        with pytest.raises(AutomationRuntimeError, match="cannot import name 'nothing' from '.helper'"):
            await self.run(files)

    async def test_module_does_not_expose_builtins(self) -> None:
        """Only the names a file defines are its attributes."""
        files = FakeFileSystem()
        files.write(Path("/auto/helper.py"), "x = 1\n")
        files.write(
            Path("/auto/main.py"),
            "from . import helper\ntry:\n    helper.missing\nexcept AttributeError as e:\n    r = str(e)\n",
        )

        assert (await self.run(files))["r"] == "module 'helper' has no attribute 'missing'"

    async def test_cannot_leave_the_automation(self) -> None:
        """A relative import above the automation's folder is refused."""
        files = FakeFileSystem()
        files.write(Path("/auto/main.py"), "from .. import secrets\n")
        files.write(Path("/secrets.py"), "KEY = 1\n")

        with pytest.raises(AutomationSecurityError, match="outside the automation"):
            await self.run(files)

    async def test_imported_file_is_checked_before_it_runs(self) -> None:
        """An imported file with a disallowed import or unsupported Python does not run."""
        files = FakeFileSystem()
        files.write(Path("/auto/main.py"), "from . import helper\n")
        files.write(Path("/auto/helper.py"), "ran = True\nimport os\n")
        evaluator = self.evaluator(files)
        evaluator.parse(await files.read_text(Path("/auto/main.py")))

        with pytest.raises(AutomationSecurityError, match=r"^helper.py:2: import of module 'os'"):
            await evaluator.execute()

    async def test_failed_module_is_not_kept(self) -> None:
        """A file that failed to load is loaded again on the next import."""
        files = FakeFileSystem()
        files.write(Path("/auto/main.py"), "try:\n    from . import helper\nexcept Exception:\n    pass\n")
        files.write(Path("/auto/helper.py"), "x = 1 / 0\n")
        evaluator = self.evaluator(files)
        evaluator.parse(await files.read_text(Path("/auto/main.py")))

        await evaluator.execute()

        assert evaluator.loader is not None
        assert evaluator.loader.modules == {}

    async def test_relative_import_is_allowed_statically(self) -> None:
        """Relative imports are never reported by the static check."""
        validate_source("from . import a\nfrom .b import c\nfrom ..d import e\n", imports=controller())

    async def test_not_available_without_files(self) -> None:
        """An evaluator that was not given the automation's files cannot import them."""
        with pytest.raises(AutomationRuntimeError, match="relative imports are not available"):
            await load("from . import helper\n")

    async def test_in_a_loaded_automation(self, tmp_path: Path) -> None:
        """An automation on disk imports a file next to it and shares its ``haa``."""
        (tmp_path / "helper.py").write_text(
            "from haanim import haa\ndef automation_id():\n    return haa.id\n", encoding="utf-8"
        )
        path = tmp_path / "auto.py"
        path.write_text(
            "from haanim import action\n"
            "from haanim import haa\nfrom .helper import automation_id\nfrom . import helper\n"
            "same = helper.haa is haa\n\n@action\ndef which():\n    return automation_id()\n",
            encoding="utf-8",
        )
        context = make_context(str(path))
        await context.load()

        assert context.get_symbol("same") is True
        assert await context.run_action("which") == "auto"


class TestSymbolsForModules:
    """Module-level details the guard rails rely on."""

    async def test_name_is_set(self) -> None:
        """``__name__`` is the automation's name."""
        assert (await load("r = __name__\n"))["r"] == "test"

    async def test_name_is_not_overwritten(self) -> None:
        """A ``__name__`` the caller set is kept."""
        scope = SymbolTable()
        scope.set("__name__", "custom")

        assert (await load("r = __name__\n", global_symbols=scope))["r"] == "custom"


def _disk() -> Any:
    """Return a file system that reads real files."""
    from haanim.testing import LocalFileSystem  # pylint: disable=import-outside-toplevel

    return LocalFileSystem()
