"""The lifecycle of an automation: load, start, stop, unload.

See "Automation Lifecycle" in the design. Each step either completes or leaves
the automation in the ``error`` state with a message; there are no partial
states.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from haanim.const import DEFAULT_SHUTDOWN_TIMEOUT, DEFAULT_STARTUP_TIMEOUT, DEFAULT_STOP_GRACE_PERIOD
from haanim.engine.errors import (
    ActionNotFoundError,
    AutomationAlreadyRunningError,
    AutomationNotLoadedError,
    AutomationNotRunningError,
)

if TYPE_CHECKING:
    from haanim.engine.action_pool import ActionWorkerPool
    from haanim.engine.automation_context import AutomationContext, TriggerDefinition

_LOGGER = logging.getLogger(__name__)

# The automation whose @startup or @shutdown handler the current code was called from.
# A context variable follows the code into the tasks it starts, and nowhere else.
_HANDLER_OF: contextvars.ContextVar[Automation | None] = contextvars.ContextVar(
    "haanim_handler_of", default=None
)

STARTUP_ACTION = "__startup__"
SHUTDOWN_ACTION = "__shutdown__"


class AutomationState(Enum):
    """The state of an automation.

    UNAVAILABLE: Not loaded.
    OFF: Loaded but not running.
    ON: Running: ``@startup`` completed and triggers are registered.
    ERROR: Loading or starting failed; the message holds the reason.
    """

    UNAVAILABLE = "unavailable"
    OFF = "off"
    ON = "on"
    ERROR = "error"


class TriggerRegistrar(Protocol):
    """Where the triggers of running automations are registered."""

    async def register_trigger(
        self, trigger_def: TriggerDefinition, constraints: list[dict[str, Any]] | None = None
    ) -> str:
        """Start firing a trigger. Returns an ID for it."""

    async def unregister_automation_triggers(self, automation_id: str) -> int:
        """Stop firing every trigger of an automation and discard its pending timers."""


class NoTriggers:
    """A registrar for a host that fires no triggers: registering does nothing."""

    async def register_trigger(
        self, trigger_def: TriggerDefinition, constraints: list[dict[str, Any]] | None = None
    ) -> str:
        """Accept a trigger without ever firing it."""
        return ""

    async def unregister_automation_triggers(self, automation_id: str) -> int:
        """Report that nothing was registered."""
        return 0


@dataclass(frozen=True)
class LifecycleSettings:
    """Time limits of the lifecycle steps, in seconds.

    Args:
        startup_timeout: How long ``@startup`` may take.
        shutdown_timeout: How long ``@shutdown`` may take.
        stop_grace_period: How long running actions get to finish when the
            automation is stopped, before they are cancelled.
    """

    startup_timeout: float = DEFAULT_STARTUP_TIMEOUT
    shutdown_timeout: float = DEFAULT_SHUTDOWN_TIMEOUT
    stop_grace_period: float = DEFAULT_STOP_GRACE_PERIOD


def _seconds(value: float) -> str:
    """Format a number of seconds for a message."""
    return f"{value:g} second" if value == 1 else f"{value:g} seconds"


def _describe(err: BaseException) -> str:
    """Describe an exception for the automation's message."""
    text = str(err)
    return f"{type(err).__name__}: {text}" if text else type(err).__name__


