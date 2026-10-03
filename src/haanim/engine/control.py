"""Controlling automations: enable, disable, start, stop, restart.

See "Controlling Automations" and "Current Automation Control" in the design.
Enable and disable are a persistent switch; start, stop and restart are
temporary and do not change it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from haanim.engine.errors import AutomationDisabledError, AutomationNotRunningError
from haanim.engine.eval_function import CHECKPOINT
from haanim.engine.lifecycle import Automation, AutomationState
from haanim.interfaces import StorageBackend

if TYPE_CHECKING:
    from haanim.engine.action_pool import ActionWorkerPool

_LOGGER = logging.getLogger(__name__)

# Key of the document that holds the enabled flags
ENABLED_STORAGE_KEY = "enabled"


class EnabledFlags:
    """The persistent enabled flag of every automation, by automation ID.

    An automation is enabled unless it was disabled. The flags are kept for
    automations whose folder is gone, so that moving a folder away and back
    does not lose the flag.
    """

    def __init__(self, storage: StorageBackend) -> None:
        """Initialize with every automation enabled, until ``load()`` is called.

        Args:
            storage: Where the flags are kept.
        """
        self._storage = storage
        self._disabled: set[str] = set()

    async def load(self) -> None:
        """Read the flags from storage. Without stored flags every automation is enabled."""
        data = await self._storage.load(ENABLED_STORAGE_KEY)
        disabled = data.get("disabled", []) if isinstance(data, dict) else []
        self._disabled = {item for item in disabled if isinstance(item, str)}

    def is_enabled(self, automation_id: str) -> bool:
        """Return whether an automation is enabled. An automation never seen before is.

        Args:
            automation_id: The automation's ID.
        """
        return automation_id not in self._disabled

    async def set_enabled(self, automation_id: str, enabled: bool) -> bool:
        """Set the flag of an automation and store it.

        Args:
            automation_id: The automation's ID.
            enabled: The new value.

        Returns:
            Whether the flag changed.
        """
        if enabled == self.is_enabled(automation_id):
            return False
        if enabled:
            self._disabled.discard(automation_id)
        else:
            self._disabled.add(automation_id)
        await self._storage.save(ENABLED_STORAGE_KEY, {"disabled": sorted(self._disabled)})
        return True


class AutomationControl:
    """The control operations on automations.

    An action that stops, restarts or disables its own automation cannot wait
    for that to finish: it is one of the things being stopped. For such a call
    the operation is scheduled and the calling action is cancelled at the
    call, so the statements after it do not run and its ``finally`` blocks do.
    """

    def __init__(self, flags: EnabledFlags, pool: ActionWorkerPool) -> None:
        """Initialize the control operations.

        Args:
            flags: The enabled flags.
            pool: The pool the automations' actions run in, used to recognise
                a call that comes from an action of the automation itself.
        """
        self._flags = flags
        self._pool = pool
        self._scheduled: set[asyncio.Future[Any]] = set()

    def is_enabled(self, automation_id: str) -> bool:
        """Return whether an automation is enabled."""
        return self._flags.is_enabled(automation_id)

    # --- Enable and disable ------------------------------------------------------

    async def enable(self, automation: Automation) -> None:
        """Mark an automation enabled and start it. Does nothing if it is enabled.

        Args:
            automation: The automation.
        """
        if not await self._flags.set_enabled(automation.automation_id, True):
            return
        if automation.state in (AutomationState.OFF, AutomationState.ERROR):
            await automation.start()

    async def disable(self, automation: Automation) -> None:
        """Stop an automation if it is running and mark it disabled. Does nothing if it is disabled.

        Args:
            automation: The automation.
        """
        if not await self._flags.set_enabled(automation.automation_id, False):
            return
        if automation.state is AutomationState.ON:
            await self._stop_or_schedule(automation, automation.stop)

    # --- Start, stop and restart -------------------------------------------------

    def _require_enabled(self, automation: Automation) -> None:
        """Raise if the automation is disabled."""
        if not self.is_enabled(automation.automation_id):
            raise AutomationDisabledError(automation.automation_id)

    async def start(self, automation: Automation) -> None:
        """Start an automation. One in the ``error`` state is loaded again first.

        Args:
            automation: The automation.

        Raises:
            AutomationDisabledError: If the automation is disabled.
            AutomationAlreadyRunningError: If the automation is running.
            AutomationNotLoadedError: If the automation is not loaded.
        """
        self._require_enabled(automation)
        await automation.start()

    async def stop(self, automation: Automation) -> None:
        """Stop an automation until the next restart of the host or hot reload.

        Args:
            automation: The automation.

        Raises:
            AutomationDisabledError: If the automation is disabled.
            AutomationNotRunningError: If the automation is not running.
        """
        self._require_enabled(automation)
        self._require_running(automation)
        await self._stop_or_schedule(automation, automation.stop)

    async def restart(self, automation: Automation) -> None:
        """Stop an automation and start it again.

        Args:
            automation: The automation.

        Raises:
            AutomationDisabledError: If the automation is disabled.
            AutomationNotRunningError: If the automation is not running.
        """
        self._require_enabled(automation)
        self._require_running(automation)

        async def stop_and_start() -> None:
            await automation.stop()
            await automation.start()

        await self._stop_or_schedule(automation, stop_and_start)

    @staticmethod
    def _require_running(automation: Automation) -> None:
        """Raise if the automation is not running."""
        if not automation.accepts_calls() or automation.state is not AutomationState.ON:
            raise AutomationNotRunningError(automation.automation_id)

    # --- Calls from inside the automation ----------------------------------------

    def _called_from_inside(self, automation: Automation) -> bool:
        """Return whether the current code is running as an action of the automation."""
        current = asyncio.current_task()
        return any(
            execution.task is current for execution in self._pool.get_active_actions(automation.automation_id)
        )

    async def _stop_or_schedule(
        self, automation: Automation, operation: Callable[[], Awaitable[None]]
    ) -> None:
        """Run a stopping operation, or schedule it if the caller is an action of the automation."""
        if not self._called_from_inside(automation):
            await operation()
            return

        scheduled = asyncio.ensure_future(operation())
        self._scheduled.add(scheduled)
        scheduled.add_done_callback(self._operation_done)

        # End the calling action here: it never gets past this call.
        current = asyncio.current_task()
        assert current is not None
        current.cancel()
        await CHECKPOINT

    def _operation_done(self, scheduled: asyncio.Future[Any]) -> None:
        """Log a scheduled operation that failed; nobody is waiting for it."""
        self._scheduled.discard(scheduled)
        if not scheduled.cancelled() and scheduled.exception() is not None:
            _LOGGER.error("Scheduled automation control operation failed", exc_info=scheduled.exception())

    async def wait_scheduled(self) -> None:
        """Wait until every operation scheduled by an automation on itself has finished."""
        while self._scheduled:
            await asyncio.gather(*self._scheduled, return_exceptions=True)
