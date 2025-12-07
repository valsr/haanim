"""Script manager for HAAnim.

This module handles loading, watching, and managing multiple script contexts.
It provides the central coordination point for all script lifecycle operations.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant

from custom_components.haanim.config import ConfigManager, get_config_manager

from custom_components.haanim.const import (
    DEFAULT_MAX_CONCURRENT_ACTIONS,
    DEFAULT_SHUTDOWN_TIMEOUT,
    DOMAIN,
    EVENT_SCRIPT_ERROR,
    EVENT_SCRIPT_LOADED,
    EVENT_SCRIPT_UNLOADED,
)
from custom_components.haanim.engine.action_pool import ActionWorkerPool
from custom_components.haanim.engine.script_context import ActionDefinition, ScriptContext, ScriptMetadata
from custom_components.haanim.engine.script_status import ScriptStatus, get_status_manager
from custom_components.haanim.engine import ScriptError
from custom_components.haanim.engine.errors import (
    ActionBusyError,
    ActionCancelledError,
    PoolExhaustedError,
    ShutdownTimeoutError,
)

_LOGGER = logging.getLogger(__name__)


class ScriptManager:
    """Manages loading, watching, and lifecycle of HAAnim scripts.

    This is the central manager for all script operations. It handles:
    - Loading scripts from the configured folder
    - Watching for file changes and hot-reloading
    - Providing access to script contexts and their actions
    - Coordinating trigger registration
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the script manager.

        Args:
            hass: Home Assistant instance.
            entry: The config entry for this integration.
        """
        self.hass = hass
        self.entry = entry

        # Get configuration
        self._config: ConfigManager = get_config_manager()
        self._script_path = self._config.get_script_path()
        self._import_allowlist = self._config.get_import_allowlist()
        self._allow_all_imports = self._config.get_allow_all_imports()

        # Script storage
        self._contexts: dict[str, ScriptContext] = {}
        self._failed_scripts: dict[str, str] = {}  # path -> error message

        # File watcher
        self._watcher_task: asyncio.Task[Any] | None = None
        self._file_mtimes: dict[str, float] = {}

        # Action worker pool for concurrent execution
        self._action_pool = ActionWorkerPool(
            max_workers=DEFAULT_MAX_CONCURRENT_ACTIONS,
            shutdown_timeout=DEFAULT_SHUTDOWN_TIMEOUT,
        )

        # State
        self._started = False
        self._stop_event = asyncio.Event()

    async def async_setup(self) -> None:
        """Set up the script manager.

        This should be called during integration setup.
        """
        # Ensure script folder exists
        folder = Path(self._script_path)
        if not folder.exists():
            _LOGGER.info("Creating script folder: %s", folder)
            folder.mkdir(parents=True, exist_ok=True)

        # Register for HA lifecycle events
        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._on_ha_started)
        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._on_ha_stop)

        _LOGGER.info(
            "Script manager initialized. Script folder: %s, Allow all imports: %s",
            folder,
            self._allow_all_imports,
        )

    async def _on_ha_started(self, _: Event) -> None:
        """Handle Home Assistant started event.

        Args:
            event: The started event.
        """
        self._started = True

        # Load all scripts
        await self.async_load_all_scripts()

        # Run startup actions for all loaded scripts
        await self._run_all_startup_actions()

        # Start file watcher
        self._watcher_task = self.hass.async_create_task(
            self._watch_scripts(),
            name="haanim_script_watcher",
        )

        _LOGGER.info("Script manager started")

    async def _on_ha_stop(self, _: Event) -> None:
        """Handle Home Assistant stop event.

        Args:
            event: The stop event.
        """
        self._stop_event.set()

        # Cancel watcher
        if self._watcher_task:
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass

        # Run shutdown actions for all scripts (with timeout handling)
        await self._run_all_shutdown_actions()

        # Shutdown the worker pool
        await self._action_pool.shutdown()

        # Unload all scripts
        await self.async_unload_all_scripts()

        _LOGGER.info("Script manager stopped")

    async def async_load_all_scripts(self) -> dict[str, ScriptMetadata | str]:
        """Load all Python scripts from the script folder.

        Returns:
            Dictionary mapping script paths to their metadata or error message.
        """
        folder = Path(self._script_path)
        results: dict[str, ScriptMetadata | str] = {}

        if not folder.exists():
            _LOGGER.warning("Script folder does not exist: %s", folder)
            return results

        # Find all .py files
        for script_path in folder.glob("*.py"):
            # Skip files starting with underscore
            if script_path.name.startswith("_"):
                continue

            try:
                metadata = await self.async_load_script(str(script_path))
                results[str(script_path)] = metadata
            except ScriptError as err:
                results[str(script_path)] = str(err)
                _LOGGER.error("Failed to load script %s: %s", script_path.name, err)
            except Exception as err:  # pylint: disable=broad-exception-caught
                # Catch any unexpected errors that aren't ScriptError
                results[str(script_path)] = str(err)
                _LOGGER.exception("Unexpected error loading script %s: %s", script_path.name, err)

        _LOGGER.info(
            "Loaded %d scripts (%d failed)",
            len([r for r in results.values() if isinstance(r, ScriptMetadata)]),
            len([r for r in results.values() if isinstance(r, str)]),
        )

        return results

    async def async_load_script(self, script_path: str) -> ScriptMetadata:
        """Load a single script.

        Args:
            script_path: Path to the script file.

        Returns:
            ScriptMetadata for the loaded script.

        Raises:
            ScriptError: If loading fails.
        """
        # Unload if already loaded
        if script_path in self._contexts:
            await self.async_unload_script(script_path)

        # Create context
        context = ScriptContext(
            hass=self.hass,
            script_path=script_path,
            import_allowlist=self._import_allowlist,
            allow_all_imports=self._allow_all_imports,
        )

        try:
            # Load the script
            metadata = await context.load()

            # Store context
            self._contexts[script_path] = context

            # Record file mtime for hot reload
            self._file_mtimes[script_path] = Path(script_path).stat().st_mtime

            # Remove from failed scripts if present
            self._failed_scripts.pop(script_path, None)

            # Fire loaded event
            self.hass.bus.async_fire(
                EVENT_SCRIPT_LOADED,
                {
                    "script_path": script_path,
                    "script_name": metadata.name,
                    "actions": [a.name for a in metadata.actions],
                    "triggers": len(metadata.triggers),
                    "has_startup": metadata.has_startup,
                    "has_shutdown": metadata.has_shutdown,
                },
            )

            # Run startup action if HA has already started (hot reload scenario)
            if self._started:
                await self._run_script_startup_action(context)

            return metadata

        except ScriptError as err:
            # Track failed script
            self._failed_scripts[script_path] = str(err)

            # Log the error with traceback for debugging
            _LOGGER.exception("Script loading error for %s", script_path)

            # Fire error event
            self.hass.bus.async_fire(
                EVENT_SCRIPT_ERROR,
                {
                    "script_path": script_path,
                    "error": str(err),
                },
            )

            raise

    async def async_unload_script(self, script_path: str) -> bool:
        """Unload a script.

        This will run the script's shutdown action (if defined) before unloading.
        If an action is currently running for this script, it will be cancelled.

        Args:
            script_path: Path to the script file.

        Returns:
            True if the script was unloaded.
        """
        if script_path not in self._contexts:
            return False

        context = self._contexts.get(script_path)
        if context:
            # Run shutdown action before unloading
            await self._run_script_shutdown_action(context)

        context = self._contexts.pop(script_path)
        self._file_mtimes.pop(script_path, None)

        # Fire unloaded event
        self.hass.bus.async_fire(
            EVENT_SCRIPT_UNLOADED,
            {
                "script_path": script_path,
                "script_name": context.name,
            },
        )

        _LOGGER.info("Unloaded script: %s", context.name)
        return True

    async def async_unload_all_scripts(self) -> None:
        """Unload all loaded scripts."""
        paths = list(self._contexts.keys())
        for path in paths:
            await self.async_unload_script(path)

    async def async_reload_script(self, script_path: str) -> ScriptMetadata:
        """Reload a script.

        Args:
            script_path: Path to the script file.

        Returns:
            ScriptMetadata for the reloaded script.
        """
        _LOGGER.info("Reloading script: %s", script_path)
        return await self.async_load_script(script_path)

    async def async_reload_all_scripts(self) -> dict[str, ScriptMetadata | str]:
        """Reload all scripts.

        Returns:
            Dictionary mapping script paths to their metadata or error message.
        """
        await self.async_unload_all_scripts()
        return await self.async_load_all_scripts()

    async def _watch_scripts(self) -> None:
        """Watch the script folder for changes and hot-reload scripts."""
        folder = Path(self._script_path)

        while not self._stop_event.is_set():
            try:
                # Check for changes every 5 seconds
                await asyncio.sleep(self._config.get_script_refresh_interval())

                if not folder.exists():
                    continue

                # Get current files
                current_files = {str(p) for p in folder.glob("*.py") if not p.name.startswith("_")}

                # Check for new files
                for script_path in current_files:
                    if script_path not in self._contexts and script_path not in self._failed_scripts:
                        _LOGGER.info("New script detected: %s", script_path)
                        try:
                            await self.async_load_script(script_path)
                        except ScriptError:
                            pass  # Error already logged

                # Check for removed files
                for script_path in list(self._contexts.keys()):
                    if script_path not in current_files:
                        _LOGGER.info("Script removed: %s", script_path)
                        await self.async_unload_script(script_path)

                # Check for modified files
                for script_path in list(self._contexts.keys()):
                    try:
                        current_mtime = Path(script_path).stat().st_mtime
                        if current_mtime > self._file_mtimes.get(script_path, 0):
                            _LOGGER.info("Script modified: %s", script_path)
                            try:
                                await self.async_reload_script(script_path)
                            except ScriptError:
                                pass  # Error already logged
                    except OSError:
                        # File may have been deleted
                        pass

                # Retry failed scripts
                for script_path in list(self._failed_scripts.keys()):
                    if script_path in current_files:
                        try:
                            current_mtime = Path(script_path).stat().st_mtime
                            if current_mtime > self._file_mtimes.get(script_path, 0):
                                _LOGGER.info("Retrying failed script: %s", script_path)
                                try:
                                    await self.async_load_script(script_path)
                                except ScriptError:
                                    pass
                        except OSError:
                            pass

            except asyncio.CancelledError:
                break
            except Exception as err:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Error in script watcher: %s", err)

    def get_context(self, script_path: str) -> ScriptContext | None:
        """Get a script context by path.

        Args:
            script_path: Path to the script file.

        Returns:
            The ScriptContext, or None if not loaded.
        """
        return self._contexts.get(script_path)

    def get_context_by_name(self, script_name: str) -> ScriptContext | None:
        """Get a script context by script name.

        Args:
            script_name: Name of the script (without .py extension).

        Returns:
            The ScriptContext, or None if not found.
        """
        for context in self._contexts.values():
            if context.script_name == script_name or context.name == script_name:
                return context
        return None

    def get_all_contexts(self) -> list[ScriptContext]:
        """Get all loaded script contexts.

        Returns:
            List of all ScriptContext instances.
        """
        return list(self._contexts.values())

    def get_all_actions(self) -> list[ActionDefinition]:
        """Get all actions from all loaded scripts.

        Returns:
            List of all action definitions.
        """
        actions: list[ActionDefinition] = []
        for context in self._contexts.values():
            actions.extend(context.get_actions())
        return actions

    def get_all_metadata(self) -> list[ScriptMetadata]:
        """Get metadata for all loaded scripts.

        Returns:
            List of ScriptMetadata for all loaded scripts.
        """
        return [metadata for ctx in self._contexts.values() if (metadata := ctx.get_metadata()) is not None]

    def get_failed_scripts(self) -> dict[str, str]:
        """Get information about failed scripts.

        Returns:
            Dictionary mapping script paths to error messages.
        """
        return self._failed_scripts.copy()

    async def async_run_action(
        self,
        script_name: str,
        action_name: str,
        *args: Any,
        manual: bool = True,
        **kwargs: Any,
    ) -> Any:
        """Run an action by script and action name.

        This method uses the action worker pool to manage concurrent execution.
        Only one action per script can run at a time, and the total number of
        concurrent actions across all scripts is limited.

        Args:
            script_name: Name of the script.
            action_name: Name of the action.
            *args: Positional arguments for the action.
            manual: If True, this is a manual execution.
            **kwargs: Keyword arguments for the action.

        Returns:
            The return value of the action.

        Raises:
            ScriptError: If script or action not found.
            ActionBusyError: If the script is already executing an action.
            PoolExhaustedError: If no workers are available.
        """
        context = self.get_context_by_name(script_name)
        if not context:
            raise ScriptError(f"Script '{script_name}' not found")

        # Get the action from the context
        actions = {a.name: a for a in context.get_actions()}
        if action_name not in actions:
            # Also try by function name
            actions_by_func = {a.func_name: a for a in context.get_actions()}
            if action_name not in actions_by_func:
                raise ScriptError(f"Action '{action_name}' not found in script '{script_name}'")
            action = actions_by_func[action_name]
        else:
            action = actions[action_name]

        # Add manual flag to kwargs
        kwargs["manual"] = manual

        # Submit to the worker pool with queue/preempt settings from action definition
        return await self._action_pool.submit_action(
            script_name=context.script_name,
            action_name=action_name,
            func=action.func,
            *args,
            queue=action.queue,
            queue_timeout=action.queue_timeout,
            preempt=action.preempt,
            **kwargs,
        )

    async def _run_all_startup_actions(self) -> None:
        """Run startup actions for all loaded scripts.

        This is called after all scripts have been loaded. Each script's
        @startup decorated function (if any) is executed through the worker pool.
        """
        startup_count = 0
        error_count = 0

        for context in self._contexts.values():
            startup_func = context.get_startup_func()
            if startup_func is None:
                continue

            try:
                _LOGGER.debug("Running startup action for script '%s'", context.script_name)
                await self._action_pool.run_startup_action(
                    script_name=context.script_name,
                    startup_func=startup_func,
                )
                startup_count += 1
            except (ActionBusyError, PoolExhaustedError) as err:
                _LOGGER.error(
                    "Failed to run startup action for script '%s': %s",
                    context.script_name,
                    err,
                )
                error_count += 1
            except ActionCancelledError:
                _LOGGER.warning(
                    "Startup action for script '%s' was cancelled",
                    context.script_name,
                )
                error_count += 1
            except Exception as err:
                _LOGGER.exception(
                    "Error in startup action for script '%s': %s",
                    context.script_name,
                    err,
                )
                error_count += 1

        _LOGGER.info(
            "Startup actions completed: %d successful, %d failed",
            startup_count,
            error_count,
        )

    async def _run_all_shutdown_actions(self) -> None:
        """Run shutdown actions for all loaded scripts.

        This is called when Home Assistant is stopping. Each script's
        @shutdown decorated function (if any) is executed with a timeout.
        If the shutdown action exceeds the timeout, it is forcefully terminated.
        """
        shutdown_count = 0
        error_count = 0

        for context in self._contexts.values():
            shutdown_func = context.get_shutdown_func()
            if shutdown_func is None:
                continue

            try:
                _LOGGER.debug("Running shutdown action for script '%s'", context.script_name)
                await self._action_pool.run_shutdown_action(
                    script_name=context.script_name,
                    shutdown_func=shutdown_func,
                )
                shutdown_count += 1
            except ShutdownTimeoutError as err:
                _LOGGER.error(
                    "Shutdown action for script '%s' timed out: %s",
                    context.script_name,
                    err,
                )
                error_count += 1
            except ActionCancelledError:
                _LOGGER.warning(
                    "Shutdown action for script '%s' was cancelled",
                    context.script_name,
                )
                error_count += 1
            except Exception as err:  # pylint: disable=broad-exception-caught
                _LOGGER.exception(
                    "Error in shutdown action for script '%s': %s",
                    context.script_name,
                    err,
                )
                error_count += 1

        _LOGGER.info(
            "Shutdown actions completed: %d successful, %d failed",
            shutdown_count,
            error_count,
        )

    async def _run_script_shutdown_action(self, context: ScriptContext) -> None:
        """Run the shutdown action for a single script.

        This is called when a script is being unloaded or reloaded.

        Args:
            context: The script context to shut down.
        """
        shutdown_func = context.get_shutdown_func()
        if shutdown_func is None:
            return

        try:
            _LOGGER.debug("Running shutdown action for script '%s'", context.script_name)
            await self._action_pool.run_shutdown_action(
                script_name=context.script_name,
                shutdown_func=shutdown_func,
            )
        except ShutdownTimeoutError as err:
            _LOGGER.error(
                "Shutdown action for script '%s' timed out: %s",
                context.script_name,
                err,
            )
        except ActionCancelledError:
            _LOGGER.warning(
                "Shutdown action for script '%s' was cancelled",
                context.script_name,
            )
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOGGER.exception(
                "Error in shutdown action for script '%s': %s",
                context.script_name,
                err,
            )

    async def _run_script_startup_action(self, context: ScriptContext) -> None:
        """Run the startup action for a single script.

        This is called when a new script is loaded (e.g., during hot reload).

        Args:
            context: The script context to start up.
        """
        startup_func = context.get_startup_func()
        if startup_func is None:
            return

        try:
            _LOGGER.debug("Running startup action for script '%s'", context.script_name)
            await self._action_pool.run_startup_action(
                script_name=context.script_name,
                startup_func=startup_func,
            )
        except (ActionBusyError, PoolExhaustedError) as err:
            _LOGGER.error(
                "Failed to run startup action for script '%s': %s",
                context.script_name,
                err,
            )
        except ActionCancelledError:
            _LOGGER.warning(
                "Startup action for script '%s' was cancelled",
                context.script_name,
            )
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOGGER.exception(
                "Error in startup action for script '%s': %s",
                context.script_name,
                err,
            )

    @property
    def action_pool(self) -> ActionWorkerPool:
        """Get the action worker pool.

        Returns:
            The ActionWorkerPool instance.
        """
        return self._action_pool

    def get_script_status(self, script_name: str) -> ScriptStatus:
        """Get the current status of a script.

        Args:
            script_name: Name of the script.

        Returns:
            The ScriptStatus for the script.
        """
        return get_status_manager().get_status(script_name)

    def get_all_script_statuses(self) -> dict[str, ScriptStatus]:
        """Get the current status of all scripts.

        Returns:
            Dictionary mapping script names to their statuses.
        """
        return get_status_manager().get_all_statuses()

    def get_script_status_display(self, script_name: str) -> str:
        """Get the display status string for a script.

        Args:
            script_name: Name of the script.

        Returns:
            Formatted status string for UI display.
        """
        return get_status_manager().get_status(script_name).get_display_status()


async def async_get_manager(hass: HomeAssistant) -> ScriptManager | None:
    """Get the script manager instance.

    Args:
        hass: Home Assistant instance.

    Returns:
        The ScriptManager instance, or None if not set up.
    """
    if DOMAIN not in hass.data:
        return None

    data = hass.data[DOMAIN]
    for entry_data in data.values():
        if isinstance(entry_data, dict) and "manager" in entry_data:
            manager = entry_data["manager"]  # type: ignore
            if isinstance(manager, ScriptManager):
                return manager
            return None

    return None
