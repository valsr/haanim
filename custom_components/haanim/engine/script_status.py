"""Script status tracking for HAAnim.

This module provides status tracking for scripts, including the current action
being executed, user-defined status messages, and timing information.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum

_LOGGER = logging.getLogger(__name__)


class ScriptRunState(Enum):
    """High-level run state of a script."""

    IDLE = "idle"
    RUNNING = "running"
    STARTUP = "startup"
    SHUTDOWN = "shutdown"


@dataclass
class ScriptStatus:
    """Status information for a script.

    Args:
        script_name: Name of the script.
        run_state: Current run state.
        running_actions: Dictionary of currently running actions by execution_id.
        last_error: Last error message if any.
    """

    script_name: str
    run_state: ScriptRunState = ScriptRunState.IDLE
    running_actions: dict[str, str] = field(default_factory=dict)
    last_error: str | None = None

    @property
    def is_running(self) -> bool:
        """Check if any action is currently running."""
        return len(self.running_actions) > 0


class ScriptStatusManager:
    """Manager for tracking script execution status."""

    def __init__(self) -> None:
        """Initialize the status manager."""
        self._statuses: dict[str, ScriptStatus] = {}
        self._lock = asyncio.Lock()

    def get_status(self, script_name: str) -> ScriptStatus:
        """Get the status for a script.

        Args:
            script_name: Name of the script.

        Returns:
            The script status.
        """
        if script_name not in self._statuses:
            self._statuses[script_name] = ScriptStatus(script_name=script_name)
        return self._statuses[script_name]

    def add_running_action(
        self,
        script_name: str,
        action_name: str,
        execution_id: str,
        is_startup: bool = False,
        is_shutdown: bool = False,
    ) -> None:
        """Add a running action to the script status.

        Args:
            script_name: Name of the script.
            action_name: Name of the action.
            execution_id: Unique execution ID.
            is_startup: Whether this is a startup action.
            is_shutdown: Whether this is a shutdown action.
        """
        status = self.get_status(script_name)
        status.running_actions[execution_id] = action_name

        if is_startup:
            status.run_state = ScriptRunState.STARTUP
        elif is_shutdown:
            status.run_state = ScriptRunState.SHUTDOWN
        else:
            status.run_state = ScriptRunState.RUNNING

    def remove_running_action(self, script_name: str, execution_id: str, error: str | None = None) -> None:
        """Remove a running action from the script status.

        Args:
            script_name: Name of the script.
            execution_id: Unique execution ID.
            error: Optional error message.
        """
        status = self.get_status(script_name)
        status.running_actions.pop(execution_id, None)

        if error:
            status.last_error = error

        # Update run state based on remaining actions
        if not status.running_actions:
            status.run_state = ScriptRunState.IDLE

    def set_idle(self, script_name: str, error: str | None = None) -> None:
        """Set a script to idle state.

        Args:
            script_name: Name of the script.
            error: Optional error message.
        """
        status = self.get_status(script_name)
        status.run_state = ScriptRunState.IDLE
        status.running_actions.clear()
        if error:
            status.last_error = error

    def clear_error(self, script_name: str) -> None:
        """Clear the error for a script.

        Args:
            script_name: Name of the script.
        """
        status = self.get_status(script_name)
        status.last_error = None

    def set_status_message(self, script_name: str, message: str) -> None:
        """Set a custom status message for a script.

        Args:
            script_name: Name of the script.
            message: Status message to set.
        """
        status = self.get_status(script_name)
        # Store message in last_error field for now - we can add a separate message field later if needed
        status.last_error = message

    def get_all_statuses(self) -> dict[str, ScriptStatus]:
        """Get all script statuses.

        Returns:
            Dictionary of script statuses by script name.
        """
        return self._statuses.copy()


# Global status manager instance
_status_manager: ScriptStatusManager | None = None


def get_status_manager() -> ScriptStatusManager:
    """Get the global script status manager.

    Returns:
        The global ScriptStatusManager instance.
    """
    global _status_manager  # pylint: disable=global-statement
    if _status_manager is None:
        _status_manager = ScriptStatusManager()
    return _status_manager


def reset_status_manager() -> None:
    """Reset the global status manager.

    This is primarily for testing purposes.
    """
    global _status_manager  # pylint: disable=global-statement
    _status_manager = None
