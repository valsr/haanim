"""Automation context management for HAAnim.

This module provides the execution context for individual automations, including
symbol tables, metadata, and lifecycle management.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from haanim import const
from haanim.engine import (
    ImportController,
    SafeBuiltins,
    SymbolTable,
    decorators,
)
from haanim.engine.ast_evaluator import AstEvaluator
from haanim.engine.callables import accepted_kwargs, as_coroutine_function
from haanim.engine.decorators import FunctionMetadata, get_metadata, has_metadata
from haanim.engine.errors import PUBLIC_ERRORS, HAAnimError
from haanim.engine.logging_wrapper import create_logger_wrapper
from haanim.engine.automation_status import AutomationStatusManager
from haanim.interfaces import AutomationRegistry, Host

_LOGGER = logging.getLogger(__name__)


@dataclass
class ActionDefinition:
    """Definition of a manually executable action from an automation.

    Args:
        name: Display name for the action.
        func_name: The function name in the automation.
        func: The callable function.
        description: Optional description.
        automation_id: Name of the parent automation.
    """

    name: str
    func_name: str
    func: Callable[..., Any]
    description: str | None = None
    automation_id: str | None = None


@dataclass
class TriggerDefinition:
    """Definition of a trigger attached to a function.

    Args:
        trigger_type: Type of trigger (state_trigger, time_trigger, event_trigger).
        trigger_expr: The trigger expression or configuration.
        func_name: The function name in the automation.
        func: The callable function.
        kwargs: Additional trigger configuration.
        automation_id: Id of the parent automation.
    """

    trigger_type: str
    trigger_expr: str | list[str]
    func_name: str
    func: Callable[..., Any]
    kwargs: dict[str, Any] = field(default_factory=dict[str, Any])
    automation_id: str | None = None


@dataclass
class AutomationMetadata:
    """Metadata about a loaded automation.

    Args:
        name: Display name of the automation.
        path: Filesystem path to the automation.
        filename: Just the filename without path.
        loaded_at: When the automation was loaded.
        modified_at: Last modification time of the file.
        actions: List of manually executable actions.
        triggers: List of triggers defined in the automation.
        error: Any error that occurred during loading.
        has_startup: Whether the automation has a startup handler.
        has_shutdown: Whether the automation has a shutdown handler.
        state: Current automation state (running, stopped, etc.).
        message: Current status message for the automation.
        run_time: Timestamp when the automation was started.
        last_action_time: Timestamp of the last action execution.
    """

    id: str
    path: str
    filename: str
    loaded_at: datetime | None = None
    modified_at: datetime | None = None
    actions: list[ActionDefinition] = field(default_factory=list[ActionDefinition])
    triggers: list[TriggerDefinition] = field(default_factory=list[TriggerDefinition])
    error: str | None = None
    enabled: bool = True
    has_startup: bool = False
    has_shutdown: bool = False
    state: str | None = None
    message: str | None = None
    run_time: datetime | None = None
    last_action_time: datetime | None = None


class AutomationContext:
    """Execution context for a single HAAnim automation.

    Manages the automation's symbol table, evaluator, and extracted metadata
    including actions and triggers.
    """

    def __init__(
        self,
        host: Host,
        automation_path: str,
        *,
        status_manager: AutomationStatusManager,
        storage_path: str,
        registry: AutomationRegistry,
        additional_imports: list[str] | None = None,
        allow_all_imports: bool = False,
    ) -> None:
        """Initialize an automation context.

        Args:
            host: The host the engine runs in.
            automation_path: Path to the automation file.
            status_manager: Where this automation's status is recorded.
            storage_path: Directory holding the persistent storage files of automations.
            registry: The loaded automations, used by ``haa`` to reach other automations.
            additional_imports: Modules automations may import in addition to the default allowlist.
            allow_all_imports: If True, allow all imports.
        """
        self.host = host
        self._status_manager = status_manager
        self._storage_path = storage_path
        self._registry = registry
        self.automation_path = automation_path
        self.filename = os.path.basename(automation_path)
        self.automation_id = os.path.splitext(self.filename)[0].replace(" ", "_")

        # Create logger for this automation
        self._logger = logging.getLogger(f"{__name__}.{self.automation_id}")

        # Initialize components
        self._import_controller = ImportController(
            additional=additional_imports,
            allow_all=allow_all_imports,
        )
        self._safe_builtins = SafeBuiltins()
        self._global_symbols = SymbolTable()
        self._evaluator: AstEvaluator | None = None

        # Automation metadata
        self._metadata: AutomationMetadata | None = None
        self._source: str | None = None

        # Extracted definitions
        self._actions: dict[str, ActionDefinition] = {}
        self._triggers: list[TriggerDefinition] = []
        self._functions: dict[str, Callable[..., Any]] = {}

        # Lifecycle handlers
        self._startup_func: Callable[..., Any] | None = None
        self._shutdown_func: Callable[..., Any] | None = None

    def _setup_builtin_functions(self) -> None:
        """Set up built-in functions available to automations.

        This injects HAAnim-specific functions into the automation's namespace,
        including decorators, logging, and Home Assistant access.
        """
        # Import here to avoid circular dependency
        from haanim.engine.haanim_api import (
            HAAnim,
        )  # pylint: disable=import-outside-toplevel

        # Create the HAAnim API instance for this automation
        haa = HAAnim(self.host, self.automation_id, self._registry, self._storage_path)

        # Create the set_status function bound to this automation
        def set_status(message: str | None) -> None:
            """Set a status message for this automation.

            This message is displayed in the UI when the automation is running.
            The status message is automatically cleared when the action completes.

            Args:
                message: The status message to display, or None to clear.
            """
            self._status_manager.set_status_message(self.automation_id, message)

        # Create a virtual 'haanim' module that automations can import from
        haanim_module = SimpleNamespace(
            action=decorators.action,
            state=decorators.state,
            state_trigger=decorators.state_trigger,
            time=decorators.time,
            time_trigger=decorators.time_trigger,
            interval=decorators.interval,
            cron=decorators.cron,
            event=decorators.event,
            event_trigger=decorators.event_trigger,
            time_active=decorators.time_active,
            state_active=decorators.state_active,
            startup=decorators.startup,
            shutdown=decorators.shutdown,
            set_status=set_status,
            haa=haa,
            ActionMode=const.ActionMode,
            # Export event classes
            ActionEvent=None,  # Will be populated from events module
            TimeEvent=None,
            IntervalEvent=None,
            CronEvent=None,
            StateEvent=None,
            EventTriggerEvent=None,
        )

        # Import event classes
        try:
            from haanim.events import (  # pylint: disable=import-outside-toplevel
                ActionEvent,
                TimeEvent,
                IntervalEvent,
                CronEvent,
                StateEvent,
                EventTriggerEvent,
            )

            haanim_module.ActionEvent = ActionEvent
            haanim_module.TimeEvent = TimeEvent
            haanim_module.IntervalEvent = IntervalEvent
            haanim_module.CronEvent = CronEvent
            haanim_module.StateEvent = StateEvent
            haanim_module.EventTriggerEvent = EventTriggerEvent
        except ImportError:
            pass

        # Export the public error classes
        for error_class in PUBLIC_ERRORS:
            setattr(haanim_module, error_class.__name__, error_class)

        # 'import logging' and 'from haanim import logging' give the automation's logger
        logging_module = create_logger_wrapper(self._logger)
        haanim_module.logging = logging_module
        haanim_module.hass = self.host.hass

        # Register what the engine supplies for these imports
        self._import_controller.register_virtual_module("haanim", haanim_module)
        self._import_controller.register_virtual_module("logging", logging_module)
        if self.host.hass is not None:
            self._import_controller.register_virtual_module("hass", self.host.hass)

        # Add decorators to global scope (for direct use without import)
        self._global_symbols.set("action", decorators.action)
        self._global_symbols.set("state", decorators.state)
        self._global_symbols.set("state_trigger", decorators.state_trigger)
        self._global_symbols.set("time", decorators.time)
        self._global_symbols.set("time_trigger", decorators.time_trigger)
        self._global_symbols.set("interval", decorators.interval)
        self._global_symbols.set("cron", decorators.cron)
        self._global_symbols.set("event", decorators.event)
        self._global_symbols.set("event_trigger", decorators.event_trigger)
        self._global_symbols.set("time_active", decorators.time_active)
        self._global_symbols.set("state_active", decorators.state_active)
        self._global_symbols.set("startup", decorators.startup)
        self._global_symbols.set("shutdown", decorators.shutdown)

        # Add HAAnim API instance to global scope
        self._global_symbols.set("haa", haa)
        self._global_symbols.set("ActionMode", const.ActionMode)

        # Add set_status function to global scope
        self._global_symbols.set("set_status", set_status)

        self._global_symbols.set("logging", logging_module)

        # Add logging functions for convenience
        self._global_symbols.set("log_debug", self._logger.debug)
        self._global_symbols.set("log_info", self._logger.info)
        self._global_symbols.set("log_warning", self._logger.warning)
        self._global_symbols.set("log_error", self._logger.error)

        # Also expose the automation's logger as 'log'
        self._global_symbols.set("log", self._logger)
        self._global_symbols.set("sleep", self.host.clock.sleep)

    async def load(self) -> AutomationMetadata:
        """Load and parse the automation file.

        Returns:
            AutomationMetadata with information about the loaded automation.

        Raises:
            HAAnimError: If loading or parsing fails.
        """
        path = Path(self.automation_path)

        if not self.host.files.exists(path):
            raise HAAnimError(f"Automation file not found: {self.automation_path}")

        # Read the source
        try:
            self._source = await self.host.files.read_text(path)
        except OSError as err:
            raise HAAnimError(f"Failed to read automation file: {err}") from err

        if not self._source:
            raise HAAnimError(f"Failed to read automation file: {self.automation_path}")

        # Get file modification time
        modified_at = self.host.files.modified_time(path)

        # Set up built-in functions
        self._setup_builtin_functions()

        # Create evaluator
        self._evaluator = AstEvaluator(
            name=self.automation_id,
            global_symbols=self._global_symbols,
            import_controller=self._import_controller,
            safe_builtins=self._safe_builtins,
            logger=self._logger,
            files=self.host.files,
            path=path,
            clock=self.host.clock,
        )

        # Parse the source
        try:
            self._evaluator.parse(self._source, filename=self.filename)
        except HAAnimError:
            raise
        except Exception as err:
            raise HAAnimError(f"Failed to parse automation: {err}") from err

        # Execute the automation to define functions and variables
        try:
            await self._evaluator.execute()
        except HAAnimError:
            raise
        except Exception as err:
            raise HAAnimError(f"Failed to execute automation: {err}") from err

        # Extract definitions from the global scope
        self._extract_definitions()

        # Create metadata
        self._metadata = AutomationMetadata(
            id=self.automation_id,
            path=self.automation_path,
            filename=self.filename,
            loaded_at=self.host.clock.now(),
            modified_at=modified_at,
            actions=list(self._actions.values()),
            triggers=self._triggers,
            has_startup=self._startup_func is not None,
            has_shutdown=self._shutdown_func is not None,
        )

        self._logger.info(
            "Automation loaded: %s (%d actions, %d triggers, startup=%s, shutdown=%s)",
            self.automation_id,
            len(self._actions),
            len(self._triggers),
            self._startup_func is not None,
            self._shutdown_func is not None,
        )

        return self._metadata

    def _extract_definitions(self) -> None:
        """Extract action, trigger definitions from loaded automation."""
        symbols = self._global_symbols.as_dict()

        for name, obj in symbols.items():
            # Skip non-callables and builtins
            if not callable(obj) or name.startswith("_"):
                continue

            # Check for HAAnim metadata
            if has_metadata(obj):
                metadata = get_metadata(obj)
                if not metadata:
                    raise RuntimeError("Metadata expected but not found")
                self._process_function_metadata(name, obj, metadata)
            elif hasattr(obj, "_haanim_metadata"):
                # Also check wrapped functions
                metadata = getattr(obj, "_haanim_metadata")
                self._process_function_metadata(name, obj, metadata)

            # Store all functions for potential use
            self._functions[name] = obj

    def _process_function_metadata(
        self,
        func_name: str,
        func: Callable[..., Any],
        metadata: FunctionMetadata,
    ) -> None:
        """Process metadata from a decorated function.

        Args:
            func_name: Name of the function.
            func: The function object.
            metadata: Extracted metadata from decorators.
        """
        # Process actions (@action) OR functions with triggers (implicit action)
        # Any function with triggers is automatically callable as an action
        if metadata.is_marked_as_action or metadata.triggers:
            action_info = metadata.action_info
            action_name = (action_info.name if action_info else None) or func_name

            self._actions[func_name] = ActionDefinition(
                name=action_name,
                func_name=func_name,
                func=func,
                description=action_info.description if action_info else None,
                automation_id=self.automation_id,
            )

        # Process triggers
        for trigger_info in metadata.triggers:
            self._triggers.append(
                TriggerDefinition(
                    trigger_type=trigger_info.trigger_type,
                    trigger_expr=trigger_info.trigger_expr,
                    func_name=func_name,
                    func=func,
                    kwargs=trigger_info.kwargs,
                    automation_id=self.automation_id,
                )
            )

        # Process lifecycle handlers
        if metadata.is_startup:
            if self._startup_func is not None:
                self._logger.warning(
                    "Multiple @startup handlers found in automation '%s'. Only the last one will be used.",
                    self.automation_id,
                )
            self._startup_func = func
            self._logger.debug("Registered startup handler: %s", func_name)

        if metadata.is_shutdown:
            if self._shutdown_func is not None:
                self._logger.warning(
                    "Multiple @shutdown handlers found in automation '%s'. Only the last one will be used.",
                    self.automation_id,
                )
            self._shutdown_func = func
            self._logger.debug("Registered shutdown handler: %s", func_name)

    async def run_action(
        self,
        action_name: str,
        *args: Any,
        manual: bool = True,
        **kwargs: Any,
    ) -> Any:
        """Run a specific action by name.

        Args:
            action_name: The name of the action to run.
            *args: Positional arguments to pass to the action.
            manual: If True, this is a manual execution (bypasses constraints).
            **kwargs: Keyword arguments to pass to the action.

        Returns:
            The return value of the action.

        Raises:
            HAAnimError: If the action is not found or execution fails.
        """
        if action_name not in self._actions:
            raise HAAnimError(f"Action '{action_name}' not found in automation '{self.automation_id}'")

        action = self._actions[action_name]

        # Offer the manual flag to actions that declare it
        kwargs.update(accepted_kwargs(action.func, {"manual": manual}))

        self._logger.info(
            "Running action '%s' (%s)",
            action.name,
            const.EXEC_MODE_MANUAL if manual else const.EXEC_MODE_TRIGGER,
        )

        try:
            return await as_coroutine_function(action.func)(*args, **kwargs)
        except Exception as err:
            self._logger.error("Action '%s' failed: %s", action_name, err)
            raise HAAnimError(f"Action '{action_name}' failed: {err}") from err

    async def run_function(
        self,
        func_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run any function defined in the automation by name.

        Args:
            func_name: The name of the function to run.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            The return value of the function.
        """
        if func_name not in self._functions:
            raise HAAnimError(f"Function '{func_name}' not found in automation '{self.automation_id}'")

        func = self._functions[func_name]

        try:
            return await as_coroutine_function(func)(*args, **kwargs)
        except Exception as err:
            self._logger.error("Function '%s' failed: %s", func_name, err)
            raise HAAnimError(f"Function '{func_name}' failed: {err}") from err

    def get_action(self, name: str) -> ActionDefinition | None:
        """Get one action by name.

        Args:
            name: The action's name.

        Returns:
            The action definition, or None if the automation has no such action.
            The name may be the function name or the action's display name.
        """
        if name in self._actions:
            return self._actions[name]
        for action in self._actions.values():
            if action.name == name:
                return action
        return None

    def get_actions(self) -> list[ActionDefinition]:
        """Get all actions defined in this automation.

        Returns:
            List of action definitions.
        """
        return list(self._actions.values())

    def get_triggers(self) -> list[TriggerDefinition]:
        """Get all triggers defined in this automation.

        Returns:
            List of trigger definitions.
        """
        return self._triggers

    def get_metadata(self) -> AutomationMetadata | None:
        """Get the automation metadata.

        Returns:
            The automation metadata, or None if not loaded.
        """
        return self._metadata

    def get_symbol(self, name: str) -> Any:
        """Get a symbol from the automation's global scope.

        Args:
            name: The symbol name.

        Returns:
            The symbol value, or None if not found.
        """
        return self._global_symbols.get(name)

    def set_symbol(self, name: str, value: Any) -> None:
        """Set a symbol in the automation's global scope.

        Args:
            name: The symbol name.
            value: The value to set.
        """
        self._global_symbols.set(name, value)

    @property
    def id(self) -> str:
        """Get the id of the automation."""
        if self._metadata:
            return self._metadata.id
        return self.automation_id

    @property
    def is_loaded(self) -> bool:
        """Check if the automation is loaded."""
        return self._metadata is not None

    @property
    def source(self) -> str | None:
        """Get the automation source code."""
        return self._source

    @property
    def has_startup(self) -> bool:
        """Check if the automation has a startup handler."""
        return self._startup_func is not None

    @property
    def has_shutdown(self) -> bool:
        """Check if the automation has a shutdown handler."""
        return self._shutdown_func is not None

    def get_startup_func(self) -> Callable[..., Any] | None:
        """Get the startup handler function.

        Returns:
            The startup function, or None if not defined.
        """
        return self._startup_func

    def get_shutdown_func(self) -> Callable[..., Any] | None:
        """Get the shutdown handler function.

        Returns:
            The shutdown function, or None if not defined.
        """
        return self._shutdown_func
