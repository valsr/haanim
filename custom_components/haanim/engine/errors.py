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
