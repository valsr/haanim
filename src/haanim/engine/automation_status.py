"""Automation status tracking for HAAnim.

This module provides status tracking for automations, including the current action
being executed, user-defined status messages, and timing information.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

_LOGGER = logging.getLogger(__name__)


class AutomationRunState(Enum):
    """High-level run state of an automation."""

    IDLE = "idle"
    RUNNING = "running"
    STARTUP = "startup"
    SHUTDOWN = "shutdown"


@dataclass
class AutomationStatus:
    """Status information for an automation.

    Args:
        automation_id: Name of the automation.
        run_state: Current run state.
        running_actions: Dictionary of currently running actions by execution_id.
        last_error: Last error message if any.
        last_action: Name of the action that most recently started executing.
    """

    automation_id: str
    run_state: AutomationRunState = AutomationRunState.IDLE
    running_actions: dict[str, str] = field(default_factory=dict)
    last_error: str | None = None
    last_action: str | None = None

    @property
    def is_running(self) -> bool:
        """Check if any action is currently running."""
        return len(self.running_actions) > 0


class AutomationStatusManager:
    """Manager for tracking automation execution status."""

    def __init__(self) -> None:
        """Initialize the status manager."""
        self._statuses: dict[str, AutomationStatus] = {}
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[str], None]] = []

    def add_listener(self, listener: Callable[[str], None]) -> Callable[[], None]:
        """Call ``listener(automation_id)`` whenever something about an automation has changed.

        That is its state, its message, its failures and the actions it is running.

        Returns:
            A function that removes the listener.
        """
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def notify(self, automation_id: str) -> None:
        """Tell the listeners that something about an automation has changed."""
        for listener in list(self._listeners):
            try:
                listener(automation_id)
            except Exception:  # pylint: disable=broad-exception-caught
                _LOGGER.exception("A status listener failed for automation '%s'", automation_id)

    def get_status(self, automation_id: str) -> AutomationStatus:
        """Get the status for an automation.

        Args:
            automation_id: Name of the automation.

        Returns:
            The automation status.
        """
        if automation_id not in self._statuses:
            self._statuses[automation_id] = AutomationStatus(automation_id=automation_id)
        return self._statuses[automation_id]

    def add_running_action(
        self,
        automation_id: str,
        action_name: str,
        execution_id: str,
        *,
        is_startup: bool = False,
        is_shutdown: bool = False,
    ) -> None:
        """Add a running action to the automation status.

        Args:
            automation_id: Name of the automation.
            action_name: Name of the action.
            execution_id: Unique execution ID.
            is_startup: Whether this is a startup action.
            is_shutdown: Whether this is a shutdown action.
        """
        status = self.get_status(automation_id)
        status.running_actions[execution_id] = action_name

        if is_startup:
            status.run_state = AutomationRunState.STARTUP
        elif is_shutdown:
            status.run_state = AutomationRunState.SHUTDOWN
        else:
            status.run_state = AutomationRunState.RUNNING
            status.last_action = action_name
        self.notify(automation_id)

    def remove_running_action(self, automation_id: str, execution_id: str, error: str | None = None) -> None:
        """Remove a running action from the automation status.

        Args:
            automation_id: Name of the automation.
            execution_id: Unique execution ID.
            error: Optional error message.
        """
        status = self.get_status(automation_id)
        status.running_actions.pop(execution_id, None)

        if error:
            status.last_error = error

        # Update run state based on remaining actions
        if not status.running_actions:
            status.run_state = AutomationRunState.IDLE
        self.notify(automation_id)

    def set_idle(self, automation_id: str, error: str | None = None) -> None:
        """Set an automation to idle state.

        Args:
            automation_id: Name of the automation.
            error: Optional error message.
        """
        status = self.get_status(automation_id)
        status.run_state = AutomationRunState.IDLE
        status.running_actions.clear()
        if error:
            status.last_error = error

    def clear_error(self, automation_id: str) -> None:
        """Clear the error for an automation.

        Args:
            automation_id: Name of the automation.
        """
        status = self.get_status(automation_id)
        status.last_error = None

    def set_status_message(self, automation_id: str, message: str | None) -> None:
        """Set a custom status message for an automation.

        Args:
            automation_id: Name of the automation.
            message: Status message to set, or None to clear it.
        """
        status = self.get_status(automation_id)
        # Store message in last_error field for now - we can add a separate message field later if needed
        status.last_error = message

    def get_all_statuses(self) -> dict[str, AutomationStatus]:
        """Get all automation statuses.

        Returns:
            Dictionary of automation statuses by automation name.
        """
        return self._statuses.copy()
