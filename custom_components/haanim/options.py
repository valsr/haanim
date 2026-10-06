"""The integration options that set the engine's limits.

See "Integration Options" in the design. The folder and the import options are
read through the ``ConfigManager``; the rescan interval and the six limits here
are handed to the automation manager when it is created.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from custom_components.haanim.const import (
    CONFIG_ACTION_QUEUE_SIZE,
    CONFIG_AUTOMATION_REFRESH_INTERVAL,
    CONFIG_DEFAULT_ACTION_TIMEOUT,
    CONFIG_MAX_CONCURRENT_ACTIONS,
    CONFIG_SHUTDOWN_TIMEOUT,
    CONFIG_STARTUP_TIMEOUT,
    CONFIG_STOP_GRACE_PERIOD,
    DEFAULT_ACTION_QUEUE_SIZE,
    DEFAULT_ACTION_TIMEOUT,
    DEFAULT_AUTOMATION_REFRESH_INTERVAL,
    DEFAULT_MAX_CONCURRENT_ACTIONS,
    DEFAULT_SHUTDOWN_TIMEOUT,
    DEFAULT_STARTUP_TIMEOUT,
    DEFAULT_STOP_GRACE_PERIOD,
)

_COUNT = vol.All(vol.Coerce(int), vol.Range(min=1))
_SECONDS = vol.All(vol.Coerce(float), vol.Range(min=0))
_POSITIVE_SECONDS = vol.All(vol.Coerce(float), vol.Range(min=0, min_included=False))

NUMERIC_OPTIONS: dict[str, tuple[Any, Any]] = {
    CONFIG_AUTOMATION_REFRESH_INTERVAL: (DEFAULT_AUTOMATION_REFRESH_INTERVAL, _COUNT),
    CONFIG_MAX_CONCURRENT_ACTIONS: (DEFAULT_MAX_CONCURRENT_ACTIONS, _COUNT),
    CONFIG_ACTION_QUEUE_SIZE: (DEFAULT_ACTION_QUEUE_SIZE, _COUNT),
    CONFIG_DEFAULT_ACTION_TIMEOUT: (DEFAULT_ACTION_TIMEOUT, _SECONDS),
    CONFIG_STARTUP_TIMEOUT: (DEFAULT_STARTUP_TIMEOUT, _POSITIVE_SECONDS),
    CONFIG_SHUTDOWN_TIMEOUT: (DEFAULT_SHUTDOWN_TIMEOUT, _POSITIVE_SECONDS),
    CONFIG_STOP_GRACE_PERIOD: (DEFAULT_STOP_GRACE_PERIOD, _SECONDS),
}
"""The numeric options: default and validator by key, in the order of the design's table."""


@dataclass(frozen=True)
class EngineOptions:
    """The limits of the engine. The defaults are the design's.

    Args:
        rescan_interval: Seconds between scans of the automations folder.
        concurrency_limit: Maximum number of actions executing at once.
        action_queue_size: Maximum queued requests per ``QUEUE`` action.
        default_action_timeout: Timeout in seconds of actions that do not set one; 0 for none.
        startup_timeout: Time limit in seconds for ``@startup``.
        shutdown_timeout: Time limit in seconds for ``@shutdown``.
        stop_grace_period: Seconds running actions get to finish before they are cancelled.
    """

    rescan_interval: int = DEFAULT_AUTOMATION_REFRESH_INTERVAL
    concurrency_limit: int = DEFAULT_MAX_CONCURRENT_ACTIONS
    action_queue_size: int = DEFAULT_ACTION_QUEUE_SIZE
    default_action_timeout: float = DEFAULT_ACTION_TIMEOUT
    startup_timeout: float = DEFAULT_STARTUP_TIMEOUT
    shutdown_timeout: float = DEFAULT_SHUTDOWN_TIMEOUT
    stop_grace_period: float = DEFAULT_STOP_GRACE_PERIOD


def numeric_option(values: Mapping[str, Any], key: str) -> Any:
    """Return a numeric option from stored values, or its default if it is missing or not valid."""
    default, validator = NUMERIC_OPTIONS[key]
    try:
        return validator(values.get(key, default))
    except vol.Invalid:
        return default


def engine_options(values: Mapping[str, Any]) -> EngineOptions:
    """Build the engine's limits from the stored options of the config entry."""
    return EngineOptions(
        rescan_interval=numeric_option(values, CONFIG_AUTOMATION_REFRESH_INTERVAL),
        concurrency_limit=numeric_option(values, CONFIG_MAX_CONCURRENT_ACTIONS),
        action_queue_size=numeric_option(values, CONFIG_ACTION_QUEUE_SIZE),
        default_action_timeout=numeric_option(values, CONFIG_DEFAULT_ACTION_TIMEOUT),
        startup_timeout=numeric_option(values, CONFIG_STARTUP_TIMEOUT),
        shutdown_timeout=numeric_option(values, CONFIG_SHUTDOWN_TIMEOUT),
        stop_grace_period=numeric_option(values, CONFIG_STOP_GRACE_PERIOD),
    )
