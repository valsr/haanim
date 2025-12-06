"""Script status tracking for HAAnim.

This module provides status tracking for scripts, including the current action
being executed, user-defined status messages, and timing information.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

_LOGGER = logging.getLogger(__name__)


class ScriptRunState(Enum):
    """High-level run state of a script."""

    IDLE = "idle"
    RUNNING = "running"
    STARTING = "starting"
    STOPPING = "stopping"


@dataclass
class ScriptStatus:
    """Status information for a script.

    Args:
        script_name: Name of the script.
        run_state: Current run state (idle, running, starting, stopping).
        action_name: Name of the currently running action (if any).
        status_message: User-defined status message.
        state_changed_at: When the current state was entered.
        last_action: Name of the last action that was executed.
        last_action_completed_at: When the last action completed.
        last_error: The last error that occurred (if any).
    """

    script_name: str
    run_state: ScriptRunState = ScriptRunState.IDLE
    action_name: str | None = None
    status_message: str | None = None
    state_changed_at: datetime = field(default_factory=datetime.now)
    last_action: str | None = None
    last_action_completed_at: datetime | None = None
    last_error: str | None = None

    def get_elapsed_seconds(self) -> float:
        """Get the time elapsed since the state changed.

        Returns:
            Elapsed time in seconds.
        """
        return (datetime.now() - self.state_changed_at).total_seconds()

    def get_elapsed_formatted(self) -> str:
        """Get the elapsed time formatted as a human-readable string.

        Returns:
            Formatted elapsed time (e.g., "5s", "1m 30s", "2h 15m").
        """
        elapsed = self.get_elapsed_seconds()

        if elapsed < 60:
            return f"{elapsed:.0f}s"
        if elapsed < 3600:
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            return f"{minutes}m {seconds}s"

        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        return f"{hours}h {minutes}m"

    def get_display_status(self) -> str:
        """Get the full display status string for the UI.

        Returns:
            Formatted status string like "Running action_name (5s): Status message"
            or "Idle" when not running.
        """
        if self.run_state == ScriptRunState.IDLE:
            return "Idle"

        # Build the status string
        state_name = self.run_state.value.capitalize()
        elapsed = self.get_elapsed_formatted()

        if self.action_name:
            base = f"{state_name} {self.action_name} ({elapsed})"
        else:
            base = f"{state_name} ({elapsed})"

        if self.status_message:
            return f"{base}: {self.status_message}"
        return base

    def to_dict(self) -> dict[str, Any]:
        """Convert status to a dictionary for API/UI consumption.

        Returns:
            Dictionary representation of the status.
        """
        return {
            "script_name": self.script_name,
            "run_state": self.run_state.value,
            "action_name": self.action_name,
            "status_message": self.status_message,
            "elapsed_seconds": self.get_elapsed_seconds(),
            "elapsed_formatted": self.get_elapsed_formatted(),
            "display_status": self.get_display_status(),
            "last_action": self.last_action,
            "last_action_completed_at": (
                self.last_action_completed_at.isoformat() if self.last_action_completed_at else None
            ),
            "last_error": self.last_error,
        }


class ScriptStatusManager:
    """Manager for tracking status of all scripts.

    Provides a centralized way to track and update script statuses,
    including action execution states and user-defined status messages.
    """

    def __init__(self) -> None:
        """Initialize the status manager."""
        self._statuses: dict[str, ScriptStatus] = {}
        self._status_callbacks: list[Callable[[str, ScriptStatus], None]] = []

    def get_status(self, script_name: str) -> ScriptStatus:
        """Get the status for a script, creating if needed.

        Args:
            script_name: Name of the script.

        Returns:
            The ScriptStatus for the script.
        """
        if script_name not in self._statuses:
            self._statuses[script_name] = ScriptStatus(script_name=script_name)
        return self._statuses[script_name]

    def get_all_statuses(self) -> dict[str, ScriptStatus]:
        """Get all script statuses.

        Returns:
            Dictionary mapping script names to their statuses.
        """
        return self._statuses.copy()

    def set_running(
        self,
        script_name: str,
        action_name: str,
        is_startup: bool = False,
        is_shutdown: bool = False,
    ) -> None:
        """Mark a script as running an action.

        Args:
            script_name: Name of the script.
            action_name: Name of the action being executed.
            is_startup: Whether this is a startup action.
            is_shutdown: Whether this is a shutdown action.
        """
        status = self.get_status(script_name)

        if is_startup:
            status.run_state = ScriptRunState.STARTING
        elif is_shutdown:
            status.run_state = ScriptRunState.STOPPING
        else:
            status.run_state = ScriptRunState.RUNNING

        status.action_name = action_name
        status.status_message = None
        status.state_changed_at = datetime.now()

        _LOGGER.debug(
            "Script '%s' status changed to %s (action: %s)",
            script_name,
            status.run_state.value,
            action_name,
        )
        self._notify_change(script_name, status)

    def set_idle(self, script_name: str, error: str | None = None) -> None:
        """Mark a script as idle (no action running).

        Args:
            script_name: Name of the script.
            error: Optional error message if the action failed.
        """
        status = self.get_status(script_name)

        # Preserve last action info
        if status.action_name:
            status.last_action = status.action_name
            status.last_action_completed_at = datetime.now()

        status.run_state = ScriptRunState.IDLE
        status.action_name = None
        status.status_message = None
        status.state_changed_at = datetime.now()

        if error:
            status.last_error = error

        _LOGGER.debug("Script '%s' status changed to idle", script_name)
        self._notify_change(script_name, status)

    def set_status_message(self, script_name: str, message: str | None) -> None:
        """Set a user-defined status message for a script.

        This can be called from within a running action to update the
        status message displayed to the user.

        Args:
            script_name: Name of the script.
            message: The status message to display, or None to clear.
        """
        status = self.get_status(script_name)
        status.status_message = message

        _LOGGER.debug(
            "Script '%s' status message updated: %s",
            script_name,
            message,
        )
        self._notify_change(script_name, status)

    def clear_status_message(self, script_name: str) -> None:
        """Clear the status message for a script.

        Args:
            script_name: Name of the script.
        """
        self.set_status_message(script_name, None)

    def remove_script(self, script_name: str) -> None:
        """Remove status tracking for a script.

        Args:
            script_name: Name of the script to remove.
        """
        if script_name in self._statuses:
            del self._statuses[script_name]
            _LOGGER.debug("Removed status tracking for script '%s'", script_name)

    def register_callback(
        self, callback: Callable[[str, ScriptStatus], None]
    ) -> Callable[[str, ScriptStatus], None]:
        """Register a callback for status changes.

        Args:
            callback: Function to call when status changes.
                      Signature: callback(script_name: str, status: ScriptStatus)

        Returns:
            The callback (for use as a decorator).
        """
        self._status_callbacks.append(callback)
        return callback

    def unregister_callback(self, callback: Callable[[str, ScriptStatus], None]) -> None:
        """Unregister a status change callback.

        Args:
            callback: The callback to remove.
        """
        if callback in self._status_callbacks:
            self._status_callbacks.remove(callback)

    def _notify_change(self, script_name: str, status: ScriptStatus) -> None:
        """Notify all registered callbacks of a status change.

        Args:
            script_name: Name of the script that changed.
            status: The new status.
        """
        for callback in self._status_callbacks:
            try:
                callback(script_name, status)
            except Exception as err:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Error in status callback: %s", err)


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
