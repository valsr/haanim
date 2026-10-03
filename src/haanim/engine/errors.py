"""Custom exceptions for HAAnim.

All exceptions derive from HAAnimError. PUBLIC_ERRORS lists the ones automations
can import from the ``haanim`` module.
"""

from collections.abc import Sequence
from typing import Any


class HAAnimError(Exception):
    """Base exception for all HAAnim errors."""

    def __init__(self, message: str, lineno: int | None = None, col_offset: int | None = None) -> None:
        """Initialize the automation error.

        Args:
            message: Error message.
            lineno: Line number where error occurred.
            col_offset: Column offset where error occurred.
        """
        super().__init__(message)
        self.lineno = lineno
        self.col_offset = col_offset


class SourceError(HAAnimError):
    """Base of the errors found by checking an automation's source before it runs."""

    def __init__(
        self,
        message: str,
        lineno: int | None = None,
        col_offset: int | None = None,
        *,
        filename: str | None = None,
        problems: Sequence[Any] = (),
    ) -> None:
        """Initialize the error.

        Args:
            message: Error message.
            lineno: Line number of the first problem.
            col_offset: Column offset of the first problem.
            filename: File the first problem is in.
            problems: Every problem found, each with ``filename``, ``lineno``,
                ``col_offset`` and ``message``.
        """
        super().__init__(message, lineno=lineno, col_offset=col_offset)
        self.filename = filename
        self.problems = tuple(problems)


class AutomationSecurityError(SourceError):
    """Exception raised when an automation uses a disallowed import, builtin or module member."""


class AutomationSyntaxError(SourceError):
    """Exception raised when an automation's source cannot be loaded.

    Raised for invalid Python and for Python the interpreter does not support.
    """


class AutomationMetadataError(HAAnimError):
    """Exception raised when an automation's ``metadata.json`` cannot be used."""


class AutomationDefinitionError(HAAnimError):
    """Exception raised when what an automation's decorators define does not fit together.

    For example two actions with one name, or two ``@startup`` handlers.
    """


class AutomationRuntimeError(HAAnimError):
    """Exception raised for runtime errors in automations."""


class AutomationDisabledError(HAAnimError):
    """Exception raised when attempting to operate on a disabled automation."""

    def __init__(self, automation_id: str) -> None:
        """Initialize the automation disabled error.

        Args:
            automation_id: The ID of the disabled automation.
        """
        super().__init__(f"Automation '{automation_id}' is disabled")
        self.automation_id = automation_id


class AutomationNotLoadedError(HAAnimError):
    """Exception raised when attempting to use an automation that is not loaded."""

    def __init__(self, automation_id: str) -> None:
        """Initialize the automation not loaded error.

        Args:
            automation_id: The ID of the automation that is not loaded.
        """
        super().__init__(f"Automation '{automation_id}' is not loaded")
        self.automation_id = automation_id


class AutomationAlreadyRunningError(HAAnimError):
    """Exception raised when attempting to start an automation that is already running."""

    def __init__(self, automation_id: str) -> None:
        """Initialize the automation already running error.

        Args:
            automation_id: The ID of the automation.
        """
        super().__init__(f"Automation '{automation_id}' is already running")
        self.automation_id = automation_id


class AutomationNotRunningError(HAAnimError):
    """Exception raised when attempting to stop an automation that is not running."""

    def __init__(self, automation_id: str) -> None:
        """Initialize the automation not running error.

        Args:
            automation_id: The ID of the automation.
        """
        super().__init__(f"Automation '{automation_id}' is not running")
        self.automation_id = automation_id


class NonExistingAutomationError(HAAnimError):
    """Exception raised when referencing an automation that does not exist."""

    def __init__(self, automation_id: str) -> None:
        """Initialize the non-existing automation error.

        Args:
            automation_id: The ID of the non-existent automation.
        """
        super().__init__(f"Automation '{automation_id}' does not exist")
        self.automation_id = automation_id


class NonExistingEntityError(HAAnimError):
    """Exception raised when accessing an entity that does not exist."""

    def __init__(self, entity_id: str) -> None:
        """Initialize the non-existing entity error.

        Args:
            entity_id: The entity ID that does not exist.
        """
        super().__init__(f"Entity '{entity_id}' does not exist")
        self.entity_id = entity_id


class NonExistingServiceError(HAAnimError):
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


