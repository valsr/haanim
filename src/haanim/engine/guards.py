"""Guard rails on the members of modules an automation may import.

Some members of allowed modules block the event loop or leave it. An automation
gets a stand-in for such a module in which those members raise
AutomationSecurityError when used; everything else is the real module's.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, NoReturn

from haanim.const import DISABLED_LOOP_MEMBERS, DISABLED_MODULE_MEMBERS, LOOP_GETTERS
from haanim.engine.errors import AutomationSecurityError


def _disabled(name: str, hint: str) -> Callable[..., NoReturn]:
    """Return a callable that refuses to run in place of a disabled member."""

    def refuse(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise AutomationSecurityError(f"'{name}' is not available in automations: {hint}")

    refuse.__name__ = name.rsplit(".", maxsplit=1)[-1]
    refuse.__qualname__ = name
    return refuse


class Guarded:
    """Stand-in for an object in which some members are disabled.

    Reading a disabled member succeeds, so ``from time import sleep`` loads;
    calling it raises AutomationSecurityError. All other attributes are read
    from, written to and deleted on the real object.
    """

    def __init__(
        self,
        target: Any,
        name: str,
        disabled: Mapping[str, str],
        wrap: Mapping[str, Callable[[Any], Any]] | None = None,
    ) -> None:
        """Initialize the stand-in.

        Args:
            target: The real object.
            name: Name to report the object by, e.g. ``asyncio``.
            disabled: Disabled member names, each with a hint on what to use instead.
            wrap: Members that are functions whose result is to be passed through
                the given function.
        """
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_disabled", dict(disabled))
        object.__setattr__(self, "_wrap", dict(wrap or {}))

    def __getattr__(self, attr: str) -> Any:
        """Return a member of the real object, or its disabled replacement."""
        disabled: dict[str, str] = object.__getattribute__(self, "_disabled")
        name: str = object.__getattribute__(self, "_name")
        if attr in disabled:
            return _disabled(f"{name}.{attr}", disabled[attr])

        value = getattr(object.__getattribute__(self, "_target"), attr)
        wrap: dict[str, Callable[[Any], Any]] = object.__getattribute__(self, "_wrap")
        if attr in wrap:
            wrapper = wrap[attr]

            def wrapped(*args: Any, **kwargs: Any) -> Any:
                return wrapper(value(*args, **kwargs))

            return wrapped
        return value

    def __setattr__(self, attr: str, value: Any) -> None:
        """Set a member on the real object."""
        setattr(object.__getattribute__(self, "_target"), attr, value)

    def __delattr__(self, attr: str) -> None:
        """Delete a member of the real object."""
        delattr(object.__getattribute__(self, "_target"), attr)

    def __dir__(self) -> list[str]:
        """List the members of the real object."""
        return dir(object.__getattribute__(self, "_target"))

    def __repr__(self) -> str:
        """Describe the stand-in by what it stands for."""
        return f"<guarded {object.__getattribute__(self, '_target')!r}>"


def guard_loop(loop: Any) -> Any:
    """Return a stand-in for an event loop that cannot be run or used with threads.

    Args:
        loop: The event loop.
    """
    return Guarded(loop, "loop", DISABLED_LOOP_MEMBERS)


def guard_module(name: str, module: Any) -> Any:
    """Return what an automation gets when it imports a module.

    Args:
        name: The module's full name.
        module: The real module.

    Returns:
        A stand-in if the module has disabled members, otherwise the module itself.
    """
    disabled = DISABLED_MODULE_MEMBERS.get(name)
    if disabled is None:
        return module
    wrap = {getter: guard_loop for getter in LOOP_GETTERS} if name == "asyncio" else None
    return Guarded(module, name, disabled, wrap)
