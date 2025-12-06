"""Custom exceptions for script engine errors."""


class ScriptError(Exception):
    """Base exception for script execution errors."""

    def __init__(self, message: str, lineno: int | None = None, col_offset: int | None = None) -> None:
        """Initialize the script error.

        Args:
            message: Error message.
            lineno: Line number where error occurred.
            col_offset: Column offset where error occurred.
        """
        super().__init__(message)
        self.lineno = lineno
        self.col_offset = col_offset


class ScriptSecurityError(ScriptError):
    """Exception raised for security violations in scripts."""


class ScriptSyntaxError(ScriptError):
    """Exception raised for syntax errors in scripts."""


class ScriptRuntimeError(ScriptError):
    """Exception raised for runtime errors in scripts."""


class ActionBusyError(ScriptError):
    """Exception raised when a script is already executing an action.

    This error occurs when an action is requested for a script that already has
    an action running. Scripts can only execute one action at a time.
    """

    def __init__(self, script_name: str, current_action: str) -> None:
        """Initialize the action busy error.

        Args:
            script_name: Name of the script that is busy.
            current_action: Name of the action currently running.
        """
        super().__init__(
            f"Script '{script_name}' is busy executing action '{current_action}'. "
            "Only one action per script can run at a time."
        )
        self.script_name = script_name
        self.current_action = current_action


class PoolExhaustedError(ScriptError):
    """Exception raised when the action worker pool has no available workers.

    This error occurs when the maximum number of concurrent actions across all
    scripts has been reached.
    """

    def __init__(self, max_workers: int) -> None:
        """Initialize the pool exhausted error.

        Args:
            max_workers: The maximum number of concurrent workers allowed.
        """
        super().__init__(
            f"Action worker pool exhausted. Maximum of {max_workers} concurrent actions reached. "
            "Please wait for other actions to complete."
        )
        self.max_workers = max_workers


class ActionCancelledError(ScriptError):
    """Exception raised when an action is cancelled.

    This error occurs when a running action is forcefully cancelled, typically
    during script shutdown or when the script is being reloaded.
    """

    def __init__(self, action_name: str, reason: str = "shutdown requested") -> None:
        """Initialize the action cancelled error.

        Args:
            action_name: Name of the action that was cancelled.
            reason: Reason for cancellation.
        """
        super().__init__(f"Action '{action_name}' was cancelled: {reason}")
        self.action_name = action_name
        self.reason = reason


class ShutdownTimeoutError(ScriptError):
    """Exception raised when a shutdown action exceeds its timeout.

    This error occurs when a script's @shutdown decorated function takes longer
    than the allowed timeout period to complete.
    """

    def __init__(self, script_name: str, timeout: float) -> None:
        """Initialize the shutdown timeout error.

        Args:
            script_name: Name of the script whose shutdown timed out.
            timeout: The timeout value in seconds.
        """
        super().__init__(
            f"Shutdown action for script '{script_name}' exceeded timeout of {timeout * 1000:.0f}ms "
            "and was forcefully terminated."
        )
        self.script_name = script_name
        self.timeout = timeout


class ActionQueueTimeoutError(ScriptError):
    """Exception raised when a queued action exceeds its queue timeout.

    This error occurs when an action is waiting in queue for a script to
    become available, but the timeout is exceeded before it can run.
    """

    def __init__(self, script_name: str, action_name: str, timeout: float) -> None:
        """Initialize the queue timeout error.

        Args:
            script_name: Name of the script.
            action_name: Name of the action that timed out.
            timeout: The timeout value in seconds.
        """
        super().__init__(
            f"Action '{action_name}' for script '{script_name}' timed out after waiting "
            f"{timeout:.1f}s in queue."
        )
        self.script_name = script_name
        self.action_name = action_name
        self.timeout = timeout
