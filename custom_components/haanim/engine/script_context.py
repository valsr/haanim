"""Script context management for HAAnim.

This module provides the execution context for individual scripts, including
symbol tables, metadata, and lifecycle management.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from homeassistant.core import HomeAssistant

from custom_components.haanim import const
from custom_components.haanim.engine import (
    ImportController,
    SafeBuiltins,
    SymbolTable,
    decorators,
)
from custom_components.haanim.engine.ast_evaluator import AstEvaluator
from custom_components.haanim.engine.decorators import FunctionMetadata, get_metadata, has_metadata
from custom_components.haanim.engine.errors import ScriptError
from custom_components.haanim.engine.script_status import get_status_manager

_LOGGER = logging.getLogger(__name__)


@dataclass
class ActionDefinition:
    """Definition of a manually executable action from a script.

    Args:
        name: Display name for the action.
        func_name: The function name in the script.
        func: The callable function.
        description: Optional description.
        script_name: Name of the parent script.
    """

    name: str
    func_name: str
    func: Callable[..., Any]
    description: str | None = None
    script_name: str | None = None


@dataclass
class TriggerDefinition:
    """Definition of a trigger attached to a function.

    Args:
        trigger_type: Type of trigger (state_trigger, time_trigger, event_trigger).
        trigger_expr: The trigger expression or configuration.
        func_name: The function name in the script.
        func: The callable function.
        kwargs: Additional trigger configuration.
        script_id: Id of the parent script.
    """

    trigger_type: str
    trigger_expr: str | list[str]
    func_name: str
    func: Callable[..., Any]
    kwargs: dict[str, Any] = field(default_factory=dict[str, Any])
    script_id: str | None = None


@dataclass
class ScriptMetadata:
    """Metadata about a loaded script.

    Args:
        name: Display name of the script.
        path: Filesystem path to the script.
        filename: Just the filename without path.
        loaded_at: When the script was loaded.
        modified_at: Last modification time of the file.
        actions: List of manually executable actions.
        triggers: List of triggers defined in the script.
        error: Any error that occurred during loading.
        has_startup: Whether the script has a startup handler.
        has_shutdown: Whether the script has a shutdown handler.
        state: Current script state (running, stopped, etc.).
        message: Current status message for the script.
        run_time: Timestamp when the script was started.
        last_action_time: Timestamp of the last action execution.
    """

    id: str
    path: str
    filename: str
    loaded_at: datetime = field(default_factory=datetime.now)
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


class ScriptContext:
    """Execution context for a single HAAnim script.

    Manages the script's symbol table, evaluator, and extracted metadata
    including actions and triggers.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        script_path: str,
        import_allowlist: list[str] | None = None,
        allow_all_imports: bool = False,
    ) -> None:
        """Initialize a script context.

        Args:
            hass: Home Assistant instance.
            script_path: Path to the script file.
            import_allowlist: List of allowed import modules.
            allow_all_imports: If True, allow all imports.
        """
        self.hass = hass
        self.script_path = script_path
        self.filename = os.path.basename(script_path)
        self.script_id = os.path.splitext(self.filename)[0].replace(" ", "_")

        # Create logger for this script
        self._logger = logging.getLogger(f"{__name__}.{self.script_id}")

        # Initialize components
        self._import_controller = ImportController(
            allowlist=import_allowlist,
            allow_all=allow_all_imports,
        )
        self._safe_builtins = SafeBuiltins()
        self._global_symbols = SymbolTable()
        self._evaluator: AstEvaluator | None = None

        # Script metadata
        self._metadata: ScriptMetadata | None = None
        self._source: str | None = None

        # Extracted definitions
        self._actions: dict[str, ActionDefinition] = {}
        self._triggers: list[TriggerDefinition] = []
        self._functions: dict[str, Callable[..., Any]] = {}

        # Lifecycle handlers
        self._startup_func: Callable[..., Any] | None = None
        self._shutdown_func: Callable[..., Any] | None = None

    def _setup_builtin_functions(self) -> None:
        """Set up built-in functions available to scripts.

        This injects HAAnim-specific functions into the script's namespace,
        including decorators, logging, and Home Assistant access.
        """
        # Import here to avoid circular dependency
        from custom_components.haanim.engine.haanim_api import (
            HAAnim,
        )  # pylint: disable=import-outside-toplevel

        # Create the HAAnim API instance for this script
        storage_path = self.hass.config.path(".storage", "haanim", "scripts")
        haa = HAAnim(self.hass, self.script_id, self.hass.data.get("haanim_manager"), storage_path)

        # Create the set_status function bound to this script
        def set_status(message: str | None) -> None:
            """Set a status message for this script.

            This message is displayed in the UI when the script is running.
            The status message is automatically cleared when the action completes.

            Args:
                message: The status message to display, or None to clear.
            """
            status_manager = get_status_manager()
            status_manager.set_status_message(self.script_id, message)

        # Create a virtual 'haanim' module that scripts can import from
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
            from custom_components.haanim.events import (  # pylint: disable=import-outside-toplevel
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

        # Register the virtual module with the import controller
        self._import_controller.register_virtual_module("haanim", haanim_module)

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

        # Add logging module wrapper
        from custom_components.haanim.engine.logging_wrapper import (  # pylint: disable=import-outside-toplevel
            create_logger_wrapper,
        )

        self._global_symbols.set("logging", create_logger_wrapper(self._logger))

        # Add logging functions for convenience
        self._global_symbols.set("log_debug", self._logger.debug)
        self._global_symbols.set("log_info", self._logger.info)
        self._global_symbols.set("log_warning", self._logger.warning)
        self._global_symbols.set("log_error", self._logger.error)

        # Also expose the script's logger as 'log'
        self._global_symbols.set("log", self._logger)
        self._global_symbols.set("sleep", asyncio.sleep)

    def read_file(self, path: Path) -> str:
        """Read the content of a file asynchronously.

        Args:
            path: The path to the file to read.
        """
        return path.read_text(encoding="utf-8")

    async def load(self) -> ScriptMetadata:
        """Load and parse the script file.

        Returns:
            ScriptMetadata with information about the loaded script.

        Raises:
            ScriptError: If loading or parsing fails.
        """
        path = Path(self.script_path)

        if not path.exists():
            raise ScriptError(f"Script file not found: {self.script_path}")

        # Read the source
        try:
            self._source = await self.hass.async_add_executor_job(self.read_file, path)
        except OSError as err:
            raise ScriptError(f"Failed to read script file: {err}") from err

        if not self._source:
            raise ScriptError(f"Failed to read script file: {self.script_path}")

        # Get file modification time
        stat = path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime)

        # Set up built-in functions
        self._setup_builtin_functions()

        # Create evaluator
        self._evaluator = AstEvaluator(
            name=self.script_id,
            global_symbols=self._global_symbols,
            import_controller=self._import_controller,
            safe_builtins=self._safe_builtins,
            logger=self._logger,
        )

        # Parse the source
        try:
            self._evaluator.parse(self._source, filename=self.filename)
        except ScriptError:
            raise
        except Exception as err:
            raise ScriptError(f"Failed to parse script: {err}") from err

        # Execute the script to define functions and variables
        try:
            await self._evaluator.execute()
        except ScriptError:
            raise
        except Exception as err:
            raise ScriptError(f"Failed to execute script: {err}") from err

        # Extract definitions from the global scope
        self._extract_definitions()

        # Create metadata
        self._metadata = ScriptMetadata(
            id=self.script_id,
            path=self.script_path,
            filename=self.filename,
            loaded_at=datetime.now(),
            modified_at=modified_at,
            actions=list(self._actions.values()),
            triggers=self._triggers,
            has_startup=self._startup_func is not None,
            has_shutdown=self._shutdown_func is not None,
        )

        self._logger.info(
            "Script loaded: %s (%d actions, %d triggers, startup=%s, shutdown=%s)",
            self.script_id,
            len(self._actions),
            len(self._triggers),
            self._startup_func is not None,
            self._shutdown_func is not None,
        )

        return self._metadata

    def _extract_definitions(self) -> None:
        """Extract action, trigger definitions from loaded script."""
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
                script_name=self.script_id,
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
                    script_id=self.script_id,
                )
            )

        # Process lifecycle handlers
        if metadata.is_startup:
            if self._startup_func is not None:
                self._logger.warning(
                    "Multiple @startup handlers found in script '%s'. Only the last one will be used.",
                    self.script_id,
                )
            self._startup_func = func
            self._logger.debug("Registered startup handler: %s", func_name)

        if metadata.is_shutdown:
            if self._shutdown_func is not None:
                self._logger.warning(
                    "Multiple @shutdown handlers found in script '%s'. Only the last one will be used.",
                    self.script_id,
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
            ScriptError: If the action is not found or execution fails.
        """
        if action_name not in self._actions:
            raise ScriptError(f"Action '{action_name}' not found in script '{self.script_id}'")

        action = self._actions[action_name]

        # Add manual flag to kwargs
        kwargs["manual"] = manual

        self._logger.info(
            "Running action '%s' (%s)",
            action.name,
            const.EXEC_MODE_MANUAL if manual else const.EXEC_MODE_TRIGGER,
        )

        try:
            if asyncio.iscoroutinefunction(action.func):
                return await action.func(*args, **kwargs)
            else:
                # Wrap sync function in async
                return await self.hass.async_add_executor_job(action.func, *args, **kwargs)
        except Exception as err:
            self._logger.error("Action '%s' failed: %s", action_name, err)
            raise ScriptError(f"Action '{action_name}' failed: {err}") from err

    async def run_function(
        self,
        func_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run any function defined in the script by name.

        Args:
            func_name: The name of the function to run.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            The return value of the function.
        """
        if func_name not in self._functions:
            raise ScriptError(f"Function '{func_name}' not found in script '{self.script_id}'")

        func = self._functions[func_name]

        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)

            return await self.hass.async_add_executor_job(func, *args, **kwargs)
        except Exception as err:
            self._logger.error("Function '%s' failed: %s", func_name, err)
            raise ScriptError(f"Function '{func_name}' failed: {err}") from err

    def get_actions(self) -> list[ActionDefinition]:
        """Get all actions defined in this script.

        Returns:
            List of action definitions.
        """
        return list(self._actions.values())

    def get_triggers(self) -> list[TriggerDefinition]:
        """Get all triggers defined in this script.

        Returns:
            List of trigger definitions.
        """
        return self._triggers

    def get_metadata(self) -> ScriptMetadata | None:
        """Get the script metadata.

        Returns:
            The script metadata, or None if not loaded.
        """
        return self._metadata

    def get_symbol(self, name: str) -> Any:
        """Get a symbol from the script's global scope.

        Args:
            name: The symbol name.

        Returns:
            The symbol value, or None if not found.
        """
        return self._global_symbols.get(name)

    def set_symbol(self, name: str, value: Any) -> None:
        """Set a symbol in the script's global scope.

        Args:
            name: The symbol name.
            value: The value to set.
        """
        self._global_symbols.set(name, value)

    @property
    def id(self) -> str:
        """Get the id of the script."""
        if self._metadata:
            return self._metadata.id
        return self.script_id

    @property
    def is_loaded(self) -> bool:
        """Check if the script is loaded."""
        return self._metadata is not None

    @property
    def source(self) -> str | None:
        """Get the script source code."""
        return self._source

    @property
    def has_startup(self) -> bool:
        """Check if the script has a startup handler."""
        return self._startup_func is not None

    @property
    def has_shutdown(self) -> bool:
        """Check if the script has a shutdown handler."""
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
