"""Tests for the ``haanim`` package as what an automation author installs.

See "Packaging" in the design: the package carries the type information for
everything an automation imports from ``haanim``, and ships ``py.typed``.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

import haanim
from haanim.engine import decorators
from haanim.engine.errors import PUBLIC_ERRORS
from haanim.engine.haanim_api import HAAnim
from haanim.engine.haanim_module import DECORATORS, EVENT_CLASSES, DecoratorRegistry, build_haanim_module
from haanim.engine.logging_wrapper import LoggerWrapper, create_logger_wrapper
from haanim.testing import FakeAutomationRegistry, make_host

PACKAGE = Path(haanim.__file__).parent


@pytest.fixture
def automation_module() -> Any:
    """The ``haanim`` module the interpreter gives to one automation."""
    import logging  # pylint: disable=import-outside-toplevel

    haa = HAAnim(make_host(), "me", FakeAutomationRegistry())
    return build_haanim_module(
        haa=haa,
        registry=DecoratorRegistry(),
        logging_wrapper=create_logger_wrapper(logging.getLogger("test.public_api")),
        hass=None,
        helpers={"sleep": haa.sleep},
    )


class TestSameNames:
    """What an automation can import at runtime is what the package declares for type checkers."""

    def test_every_runtime_name_is_declared(self, automation_module: Any) -> None:
        """Test each name of an automation's module is in the package's __all__."""
        assert set(automation_module.__all__) <= set(haanim.__all__)

    def test_nothing_else_is_declared(self, automation_module: Any) -> None:
        """Test the package declares no automation name the runtime lacks."""
        own = {"PUBLIC_ERRORS", "RUNTIME_ONLY", "LoggerWrapper", "__version__"}
        assert set(haanim.__all__) - own == set(automation_module.__all__)

    def test_all_is_sorted_and_unique(self) -> None:
        """Test __all__ lists each name once."""
        assert len(haanim.__all__) == len(set(haanim.__all__))

    @pytest.mark.parametrize("name", sorted(DECORATORS))
    def test_decorators_are_the_engines(self, name: str) -> None:
        """Test a decorator of the package is the engine's function, with its signature."""
        assert getattr(haanim, name) is DECORATORS[name]
        assert getattr(haanim, name) is getattr(decorators, name)

    @pytest.mark.parametrize("cls", [*EVENT_CLASSES, *PUBLIC_ERRORS], ids=lambda cls: cls.__name__)
    def test_classes_are_the_runtimes(self, automation_module: Any, cls: type) -> None:
        """Test an event or error class is the same object in the package and at runtime."""
        assert getattr(haanim, cls.__name__) is cls
        assert getattr(automation_module, cls.__name__) is cls

    @pytest.mark.parametrize(
        "name",
        [
            "HAAnim",
            "HAAnimAutomationProxy",
            "HAAnimCard",
            "HAAnimEntity",
            "HAAnimServiceCall",
            "HAAnimServiceProxy",
            "ActionMode",
        ],
    )
    def test_api_classes_are_the_runtimes(self, automation_module: Any, name: str) -> None:
        """Test the classes behind haa are the same object in the package and at runtime."""
        assert getattr(haanim, name) is getattr(automation_module, name)


class TestRuntimeOnlyNames:
    """haa, hass, logging and sleep belong to a running automation."""

    def test_declared_for_type_checkers(self) -> None:
        """Test the package's source declares them with their types under TYPE_CHECKING."""
        source = (PACKAGE / "__init__.py").read_text(encoding="utf-8")
        block = source[source.index("if TYPE_CHECKING:") : source.index("def __getattr__")]
        assert "haa: HAAnim" in block
        assert "hass: Any" in block
        assert "logging: LoggerWrapper" in block
        assert "async def sleep(duration: str | float) -> None:" in block
        assert haanim.RUNTIME_ONLY == ("haa", "hass", "logging", "sleep")

    @pytest.mark.parametrize("name", ["haa", "hass", "logging", "sleep"])
    def test_not_there_outside_an_automation(self, name: str) -> None:
        """Test using one outside an automation says where it comes from."""
        with pytest.raises(AttributeError, match="only inside a running automation"):
            getattr(haanim, name)

    def test_unknown_name(self) -> None:
        """Test a name the package never had is an ordinary AttributeError."""
        with pytest.raises(AttributeError, match="module 'haanim' has no attribute 'nothing'"):
            getattr(haanim, "nothing")

    def test_runtime_types_match_the_declarations(self, automation_module: Any) -> None:
        """Test what the runtime supplies is of the declared type."""
        assert isinstance(automation_module.haa, HAAnim)
        assert isinstance(automation_module.logging, LoggerWrapper)
        assert inspect.iscoroutinefunction(automation_module.sleep)
        assert list(inspect.signature(automation_module.sleep).parameters) == ["duration"]


class TestTyped:
    """The package ships its type information."""

    def test_py_typed(self) -> None:
        """Test the marker file is in the package."""
        assert (PACKAGE / "py.typed").is_file()

    def test_no_stub_file_left(self) -> None:
        """Test the hand-written stubs are gone: the package is its own type information."""
        assert not (PACKAGE.parents[1] / "stubs").exists()
        assert list(PACKAGE.rglob("*.pyi")) == []
