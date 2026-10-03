"""Automation manager for HAAnim.

This module handles loading, watching, and managing multiple automation contexts.
It provides the central coordination point for all automation lifecycle operations.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant

from custom_components.haanim.config import ConfigManager, get_config_manager

from custom_components.haanim.const import (
    DEFAULT_MAX_CONCURRENT_ACTIONS,
    DEFAULT_WORKER_SHUTDOWN_TIMEOUT,
    DOMAIN,
    EVENT_AUTOMATION_ERROR,
    EVENT_AUTOMATION_LOADED,
    EVENT_AUTOMATION_UNLOADED,
)
from haanim.engine.action_pool import ActionWorkerPool
from haanim.engine.automation_context import (
    ActionDefinition,
    AutomationContext,
    AutomationMetadata,
)
from haanim.engine.automation_status import AutomationStatus, AutomationStatusManager
from haanim.engine.automation_ids import RejectedFolder
from haanim.engine.discovery import DiscoveredAutomation, FolderIssues, discover
from haanim.engine.hot_reload import HotReloader
from haanim.interfaces import Host
from haanim.engine.callables import accepted_kwargs
from haanim.engine.control import AutomationControl, EnabledFlags
from haanim.engine.errors import (
    AutomationNotRunningError,
    HAAnimError,
    NonExistingAutomationError,
)
from haanim.engine.lifecycle import (
    Automation,
    AutomationState,
    NoTriggers,
    TriggerRegistrar,
    start_all,
    stop_all,
)

_LOGGER = logging.getLogger(__name__)


class AutomationManager:
    """Manages loading, watching, and lifecycle of HAAnim automations.

    This is the central manager for all automation operations. It handles:
    - Loading automations from the configured folder
    - Watching for file changes and hot-reloading
    - Providing access to automation contexts and their actions
    - Coordinating trigger registration
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        host: Host,
    ) -> None:
        """Initialize the automation manager.

        Args:
            hass: Home Assistant instance.
            entry: The config entry for this integration.
            host: The host interfaces the engine uses to reach Home Assistant.
        """
        self.hass = hass
        self.entry = entry
        self.host = host
        self._status_manager = AutomationStatusManager()
        self._storage_path = hass.config.path(".storage", "haanim", "automations")

        # Get configuration
        self._config: ConfigManager = get_config_manager()
        self._automation_path = self._config.get_automation_path()
        self._import_allowlist = self._config.get_import_allowlist()
        self._allow_all_imports = self._config.get_allow_all_imports()

        # Automation storage, both keyed by the path of the automation's folder
        self._contexts: dict[str, AutomationContext] = {}
        self._automations: dict[str, Automation] = {}
        self._triggers: TriggerRegistrar = NoTriggers()

        # The persistent enabled flags and the control operations
        self._flags = EnabledFlags(host.storage)
        self._flags_loaded = False
        self._failed_automations: dict[str, str] = {}  # path -> error message

        # Hot reload
        self._watcher_task: asyncio.Task[Any] | None = None
        self._reloader = HotReloader(
            host.files,
            Path(self._automation_path),
            host.clock,
            self,
            interval=self._config.get_automation_refresh_interval(),
        )

        # Folders that are not loaded because of their name, kept in step with repair issues
        self._folder_issues = FolderIssues(host.issues)
        self._automation_ids: dict[str, str] = {}  # folder path -> automation ID

        # Action worker pool for concurrent execution
        self._action_pool = ActionWorkerPool(
            status_manager=self._status_manager,
            clock=host.clock,
            max_workers=DEFAULT_MAX_CONCURRENT_ACTIONS,
            shutdown_timeout=DEFAULT_WORKER_SHUTDOWN_TIMEOUT,
        )

        self._control = AutomationControl(self._flags, self._action_pool)

        # State
        self._started = False

    async def async_setup(self) -> None:
        """Set up the automation manager.

        This should be called during integration setup.
        """
        # Ensure automation folder exists
        folder = Path(self._automation_path)
        if not folder.exists():
            _LOGGER.info("Creating automation folder: %s", folder)
            folder.mkdir(parents=True, exist_ok=True)

        # Register for HA lifecycle events
        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._on_ha_started)
        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._on_ha_stop)

        _LOGGER.info(
            "Automation manager initialized. Automation folder: %s, Allow all imports: %s",
            folder,
            self._allow_all_imports,
        )

    async def _on_ha_started(self, _: Event) -> None:
        """Handle Home Assistant started event.

        Args:
            event: The started event.
        """
        # Load all automations, then start them one at a time in ascending ID order
        await self.async_load_all_automations()
        await start_all(self._automations.values(), self._control.is_enabled)
        self._started = True

        # Start hot reloading from the files as they are now
        await self._reloader.prime()
        self._watcher_task = self.hass.async_create_task(
            self._reloader.run(),
            name="haanim_automation_watcher",
        )

        _LOGGER.info("Automation manager started")

    async def _on_ha_stop(self, _: Event) -> None:
        """Handle Home Assistant stop event.

        Args:
            event: The stop event.
        """
        # Cancel watcher
        if self._watcher_task:
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass

        # Stop all automations, one at a time in descending ID order
        await stop_all(self._automations.values())

        # Shutdown the worker pool
        await self._action_pool.shutdown()

        # Unload all automations
        await self.async_unload_all_automations()

        _LOGGER.info("Automation manager stopped")

    async def _discover(self) -> list[DiscoveredAutomation]:
        """Scan the automation folder and report the folders that cannot be loaded.

        Returns:
            The automations to load, in ascending order of automation ID.
        """
        discovery = await discover(self.host.files, Path(self._automation_path))
        self.report_rejected(discovery.rejected)
        for rejected in discovery.rejected:
            _LOGGER.warning(
                "Automation folder '%s' is not loaded: %s",
                rejected.folder,
                (
                    f"its ID '{rejected.automation_id}' is taken by folder '{rejected.winner}'"
                    if rejected.winner
                    else "its name gives no automation ID"
                ),
            )
        self._automation_ids = {str(found.folder): found.automation_id for found in discovery.automations}
        return discovery.automations

    async def async_load_all_automations(self) -> dict[str, AutomationMetadata | str]:
        """Load every automation in the automation folder.

        An automation is a folder that contains a ``main.py``. They are loaded
        in ascending order of automation ID.

        Returns:
            Dictionary mapping automation folder paths to their metadata or error message.
        """
        results: dict[str, AutomationMetadata | str] = {}
        await self._load_flags()

        for found in await self._discover():
            automation_path = str(found.folder)
            try:
                results[automation_path] = await self.async_load_automation(automation_path)
            except HAAnimError as err:
                results[automation_path] = str(err)
                _LOGGER.error("Failed to load automation %s: %s", found.automation_id, err)
            except Exception as err:  # pylint: disable=broad-exception-caught
                # Catch any unexpected errors that aren't HAAnimError
                results[automation_path] = str(err)
                _LOGGER.exception("Unexpected error loading automation %s: %s", found.automation_id, err)

        _LOGGER.info(
            "Loaded %d automations (%d failed)",
            len([r for r in results.values() if isinstance(r, AutomationMetadata)]),
            len([r for r in results.values() if isinstance(r, str)]),
        )

        return results

    async def async_load_automation(self, automation_path: str) -> AutomationMetadata:
        """Load a single automation, and start it if Home Assistant has started.

        Loading checks the automation's files; none of its code runs until it
        is started.

        Args:
            automation_path: Path of the automation's folder.

        Returns:
            AutomationMetadata for the loaded automation.

        Raises:
            HAAnimError: If loading fails.
        """
        # Stop and unload if already loaded
        if automation_path in self._automations:
            await self.async_unload_automation(automation_path)

        context = AutomationContext(
            host=self.host,
            automation_path=automation_path,
            automation_id=self._automation_ids.get(automation_path),
            status_manager=self._status_manager,
            storage_path=self._storage_path,
            registry=self,
            additional_imports=self._import_allowlist,
            allow_all_imports=self._allow_all_imports,
        )
        automation = Automation(context, pool=self._action_pool, triggers=self._triggers)

        # Kept also when loading fails: the automation is then in the error state
        self._automations[automation_path] = automation

        if not await automation.load():
            message = automation.message or "unknown error"
            self._failed_automations[automation_path] = message
            self.hass.bus.async_fire(
                EVENT_AUTOMATION_ERROR,
                {
                    "automation_path": automation_path,
                    "error": message,
                },
            )
            raise HAAnimError(message)

        self._contexts[automation_path] = context
        self._failed_automations.pop(automation_path, None)
        metadata = context.get_metadata()
        assert metadata is not None

        # Start it right away if Home Assistant has already started (hot reload), unless it is disabled
        await self._load_flags()
        if self._started and self._control.is_enabled(automation.automation_id):
            await automation.start()

        self.hass.bus.async_fire(
            EVENT_AUTOMATION_LOADED,
            {
                "automation_path": automation_path,
                "automation_id": metadata.id,
                "state": automation.state.value,
                "enabled": self._control.is_enabled(automation.automation_id),
                "actions": [a.name for a in metadata.actions],
                "triggers": len(metadata.triggers),
                "has_startup": metadata.has_startup,
                "has_shutdown": metadata.has_shutdown,
            },
        )

        return metadata

    async def async_unload_automation(self, automation_path: str) -> bool:
        """Stop and unload an automation.

        A running automation is stopped first: its triggers are unregistered,
        running actions get the grace period and are then cancelled, and its
        ``@shutdown`` handler runs.

        Args:
            automation_path: Path of the automation's folder.

        Returns:
            True if the automation was unloaded.
        """
        automation = self._automations.pop(automation_path, None)
        if automation is None:
            return False

        self._contexts.pop(automation_path, None)
        self._failed_automations.pop(automation_path, None)
        automation_id = automation.automation_id
        await automation.unload()

        # Fire unloaded event
        self.hass.bus.async_fire(
            EVENT_AUTOMATION_UNLOADED,
            {
                "automation_path": automation_path,
                "automation_id": automation_id,
            },
        )

        _LOGGER.info("Unloaded automation: %s", automation_id)
        return True

    async def async_unload_all_automations(self) -> None:
        """Stop and unload all automations, one at a time in descending order of automation ID."""
        by_id = sorted(self._automations.items(), key=lambda item: item[1].automation_id, reverse=True)
        for path, _ in by_id:
            await self.async_unload_automation(path)

    async def async_reload_automation(self, automation_path: str) -> AutomationMetadata:
        """Reload an automation.

        Args:
            automation_path: Path to the automation file.

        Returns:
            AutomationMetadata for the reloaded automation.
        """
        _LOGGER.info("Reloading automation: %s", automation_path)
        return await self.async_load_automation(automation_path)

    async def async_reload_all_automations(self) -> dict[str, AutomationMetadata | str]:
        """Reload all automations.

        Returns:
            Dictionary mapping automation paths to their metadata or error message.
        """
        await self.async_unload_all_automations()
        return await self.async_load_all_automations()

    # --- ReloadTarget: what the hot reloader keeps in step with the files ----------

    def folders(self) -> list[Path]:
        """Return the folder of every automation that is loaded or failed to load."""
        return [Path(path) for path in self._automations]

    async def reload(self, found: DiscoveredAutomation) -> None:
        """Stop, unload, load and start an automation whose files changed, or load a new one."""
        automation_path = str(found.folder)
        self._automation_ids[automation_path] = found.automation_id
        try:
            await self.async_load_automation(automation_path)
        except HAAnimError:
            pass  # The automation is in the error state and its message says why

    async def remove(self, folder: Path) -> None:
        """Stop and unload the automation of a folder that is gone."""
        automation_path = str(folder)
        await self.async_unload_automation(automation_path)
        self._automation_ids.pop(automation_path, None)

    def report_rejected(self, rejected: Sequence[RejectedFolder]) -> None:
        """Raise and clear the repair issues of folders that are not loaded because of their name."""
        self._folder_issues.update(list(rejected))

    def get_context(self, automation_path: str) -> AutomationContext | None:
        """Get an automation context by path.

        Args:
            automation_path: Path to the automation file.

        Returns:
            The AutomationContext, or None if not loaded.
        """
        return self._contexts.get(automation_path)

    def get_context_by_name(self, automation_id: str) -> AutomationContext | None:
        """Get an automation context by automation name.

        Args:
            automation_id: Name of the automation (without .py extension).

        Returns:
            The AutomationContext, or None if not found.
        """
        for context in self._contexts.values():
            if context.automation_id == automation_id:
                return context
        return None

    def get_all_contexts(self) -> list[AutomationContext]:
        """Get all loaded automation contexts.

        Returns:
            List of all AutomationContext instances.
        """
        return list(self._contexts.values())

    def get_all_actions(self) -> list[ActionDefinition]:
        """Get all actions from all loaded automations.

        Returns:
            List of all action definitions.
        """
        actions: list[ActionDefinition] = []
        for context in self._contexts.values():
            actions.extend(context.get_actions())
        return actions

    def get_all_metadata(self) -> list[AutomationMetadata]:
        """Get metadata for all loaded automations.

        Returns:
            List of AutomationMetadata for all loaded automations.
        """
        return [metadata for ctx in self._contexts.values() if (metadata := ctx.get_metadata()) is not None]

    def get_failed_automations(self) -> dict[str, str]:
        """Get information about failed automations.

        Returns:
            Dictionary mapping automation paths to error messages.
        """
        return self._failed_automations.copy()

    async def async_run_action(
        self,
        automation_id: str,
        action_name: str,
        *args: Any,
        manual: bool = True,
        **kwargs: Any,
    ) -> Any:
        """Run an action by automation and action name.

        This method uses the action worker pool to manage concurrent execution.
        Multiple actions from the same automation can run concurrently, limited only
        by the global worker pool size.

        Args:
            automation_id: Name of the automation.
            action_name: Name of the action.
            *args: Positional arguments for the action.
            manual: If True, this is a manual execution.
            **kwargs: Keyword arguments for the action.

        Returns:
            The return value of the action.

        Raises:
            HAAnimError: If automation or action not found.
            PoolExhaustedError: If no workers are available.
        """
        context = self.get_context_by_name(automation_id)
        if not context:
            raise HAAnimError(f"Automation '{automation_id}' not found")

        if not self._automation(context.automation_id).accepts_calls():
            raise AutomationNotRunningError(context.automation_id)

        # A disabled action is listed but cannot be run
        action = context.get_action(action_name)
        if action is None or action.disabled:
            raise HAAnimError(f"Action '{action_name}' not found in automation '{automation_id}'")

        # Offer the manual flag to actions that declare it
        kwargs.update(accepted_kwargs(action.func, {"manual": manual}))

        # Submit to the worker pool
        return await self._action_pool.submit_action(
            automation_id=context.automation_id,
            action_name=action_name,
            func=action.func,
            *args,
            **kwargs,
        )

    def _automation(self, automation_id: str) -> Automation:
        """Return the automation with an ID.

        Raises:
            NonExistingAutomationError: If no such automation is loaded.
        """
        for automation in self._automations.values():
            if automation.automation_id == automation_id:
                return automation
        raise NonExistingAutomationError(automation_id)

    def get_automation_state(self, automation_id: str) -> AutomationState:
        """Return the lifecycle state of an automation.

        An automation that is not loaded is ``unavailable``.
        """
        try:
            return self._automation(automation_id).state
        except NonExistingAutomationError:
            return AutomationState.UNAVAILABLE

    def set_trigger_registrar(self, triggers: TriggerRegistrar) -> None:
        """Set where the triggers of started automations are registered.

        Args:
            triggers: The trigger manager.
        """
        self._triggers = triggers

    async def async_call_action(
        self,
        automation_id: str,
        action_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Call an automation action.

        Args:
            automation_id: Automation identifier.
            action_name: Name of the action to call.
            args: Positional arguments for the action.
            kwargs: Keyword arguments for the action.

        Returns:
            Action return value.

        Raises:
            NonExistingAutomationError: If automation not found.
            AutomationNotRunningError: If the automation is not running.
            ActionNotFoundError: If action not found.
        """
        return await self._automation(automation_id).call_action(action_name, *args, **kwargs)

    async def async_enable_automation(self, automation_id: str) -> None:
        """Mark an automation enabled and start it. Does nothing if it is enabled.

        Args:
            automation_id: Automation identifier.

        Raises:
            NonExistingAutomationError: If automation not found.
        """
        await self._load_flags()
        await self._control.enable(self._automation(automation_id))
        _LOGGER.info("Enabled automation: %s", automation_id)

    async def async_disable_automation(self, automation_id: str) -> None:
        """Stop an automation and mark it disabled. Does nothing if it is disabled.

        Args:
            automation_id: Automation identifier.

        Raises:
            NonExistingAutomationError: If automation not found.
        """
        await self._load_flags()
        await self._control.disable(self._automation(automation_id))
        _LOGGER.info("Disabled automation: %s", automation_id)

    async def async_start_automation(self, automation_id: str) -> None:
        """Start an automation. Does not change the enabled flag.

        Args:
            automation_id: Automation identifier.

        Raises:
            NonExistingAutomationError: If automation not found.
            AutomationDisabledError: If the automation is disabled.
            AutomationAlreadyRunningError: If the automation is running.
        """
        await self._load_flags()
        await self._control.start(self._automation(automation_id))
        _LOGGER.info("Started automation: %s", automation_id)

    async def async_stop_automation(self, automation_id: str) -> None:
        """Stop an automation. Does not change the enabled flag.

        Args:
            automation_id: Automation identifier.

        Raises:
            NonExistingAutomationError: If automation not found.
            AutomationDisabledError: If the automation is disabled.
            AutomationNotRunningError: If the automation is not running.
        """
        await self._load_flags()
        await self._control.stop(self._automation(automation_id))
        _LOGGER.info("Stopped automation: %s", automation_id)

    async def async_restart_automation(self, automation_id: str) -> None:
        """Stop an automation and start it again.

        Args:
            automation_id: Automation identifier.

        Raises:
            NonExistingAutomationError: If automation not found.
            AutomationDisabledError: If the automation is disabled.
            AutomationNotRunningError: If the automation is not running.
        """
        await self._load_flags()
        await self._control.restart(self._automation(automation_id))
        _LOGGER.info("Restarted automation: %s", automation_id)

    def automation_state(self, automation_id: str) -> str:
        """Return the state of an automation: ``unavailable``, ``off``, ``on`` or ``error``."""
        return self.get_automation_state(automation_id).value

    def automation_message(self, automation_id: str) -> str | None:
        """Return why an automation is in the ``error`` state, or None."""
        try:
            return self._automation(automation_id).message
        except NonExistingAutomationError:
            return self._failed_message(automation_id)

    def _failed_message(self, automation_id: str) -> str | None:
        """Return the load error of an automation that could not be loaded, by ID."""
        for path, message in self._failed_automations.items():
            if self._automation_ids.get(path) == automation_id:
                return message
        return None

    def is_automation_enabled(self, automation_id: str) -> bool:
        """Return whether an automation is enabled."""
        return self._control.is_enabled(automation_id)

    async def _load_flags(self) -> None:
        """Read the enabled flags from storage, once."""
        if not self._flags_loaded:
            await self._flags.load()
            self._flags_loaded = True

    @property
    def action_pool(self) -> ActionWorkerPool:
        """Get the action worker pool.

        Returns:
            The ActionWorkerPool instance.
        """
        return self._action_pool

    def get_automation_status(self, automation_id: str) -> AutomationStatus:
        """Get the current status of an automation.

        Args:
            automation_id: Name of the automation.

        Returns:
            The AutomationStatus for the automation.
        """
        return self._status_manager.get_status(automation_id)

    def get_all_automation_statuses(self) -> dict[str, AutomationStatus]:
        """Get the current status of all automations.

        Returns:
            Dictionary mapping automation names to their statuses.
        """
        return self._status_manager.get_all_statuses()


async def async_get_manager(hass: HomeAssistant) -> AutomationManager | None:
    """Get the automation manager instance.

    Args:
        hass: Home Assistant instance.

    Returns:
        The AutomationManager instance, or None if not set up.
    """
    if DOMAIN not in hass.data:
        return None

    data = hass.data[DOMAIN]
    for entry_data in data.values():
        if isinstance(entry_data, dict) and "manager" in entry_data:
            manager = entry_data["manager"]  # type: ignore
            if isinstance(manager, AutomationManager):
                return manager
            return None

    return None