class Automation:
    """One automation and the state it is in.

    Wraps the automation's context and moves it through the lifecycle steps.
    The steps of one automation must not run concurrently; the caller starts
    and stops automations one at a time.
    """

    def __init__(
        self,
        context: AutomationContext,
        *,
        pool: ActionWorkerPool,
        triggers: TriggerRegistrar,
        settings: LifecycleSettings | None = None,
    ) -> None:
        """Initialize the automation in the ``unavailable`` state.

        Args:
            context: The automation's context.
            pool: Where the automation's actions and lifecycle handlers run.
            triggers: Where the automation's triggers are registered.
            settings: The time limits. The design's defaults if omitted.
        """
        self.context = context
        self._pool = pool
        self._triggers = triggers
        self._settings = settings or LifecycleSettings()
        self._clock = context.host.clock
        self._state = AutomationState.UNAVAILABLE
        self._message: str | None = None
        self._last_error: str | None = None
        # Whether @startup or @shutdown is running; it may call the automation's own actions.
        self._handler_running = False
        self._stopping = False

    @property
    def automation_id(self) -> str:
        """The automation's ID."""
        return self.context.automation_id

    @property
    def state(self) -> AutomationState:
        """The automation's state."""
        return self._state

    @property
    def message(self) -> str | None:
        """Why the automation is in the ``error`` state; None in every other state."""
        return self._message

    @property
    def last_error(self) -> str | None:
        """The most recent failure that did not change the state, such as a failing ``@shutdown``."""
        return self._last_error

    def _set_state(self, state: AutomationState, message: str | None = None) -> None:
        """Move to a state."""
        if state is not self._state or message != self._message:
            _LOGGER.debug(
                "Automation '%s': %s -> %s%s",
                self.automation_id,
                self._state.value,
                state.value,
                f" ({message})" if message else "",
            )
        self._state = state
        self._message = message

    def _fail(self, message: str) -> None:
        """Move to the ``error`` state with a reason."""
        _LOGGER.error("Automation '%s': %s", self.automation_id, message)
        self._set_state(AutomationState.ERROR, message)

    # --- Load ---------------------------------------------------------------------

    async def load(self) -> bool:
        """Read the metadata and check every file of the automation. Runs no automation code.

        Returns:
            True if the automation is now ``off``; False if it is in ``error``.

        Raises:
            AutomationAlreadyRunningError: If the automation is ``on``; stop it first.
        """
        if self._state is AutomationState.ON:
            raise AutomationAlreadyRunningError(self.automation_id)

        try:
            await self.context.load()
        except Exception as err:  # pylint: disable=broad-exception-caught
            self.context.unload()
            self._fail(str(err) or type(err).__name__)
            return False

        self._set_state(AutomationState.OFF)
        return True

    # --- Start --------------------------------------------------------------------

    async def start(self) -> bool:
        """Run the automation's code, its ``@startup`` handler, and register its triggers.

        An automation in ``error`` is loaded again first. If any step raises or
        times out, the namespace is discarded, ``@shutdown`` is not called, no
        trigger stays registered and the state is ``error``.

        Returns:
            True if the automation is now ``on``; False if it is in ``error``.

        Raises:
            AutomationNotLoadedError: If the automation is ``unavailable``.
            AutomationAlreadyRunningError: If the automation is ``on``.
        """
        if self._state is AutomationState.UNAVAILABLE:
            raise AutomationNotLoadedError(self.automation_id)
        if self._state is AutomationState.ON:
            raise AutomationAlreadyRunningError(self.automation_id)
        if self._state is AutomationState.ERROR and not await self.load():
            return False

        try:
            await self.context.execute()
            await self._run_startup()
            for trigger in self.context.get_triggers():
                await self._triggers.register_trigger(trigger)
        except Exception as err:  # pylint: disable=broad-exception-caught
            await self._abandon_start()
            self._fail(str(err) if isinstance(err, _StartupFailure) else _describe(err))
            return False
        except BaseException:
            await self._abandon_start()
            self._set_state(AutomationState.OFF)
            raise

        self._set_state(AutomationState.ON)
        return True

    async def _run_startup(self) -> None:
        """Call ``@startup`` and wait for it, bounded by the startup timeout."""
        startup = self.context.get_startup_func()
        if startup is None:
            return

        timeout = self._settings.startup_timeout
        self._handler_running = True
        token = _HANDLER_OF.set(self)
        try:
            await self._clock.wait_for(
                self._pool.submit_action(self.automation_id, STARTUP_ACTION, startup, is_lifecycle=True),
                timeout,
            )
        except TimeoutError as err:
            raise _StartupFailure(f"@startup did not finish within {_seconds(timeout)}") from err
        except Exception as err:
            raise _StartupFailure(f"@startup failed: {_describe(err)}") from err
        finally:
            _HANDLER_OF.reset(token)
            self._handler_running = False

    async def _abandon_start(self) -> None:
        """Undo a start that failed part-way."""
        await self._triggers.unregister_automation_triggers(self.automation_id)
        await self._pool.cancel_automation_actions(self.automation_id, "automation failed to start")
        self.context.discard()

    # --- Stop ---------------------------------------------------------------------

    async def stop(self) -> None:
        """Stop the automation: triggers, running actions, ``@shutdown``, namespace.

        A failing or slow ``@shutdown`` is recorded in ``last_error`` and does
        not prevent the automation from stopping.

        Raises:
            AutomationNotRunningError: If the automation is not ``on``.
        """
        if self._state is not AutomationState.ON or self._stopping:
            raise AutomationNotRunningError(self.automation_id)

        self._stopping = True
        try:
            await self._triggers.unregister_automation_triggers(self.automation_id)
            await self._finish_running_actions()
            await self._run_shutdown()
        finally:
            self._stopping = False
            self.context.discard()
            self._set_state(AutomationState.OFF)

    async def _finish_running_actions(self) -> None:
        """Give running actions the grace period, then cancel the ones still running."""
        grace = self._settings.stop_grace_period
        try:
            await self._clock.wait_for(self._pool.wait_idle(self.automation_id), grace)
            return
        except TimeoutError:
            pass

        await self._pool.cancel_automation_actions(self.automation_id, "automation stopped")
        try:
            await self._clock.wait_for(self._pool.wait_idle(self.automation_id), grace)
        except TimeoutError:
            _LOGGER.warning(
                "Automation '%s': actions were still running %s after being cancelled",
                self.automation_id,
                _seconds(grace),
            )

    async def _run_shutdown(self) -> None:
        """Call ``@shutdown`` and wait for it, bounded by the shutdown timeout."""
        shutdown = self.context.get_shutdown_func()
        if shutdown is None:
            return

        timeout = self._settings.shutdown_timeout
        self._handler_running = True
        token = _HANDLER_OF.set(self)
        try:
            await self._clock.wait_for(
                self._pool.submit_action(self.automation_id, SHUTDOWN_ACTION, shutdown, is_lifecycle=True),
                timeout,
            )
        except TimeoutError:
            self._record_error(f"@shutdown did not finish within {_seconds(timeout)}")
        except Exception as err:  # pylint: disable=broad-exception-caught
            self._record_error(f"@shutdown failed: {_describe(err)}")
        finally:
            _HANDLER_OF.reset(token)
            self._handler_running = False

    def _record_error(self, message: str) -> None:
        """Record a failure that does not change the state."""
        _LOGGER.error("Automation '%s': %s", self.automation_id, message)
        self._last_error = message

    # --- Unload -------------------------------------------------------------------

    async def unload(self) -> None:
        """Release the automation's code. A running automation is stopped first."""
        if self._state is AutomationState.ON:
            await self.stop()
        self.context.unload()
        self._set_state(AutomationState.UNAVAILABLE)

    # --- Calls --------------------------------------------------------------------

    def accepts_calls(self) -> bool:
        """Return whether an action of the automation can be called now.

        Actions can be called while the automation is ``on`` and not being
        stopped. In addition, the automation's own ``@startup`` and
        ``@shutdown`` handlers can call its actions.
        """
        if self._handler_running and _HANDLER_OF.get() is self:
            return True
        return self._state is AutomationState.ON and not self._stopping

    async def call_action(self, action_name: str, *args: Any, **kwargs: Any) -> Any:
        """Call an action of the automation.

        Args:
            action_name: Name of the action.
            *args: Positional arguments for the action.
            **kwargs: Keyword arguments for the action.

        Returns:
            What the action returns.

        Raises:
            AutomationNotRunningError: If the automation is not running.
            ActionNotFoundError: If the automation has no such action.
        """
        if not self.accepts_calls():
            raise AutomationNotRunningError(self.automation_id)

        action = self.context.get_action(action_name)
        if action is None:
            raise ActionNotFoundError(self.automation_id, action_name)

        # The action runs in a task of its own: if the caller is cancelled (its
        # automation is stopped, say), the call it already made runs to completion here.
        running = asyncio.ensure_future(
            self._pool.submit_action(self.automation_id, action_name, action.func, *args, **kwargs)
        )
        running.add_done_callback(_retrieve_exception)
        return await asyncio.shield(running)


