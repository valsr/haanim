"""The lifecycle of an automation: load, start, stop, unload.

See "Automation Lifecycle" in the design. Each step either completes or leaves
the automation in the ``error`` state with a message; there are no partial
states.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from haanim.const import (
    DEFAULT_SHUTDOWN_TIMEOUT,
    DEFAULT_STARTUP_TIMEOUT,
    DEFAULT_STOP_GRACE_PERIOD,
    EVENT_ACTION_ERROR,
)
from haanim.engine.callables import event_arguments
from haanim.engine.errors import (
    ActionDroppedError,
    ActionNotFoundError,
    AutomationAlreadyRunningError,
    AutomationDefinitionError,
    AutomationNotLoadedError,
    AutomationNotRunningError,
)
from haanim.events import SOURCE_TRIGGER
from haanim.interfaces import AutomationTimes

if TYPE_CHECKING:
    from haanim.engine.action_dispatcher import ActionDispatcher
    from haanim.engine.automation_context import AutomationContext, TriggerDefinition

_LOGGER = logging.getLogger(__name__)

# The automation whose @startup or @shutdown handler the current code was called from.
# A context variable follows the code into the tasks it starts, and nowhere else.
_HANDLER_OF: contextvars.ContextVar[Automation | None] = contextvars.ContextVar(
    "haanim_handler_of", default=None
)

STARTUP_ACTION = "__startup__"
SHUTDOWN_ACTION = "__shutdown__"

REASON_STOPPED = "automation stopped"
REASON_START_FAILED = "automation failed to start"


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

    async def register_trigger(self, trigger_def: TriggerDefinition) -> str:
        """Start firing a trigger. Returns an ID for it."""

    async def unregister_automation_triggers(self, automation_id: str) -> int:
        """Stop firing every trigger of an automation and discard its pending timers."""


class NoTriggers:
    """A registrar for a host that fires no triggers: registering does nothing."""

    async def register_trigger(self, trigger_def: TriggerDefinition) -> str:
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


@dataclass(frozen=True)
class ActionFailure:
    """A failure that left the automation running: the value of ``last_error``.

    Args:
        time: When it happened.
        action: Name of the action, or ``"@shutdown"``.
        error_type: Name of the exception class.
        message: The exception's message.
    """

    time: datetime
    action: str
    error_type: str
    message: str

    def __str__(self) -> str:
        """Describe the failure in one line."""
        return (
            f"{self.action}: {self.error_type}: {self.message}"
            if self.message
            else f"{self.action}: {self.error_type}"
        )


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
        dispatcher: ActionDispatcher,
        triggers: TriggerRegistrar,
        settings: LifecycleSettings | None = None,
    ) -> None:
        """Initialize the automation in the ``unavailable`` state.

        Args:
            context: The automation's context.
            dispatcher: Where the automation's actions and lifecycle handlers run.
            triggers: Where the automation's triggers are registered.
            settings: The time limits. The design's defaults if omitted.
        """
        self.context = context
        self._dispatcher = dispatcher
        self._triggers = triggers
        self._settings = settings or LifecycleSettings()
        self._clock = context.host.clock
        self._state = AutomationState.UNAVAILABLE
        self._message: str | None = None
        self._last_error: ActionFailure | None = None
        self._load_time: datetime | None = None
        self._run_time: datetime | None = None
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
    def last_error(self) -> ActionFailure | None:
        """The most recent failure that did not change the state.

        That is an action that failed when a trigger called it, or a failing
        ``@shutdown``. None if there was none.
        """
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

        self._load_time = self._clock.now()
        self._set_state(AutomationState.OFF)
        return True

    @property
    def times(self) -> AutomationTimes:
        """When the automation was loaded, last started, and last ran an action."""
        return AutomationTimes(
            load_time=self._load_time,
            run_time=self._run_time,
            last_action_time=self._dispatcher.last_action_time(self.automation_id),
        )

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
            self._dispatcher.set_failure_handler(self.automation_id, self.record_action_failure)
            for trigger in self.context.get_triggers():
                await self._triggers.register_trigger(trigger)
        except Exception as err:  # pylint: disable=broad-exception-caught
            await self._abandon_start()
            own_message = isinstance(err, (_StartupFailure, AutomationDefinitionError))
            self._fail(str(err) if own_message else _describe(err))
            return False
        except BaseException:
            await self._abandon_start()
            self._set_state(AutomationState.OFF)
            raise

        self._run_time = self._clock.now()
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
                self._dispatcher.run_handler(
                    self.automation_id, STARTUP_ACTION, startup, *self._handler_arguments(startup)
                ),
                timeout,
            )
        except TimeoutError as err:
            raise _StartupFailure(f"@startup did not finish within {_seconds(timeout)}") from err
        except Exception as err:
            raise _StartupFailure(f"@startup failed: {_describe(err)}") from err
        finally:
            _HANDLER_OF.reset(token)
            self._handler_running = False

    def _handler_arguments(self, handler: Any) -> tuple[Any, ...]:
        """Return what to call a lifecycle handler with: its event, if it takes one."""
        return event_arguments(handler, self.context.make_event(source=SOURCE_TRIGGER))

    async def _abandon_start(self) -> None:
        """Undo a start that failed part-way."""
        await self._triggers.unregister_automation_triggers(self.automation_id)
        self._dispatcher.set_failure_handler(self.automation_id, None)
        self._dispatcher.remove_queued(self.automation_id, REASON_START_FAILED)
        self._dispatcher.cancel_running(self.automation_id, REASON_START_FAILED)
        await self._flush_variables()
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
            self._dispatcher.remove_queued(self.automation_id, REASON_STOPPED)
            await self._finish_running_actions()
            await self._run_shutdown()
        finally:
            self._stopping = False
            self._dispatcher.set_failure_handler(self.automation_id, None)
            await self._flush_variables()
            self.context.discard()
            self._set_state(AutomationState.OFF)

    async def _finish_running_actions(self) -> None:
        """Give running actions the grace period, then cancel the ones still running."""
        grace = self._settings.stop_grace_period
        try:
            await self._clock.wait_for(self._dispatcher.wait_idle(self.automation_id), grace)
            return
        except TimeoutError:
            pass

        self._dispatcher.cancel_running(self.automation_id, REASON_STOPPED)
        try:
            await self._clock.wait_for(self._dispatcher.wait_idle(self.automation_id), grace)
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
                self._dispatcher.run_handler(
                    self.automation_id, SHUTDOWN_ACTION, shutdown, *self._handler_arguments(shutdown)
                ),
                timeout,
            )
        except TimeoutError:
            self._record_failure(
                "@shutdown", "TimeoutError", f"@shutdown did not finish within {_seconds(timeout)}"
            )
        except Exception as err:  # pylint: disable=broad-exception-caught
            self._record_failure("@shutdown", type(err).__name__, str(err))
        finally:
            _HANDLER_OF.reset(token)
            self._handler_running = False

    async def _flush_variables(self) -> None:
        """Write the persistent variables that have changed: always done before the namespace goes."""
        if self.context.variables is not None:
            await self.context.variables.flush()

    def _record_failure(
        self, action: str, error_type: str, message: str, level: int = logging.ERROR
    ) -> ActionFailure:
        """Record a failure that does not change the state: log it and set ``last_error``."""
        failure = ActionFailure(self._clock.now(), action, error_type, message)
        self.context.logger.log(level, "Automation '%s': %s", self.automation_id, failure)
        self._last_error = failure
        return failure

    def record_action_failure(self, action_name: str, error: BaseException) -> None:
        """Record the failure of an action that a trigger called.

        There is no caller to raise to, so the failure is logged to the
        automation's logger, kept as ``last_error`` and announced with a
        ``haanim_action_error`` event. The automation stays ``on``.

        Args:
            action_name: The action's name.
            error: What the action raised, or the error that kept it from running.
        """
        # A dropped request is the DROP mode doing its work, not a fault in the action
        level = logging.WARNING if isinstance(error, ActionDroppedError) else logging.ERROR
        failure = self._record_failure(action_name, type(error).__name__, str(error), level)
        self.context.host.events.fire(
            EVENT_ACTION_ERROR,
            {
                "automation_id": self.automation_id,
                "action": failure.action,
                "error_type": failure.error_type,
                "message": failure.message,
            },
        )

    # --- Unload -------------------------------------------------------------------

    async def unload(self) -> None:
        """Release the automation's code. A running automation is stopped first."""
        if self._state is AutomationState.ON:
            await self.stop()
        self.context.unload()
        self._load_time = None
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

    async def call_action(
        self,
        action_name: str,
        data: dict[str, Any] | None = None,
        *,
        caller: str | None = None,
    ) -> Any:
        """Call an action of the automation.

        The action receives an ``AutomationEvent`` if ``caller`` is given, else
        a ``ManualEvent``; this holds for trigger functions too. The data is
        delivered as ``event.data``.

        Args:
            action_name: A name of the action.
            data: The arguments of the call.
            caller: ID of the calling automation. Without it the call is a manual one.

        Returns:
            What the action returns.

        Raises:
            AutomationNotLoadedError: If the automation is not loaded.
            AutomationNotRunningError: If the automation is stopped, disabled or in error.
            ActionNotFoundError: If the automation has no such action, or it is disabled.
            ActionDroppedError: If the request is dropped (``DROP`` mode, or a re-entrant call).
            QueueFullError: If the action's queue is full (``QUEUE`` mode).
            ActionCancelledError: If the execution is cancelled.
            Exception: Whatever the action raises.
        """
        if self._state is AutomationState.UNAVAILABLE:
            raise AutomationNotLoadedError(self.automation_id)
        if not self.accepts_calls():
            raise AutomationNotRunningError(self.automation_id)

        # A disabled action is listed but cannot be called
        action = self.context.get_action(action_name)
        if action is None or action.disabled:
            raise ActionNotFoundError(self.automation_id, action_name)

        event = self.context.make_event(caller=caller, data=data)

        # The dispatcher runs the action in a task of its own: if the caller is cancelled
        # (its automation is stopped, say), the call it already made runs to completion.
        return await self._dispatcher.dispatch(
            self.automation_id,
            action.name,
            action.func,
            *event_arguments(action.func, event),
            mode=action.execution_mode,
            timeout=action.timeout,
        )


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


async def start_all(
    automations: Iterable[Automation], is_enabled: Callable[[str], bool] | None = None
) -> None:
    """Start every enabled automation that loaded without error, one at a time in ascending order of ID.

    A ``@startup`` can therefore rely on automations with a smaller ID being
    ``on``.

    Args:
        automations: The automations to start. Only those in ``off`` are started.
        is_enabled: Tells whether the automation with an ID is enabled. All are if omitted.
    """
    for automation in _by_id(automations):
        if automation.state is not AutomationState.OFF:
            continue
        if is_enabled is None or is_enabled(automation.automation_id):
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
