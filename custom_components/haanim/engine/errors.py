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


class ScriptDisabledError(ScriptError):
    """Exception raised when attempting to operate on a disabled script."""

    def __init__(self, script_id: str) -> None:
        """Initialize the script disabled error.

        Args:
            script_id: The ID of the disabled script.
        """
        super().__init__(f"Script '{script_id}' is disabled")
        self.script_id = script_id


class ScriptNotLoadedError(ScriptError):
    """Exception raised when attempting to use a script that is not loaded."""

    def __init__(self, script_id: str) -> None:
        """Initialize the script not loaded error.

        Args:
            script_id: The ID of the script that is not loaded.
        """
        super().__init__(f"Script '{script_id}' is not loaded")
        self.script_id = script_id


class ScriptAlreadyRunningError(ScriptError):
    """Exception raised when attempting to start a script that is already running."""

    def __init__(self, script_id: str) -> None:
        """Initialize the script already running error.

        Args:
            script_id: The ID of the script.
        """
        super().__init__(f"Script '{script_id}' is already running")
        self.script_id = script_id


class ScriptNotRunningError(ScriptError):
    """Exception raised when attempting to stop a script that is not running."""

    def __init__(self, script_id: str) -> None:
        """Initialize the script not running error.

        Args:
            script_id: The ID of the script.
        """
        super().__init__(f"Script '{script_id}' is not running")
        self.script_id = script_id


class NonExistingScriptError(ScriptError):
    """Exception raised when referencing a script that does not exist."""

    def __init__(self, script_id: str) -> None:
        """Initialize the non-existing script error.

        Args:
            script_id: The ID of the non-existent script.
        """
        super().__init__(f"Script '{script_id}' does not exist")
        self.script_id = script_id


class NonExistingEntityError(ScriptError):
    """Exception raised when accessing an entity that does not exist."""

    def __init__(self, entity_id: str) -> None:
        """Initialize the non-existing entity error.

        Args:
            entity_id: The entity ID that does not exist.
        """
        super().__init__(f"Entity '{entity_id}' does not exist")
        self.entity_id = entity_id


class NonExistingServiceError(ScriptError):
    """Exception raised when calling a service that does not exist."""

    def __init__(self, domain: str, service: str) -> None:
        """Initialize the non-existing service error.

        Args:
            domain: The service domain.
            service: The service name.
        """
        super().__init__(f"Service '{domain}.{service}' does not exist")
        self.domain = domain
        self.service = service


class ActionNotFoundError(ScriptError):
    """Exception raised when calling an action that doesn't exist."""

    def __init__(self, script_id: str, action_name: str) -> None:
        """Initialize the action not found error.

        Args:
            script_id: The ID of the script.
            action_name: The name of the action.
        """
        super().__init__(f"Action '{action_name}' not found in script '{script_id}'")
        self.script_id = script_id
        self.action_name = action_name


class ActionFailedError(ScriptError):
    """Exception raised when an action fails during execution."""

    def __init__(self, script_id: str, action_name: str, reason: str) -> None:
        """Initialize the action failed error.

        Args:
            script_id: The ID of the script.
            action_name: The name of the action.
            reason: The reason for failure.
        """
        super().__init__(f"Action '{action_name}' in script '{script_id}' failed: {reason}")
        self.script_id = script_id
        self.action_name = action_name
        self.reason = reason


class ActionTimeOutError(ScriptError):
    """Exception raised when an action exceeds its timeout."""

    def __init__(self, script_id: str, action_name: str, timeout: float) -> None:
        """Initialize the action timeout error.

        Args:
            script_id: The ID of the script.
            action_name: The name of the action.
            timeout: The timeout value in seconds.
        """
        super().__init__(f"Action '{action_name}' in script '{script_id}' exceeded timeout of {timeout}s")
        self.script_id = script_id
        self.action_name = action_name
        self.timeout = timeout


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


class QueueFullError(ScriptError):
    """Exception raised when an action queue is full."""

    def __init__(self, script_id: str, action_name: str, queue_size: int) -> None:
        """Initialize the queue full error.

        Args:
            script_id: The ID of the script.
            action_name: The name of the action.
            queue_size: The maximum queue size.
        """
        super().__init__(
            f"Queue for action '{action_name}' in script '{script_id}' is full (max: {queue_size})"
        )
        self.script_id = script_id
        self.action_name = action_name
        self.queue_size = queue_size


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