def _retrieve_exception(task: asyncio.Future[Any]) -> None:
    """Mark the exception of an action as seen, for when its caller is no longer waiting for it."""
    if not task.cancelled():
        task.exception()


class _StartupFailure(Exception):
    """``@startup`` raised or timed out; the message is the automation's error message."""


def _by_id(automations: Iterable[Automation]) -> list[Automation]:
    """Sort automations by ascending ID."""
    return sorted(automations, key=lambda automation: automation.automation_id)


async def load_all(automations: Iterable[Automation]) -> None:
    """Load automations one at a time in ascending order of ID.

    Args:
        automations: The automations to load. Running ones are left alone.
    """
    for automation in _by_id(automations):
        if automation.state is not AutomationState.ON:
            await automation.load()


async def start_all(automations: Iterable[Automation]) -> None:
    """Start every automation that loaded without error, one at a time in ascending order of ID.

    A ``@startup`` can therefore rely on automations with a smaller ID being
    ``on``.

    Args:
        automations: The automations to start. Only those in ``off`` are started.
    """
    for automation in _by_id(automations):
        if automation.state is AutomationState.OFF:
            await automation.start()


async def stop_all(automations: Iterable[Automation]) -> None:
    """Stop every running automation, one at a time in descending order of ID.

    Args:
        automations: The automations to stop. Only those in ``on`` are stopped.
    """
    for automation in reversed(_by_id(automations)):
        if automation.state is AutomationState.ON:
            await automation.stop()


async def unload_all(automations: Iterable[Automation]) -> None:
    """Stop and unload automations, one at a time in descending order of ID.

    Args:
        automations: The automations to unload.
    """
    for automation in reversed(_by_id(automations)):
        await automation.unload()