class ActionNotFoundError(HAAnimError):
    """Exception raised when calling an action that doesn't exist."""

    def __init__(self, automation_id: str, action_name: str) -> None:
        """Initialize the action not found error.

        Args:
            automation_id: The ID of the automation.
            action_name: The name of the action.
        """
        super().__init__(f"Action '{action_name}' not found in automation '{automation_id}'")
        self.automation_id = automation_id
        self.action_name = action_name


class ActionDroppedError(HAAnimError):
    """Exception raised when an action request is dropped.

    A request is dropped when the action uses the DROP execution mode and is
    already executing, or when the action is called re-entrantly.
    """

    def __init__(self, automation_id: str, action_name: str, reason: str = "already executing") -> None:
        """Initialize the action dropped error.

        Args:
            automation_id: The ID of the automation.
            action_name: The name of the action.
            reason: Why the request was dropped.
        """
        super().__init__(f"Action '{action_name}' in automation '{automation_id}' was dropped: {reason}")
        self.automation_id = automation_id
        self.action_name = action_name
        self.reason = reason


class ActionTimeOutError(HAAnimError):
    """Exception raised when an action exceeds its timeout."""

    def __init__(self, automation_id: str, action_name: str, timeout: float) -> None:
        """Initialize the action timeout error.

        Args:
            automation_id: The ID of the automation.
            action_name: The name of the action.
            timeout: The timeout value in seconds.
        """
        super().__init__(
            f"Action '{action_name}' in automation '{automation_id}' exceeded timeout of {timeout}s"
        )
        self.automation_id = automation_id
        self.action_name = action_name
        self.timeout = timeout


class ActionCancelledError(HAAnimError):
    """Exception raised when an action is cancelled.

    This error occurs when a running action is forcefully cancelled, typically
    during automation shutdown or when the automation is being reloaded.
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


class QueueFullError(HAAnimError):
    """Exception raised when an action queue is full."""

    def __init__(self, automation_id: str, action_name: str, queue_size: int) -> None:
        """Initialize the queue full error.

        Args:
            automation_id: The ID of the automation.
            action_name: The name of the action.
            queue_size: The maximum queue size.
        """
        super().__init__(
            f"Queue for action '{action_name}' in automation '{automation_id}' is full (max: {queue_size})"
        )
        self.automation_id = automation_id
        self.action_name = action_name
        self.queue_size = queue_size


class PoolExhaustedError(HAAnimError):
    """Exception raised when the action worker pool has no available workers.

    This error occurs when the maximum number of concurrent actions across all
    automations has been reached.
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


class ShutdownTimeoutError(HAAnimError):
    """Exception raised when a shutdown action exceeds its timeout.

    This error occurs when an automation's @shutdown decorated function takes longer
    than the allowed timeout period to complete.
    """

    def __init__(self, automation_id: str, timeout: float) -> None:
        """Initialize the shutdown timeout error.

        Args:
            automation_id: Name of the automation whose shutdown timed out.
            timeout: The timeout value in seconds.
        """
        super().__init__(
            f"Shutdown action for automation '{automation_id}' exceeded timeout of {timeout * 1000:.0f}ms "
            "and was forcefully terminated."
        )
        self.automation_id = automation_id
        self.timeout = timeout


class ServiceCallError(HAAnimError):
    """Exception raised by a host when a service call fails.

    This is internal: the ``haa`` API reports it to automations through the
    result object of the call, it is not raised to them.
    """

    def __init__(self, domain: str, service: str, reason: str) -> None:
        """Initialize the service call error.

        Args:
            domain: The service domain.
            service: The service name.
            reason: Why the call failed.
        """
        super().__init__(f"Service '{domain}.{service}' failed: {reason}")
        self.domain = domain
        self.service = service
        self.reason = reason


PUBLIC_ERRORS: tuple[type[HAAnimError], ...] = (
    HAAnimError,
    AutomationSyntaxError,
    AutomationSecurityError,
    NonExistingAutomationError,
    AutomationNotLoadedError,
    AutomationNotRunningError,
    AutomationAlreadyRunningError,
    AutomationDisabledError,
    ActionNotFoundError,
    ActionDroppedError,
    QueueFullError,
    PoolExhaustedError,
    ActionTimeOutError,
    ActionCancelledError,
    NonExistingEntityError,
    NonExistingServiceError,
)
"""Errors exported to automations through the ``haanim`` module."""
