"""Automation manager for HAAnim.

This module handles loading, watching, and managing multiple automation contexts.
It provides the central coordination point for all automation lifecycle operations.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CoreState, Event, HomeAssistant

from custom_components.haanim.config import ConfigManager, get_config_manager

from custom_components.haanim.options import EngineOptions
from custom_components.haanim.const import (
    DOMAIN,
    EVENT_AUTOMATION_ERROR,
    EVENT_AUTOMATION_LOADED,
    EVENT_AUTOMATION_UNLOADED,
)
from haanim.engine.action_dispatcher import ActionDispatcher
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
from haanim.interfaces import AutomationTimes, Host
from haanim.engine.control import AutomationControl, EnabledFlags
from haanim.engine.errors import (
    HAAnimError,
    NonExistingAutomationError,
)
from haanim.engine.lifecycle import (
    ActionFailure,
    Automation,
    AutomationState,
    LifecycleSettings,
    NoTriggers,
    TriggerRegistrar,
    start_all,
    stop_all,
)

_LOGGER = logging.getLogger(__name__)


class AutomationListener(Protocol):
    """Told when automations appear, change and go away: what the entity platform implements."""

    def automation_changed(self, automation_id: str) -> None:
        """Something about an automation has changed, or the automation is new."""

    def automation_removed(self, automation_id: str) -> None:
        """The folder of an automation is gone."""

    def automations_loaded(self) -> None:
        """Every automation folder has been loaded after Home Assistant started."""


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
        options: EngineOptions | None = None,
    ) -> None:
        """Initialize the automation manager.

        Args:
            hass: Home Assistant instance.
            entry: The config entry for this integration.
            host: The host interfaces the engine uses to reach Home Assistant.
            options: The engine's limits from the integration options. The design's defaults if omitted.
        """
        self._options = options or EngineOptions()
        self._lifecycle_settings = LifecycleSettings(
            startup_timeout=self._options.startup_timeout,
            shutdown_timeout=self._options.shutdown_timeout,
            stop_grace_period=self._options.stop_grace_period,
        )
        self.hass = hass
        self.entry = entry
        self.host = host
        self._status_manager = AutomationStatusManager()

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
            interval=self._options.rescan_interval,
        )

        # Folders that are not loaded because of their name, kept in step with repair issues
        self._folder_issues = FolderIssues(host.issues)
        self._automation_ids: dict[str, str] = {}  # folder path -> automation ID

        # Action worker pool for concurrent execution
        self._action_pool = ActionWorkerPool(
            status_manager=self._status_manager,
            clock=host.clock,
            max_workers=self._options.concurrency_limit,
        )

        # Every action request goes through the dispatcher (execution modes, queues)
        self._dispatcher = ActionDispatcher(
            self._action_pool,
            queue_size=self._options.action_queue_size,
            default_timeout=self._options.default_action_timeout,
        )

        self._control = AutomationControl(self._flags, self._dispatcher)

        # State
        self._started = False
        self._stopped = False
        self._unsub_stop: Callable[[], None] | None = None

        # Who shows the automations: told about every change of every automation
        self._listeners: list[AutomationListener] = []
        self._status_manager.add_listener(self._on_changed)

    def add_listener(self, listener: AutomationListener) -> Callable[[], None]:
        """Tell a listener when automations appear, change and go away.

        Returns:
            A function that removes the listener.
        """
        self._listeners = [*self._listeners, listener]
        return lambda: setattr(self, "_listeners", [kept for kept in self._listeners if kept is not listener])

    def _on_changed(self, automation_id: str) -> None:
        """Pass a change of an automation on to the listeners."""
        for listener in list(self._listeners):
            listener.automation_changed(automation_id)

    @property
    def started(self) -> bool:
        """Whether the automation folders have been loaded and the automations started."""
        return self._started

    def automation_ids(self) -> list[str]:
        """Return the ID of every automation that is loaded or failed to load, sorted."""
        return sorted(automation.automation_id for automation in self._automations.values())

    def automation_name(self, automation_id: str) -> str:
        """Return the name of an automation from its metadata, or its ID if it has none."""
        context = self.get_context_by_name(automation_id)
        metadata = context.get_metadata() if context else None
        return (metadata.name if metadata else None) or automation_id

    def automation_status_message(self, automation_id: str) -> str | None:
        """Return the message an automation set with ``haa.set_message()``, or None."""
        context = self.get_context_by_name(automation_id)
        metadata = context.get_metadata() if context else None
        return metadata.message if metadata else None

    def automation_last_error(self, automation_id: str) -> ActionFailure | None:
        """Return the most recent action failure of an automation, or None."""
        try:
            return self._automation(automation_id).last_error
        except NonExistingAutomationError:
            return None

    async def async_setup(self) -> None:
        """Set up the automation manager.

        This should be called during integration setup.
        """
        # Ensure automation folder exists
        folder = Path(self._automation_path)
        if not folder.exists():
            _LOGGER.info("Creating automation folder: %s", folder)
            folder.mkdir(parents=True, exist_ok=True)

        # Load and start with Home Assistant, or now if it is already running (a reload of the integration)
        if self.hass.state is CoreState.running:
            await self._on_ha_started(None)
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._on_ha_started)
        self._unsub_stop = self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._on_ha_stop)

        _LOGGER.info(
            "Automation manager initialized. Automation folder: %s, Allow all imports: %s",
            folder,
            self._allow_all_imports,
        )

    async def _on_ha_started(self, _: Event | None) -> None:
        """Handle Home Assistant started event.

        Args:
            event: The started event.
        """
        # Load all automations, then start them one at a time in ascending ID order
        await self.async_load_all_automations()
        await start_all(self._automations.values(), self._control.is_enabled)
        self._started = True
        for listener in list(self._listeners):
            listener.automations_loaded()

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
        self._unsub_stop = None
        await self._stop()

    async def async_shutdown(self) -> None:
        """Stop and unload everything: the integration is unloaded or reloaded."""
        if self._unsub_stop is not None:
            self._unsub_stop()
            self._unsub_stop = None
        await self._stop()

    async def _stop(self) -> None:
        """Stop the watcher, every automation and the dispatcher. Does nothing the second time."""
        if self._stopped:
            return
        self._stopped = True
        self._started = False
        # Cancel watcher
        if self._watcher_task:
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass

        # Stop all automations, one at a time in descending ID order
        await stop_all(self._automations.values())

        # Reject new requests and cancel what is still running
        await self._dispatcher.shutdown()

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
            registry=self,
            additional_imports=self._import_allowlist,
            allow_all_imports=self._allow_all_imports,
        )
        automation = Automation(
            context, dispatcher=self._dispatcher, triggers=self._triggers, settings=self._lifecycle_settings
        )

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

        # The name and the enabled flag are known only now
        self._status_manager.notify(automation.automation_id)
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

    async def async_reload(self, automation_id: str | None = None) -> None:
        """Rescan now and reload one automation, or all of them without an ID.

        Raises:
            NonExistingAutomationError: If there is no automation with the ID.
            HAAnimError: If the one automation cannot be loaded; it is then in the error state.
        """
        if automation_id is None:
            await self.async_reload_all_automations()
            for listener in list(self._listeners):
                listener.automations_loaded()
            return
        path = next(
            (
                path
                for path, automation in self._automations.items()
                if automation.automation_id == automation_id
            ),
            None,
        )
        if path is None:
            raise NonExistingAutomationError(automation_id)
        await self.async_load_automation(path)

    def automation_actions(self, automation_id: str) -> list[ActionDefinition]:
        """Return the actions of an automation; none while its code is not running.

        Raises:
            NonExistingAutomationError: If there is no automation with the ID.
        """
        return self._automation(automation_id).context.get_actions()

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
        automation = self._automations.get(automation_path)
        await self.async_unload_automation(automation_path)
        self._automation_ids.pop(automation_path, None)
        if automation is not None:
            for listener in list(self._listeners):
                listener.automation_removed(automation.automation_id)

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
        data: dict[str, Any] | None = None,
    ) -> Any:
        """Run an action by hand, as from the GUI or the run_action service.

        The action receives a ``ManualEvent`` whose ``data`` is the data given.

        Args:
            automation_id: The automation's ID.
            action_name: A name of the action.
            data: The arguments of the call.

        Returns:
            The result of the action.

        Raises:
            NonExistingAutomationError: If there is no automation with that ID.
            ActionNotFoundError: If the automation has no such action, or it is disabled.
            AutomationNotRunningError: If the automation is not running.
            Exception: Whatever the action raises, unchanged.
        """
        return await self._automation(automation_id).call_action(action_name, data)

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
        data: dict[str, Any] | None = None,
        *,
        caller: str | None = None,
    ) -> Any:
        """Call an automation action.

        Args:
            automation_id: Automation identifier.
            action_name: A name of the action to call.
            data: The arguments of the call; the action gets them as ``event.data``.
            caller: ID of the calling automation. Without it the call is a manual one.

        Returns:
            Action return value.

        Raises:
            NonExistingAutomationError: If automation not found.
            AutomationNotRunningError: If the automation is not running.
            ActionNotFoundError: If action not found.
        """
        return await self._automation(automation_id).call_action(action_name, data, caller=caller)

    async def async_enable_automation(self, automation_id: str) -> None:
        """Mark an automation enabled and start it. Does nothing if it is enabled.

        Args:
            automation_id: Automation identifier.

        Raises:
            NonExistingAutomationError: If automation not found.
        """
        await self._load_flags()
        try:
            await self._control.enable(self._automation(automation_id))
        finally:
            self._status_manager.notify(automation_id)
        _LOGGER.info("Enabled automation: %s", automation_id)

    async def async_disable_automation(self, automation_id: str) -> None:
        """Stop an automation and mark it disabled. Does nothing if it is disabled.

        Args:
            automation_id: Automation identifier.

        Raises:
            NonExistingAutomationError: If automation not found.
        """
        await self._load_flags()
        try:
            await self._control.disable(self._automation(automation_id))
        finally:
            self._status_manager.notify(automation_id)
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

    def automation_times(self, automation_id: str) -> AutomationTimes:
        """Return when an automation was loaded, last started and last ran an action."""
        try:
            return self._automation(automation_id).times
        except NonExistingAutomationError:
            return AutomationTimes()

    async def _load_flags(self) -> None:
        """Read the enabled flags from storage, once."""
        if not self._flags_loaded:
            await self._flags.load()
            self._flags_loaded = True

    @property
    def dispatcher(self) -> ActionDispatcher:
        """The dispatcher every action request goes through."""
        return self._dispatcher

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
