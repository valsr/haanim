"""Configuration constants for HAAnim.

This module contains all configuration-related constants including config keys,
default values, and security-related settings.
"""

from typing import Final

# Configuration keys
CONFIG_SCRIPT_PATH: Final = "script_path"
CONFIG_IMPORT_ALLOWLIST: Final = "import_allowlist"
CONFIG_ALLOW_ALL_IMPORTS: Final = "allow_all_imports"

# Default configuration values
DEFAULT_NAME: Final = "HAAnim"
DEFAULT_SCRIPT_PATH: Final = "/config/haanim"
DEFAULT_ALLOW_ALL_IMPORTS: Final = False

# Default import allowlist - safe modules for automation scripts
DEFAULT_IMPORT_ALLOWLIST: Final[list[str]] = [
    "asyncio",
    "datetime",
    "json",
    "logging",
    "math",
    "random",
    "re",
    "time",
    "typing",
    "collections",
    "functools",
    "itertools",
    "operator",
    "statistics",
    "decimal",
    "fractions",
    "enum",
    "dataclasses",
]

# Restricted builtins that should not be available in scripts
RESTRICTED_BUILTINS: Final[set[str]] = {
    "eval",
    "exec",
    "compile",
    "open",
    "input",
    "__import__",
    "breakpoint",
    "memoryview",
    "globals",
    "locals",
    "vars",
    "dir",
    "delattr",
    "setattr",
    "getattr",
}
