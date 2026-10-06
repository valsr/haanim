"""Automation context management for HAAnim.

This module provides the execution context for individual automations, including
symbol tables, metadata, and lifecycle management.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from haanim import const
from haanim.engine import (
    ImportController,
    SafeBuiltins,
    SymbolTable,
)
from haanim.engine.ast_evaluator import AstEvaluator
from haanim.engine.automation_ids import automation_id as derive_automation_id
from haanim.engine.callables import as_coroutine_function, event_arguments, signature_problem
from haanim.engine.decorators import ActionInfo, FunctionMetadata, TriggerInfo, get_metadata
from haanim.engine.discovery import MAIN_FILENAME, has_main, last_modified, source_files
from haanim.engine.errors import (
    ActionNotFoundError,
    AutomationDefinitionError,
    AutomationNotLoadedError,
    AutomationSyntaxError,
    HAAnimError,
)
from haanim.engine.expression_eval import parse_expression
from haanim.events import SOURCE_TRIGGER, ActionEvent, AutomationEvent, ManualEvent
from haanim.engine.haanim_module import DecoratorRegistry, build_haanim_module
from haanim.engine.logging_wrapper import automation_logger, create_logger_wrapper
from haanim.engine.metadata import DEFAULT_VERSION, load_metadata
from haanim.engine.validation import validate_files
from haanim.engine.variables import VariableStore
from haanim.engine.automation_status import AutomationStatusManager
from haanim.interfaces import AutomationRegistry, Host

_LOGGER = logging.getLogger(__name__)


@dataclass
class ActionDefinition:
    """An action of an automation.

    Args:
        name: The name the action is addressed by.
        func_name: The name of the function in the automation.
        func: The function.
        description: What the action does.
        automation_id: ID of the automation the action belongs to.
        aliases: Additional names the action is addressed by.
        execution_mode: How concurrent calls are handled.
        timeout: Time limit in seconds; None for the default timeout.
        disabled: Whether the action is listed but cannot be called.
    """

    name: str
    func_name: str
    func: Callable[..., Any]
    description: str | None = None
    automation_id: str | None = None
    aliases: tuple[str, ...] = ()
    execution_mode: const.ActionMode = const.ActionMode.DROP
    timeout: float | None = None
    disabled: bool = False

    @property
    def names(self) -> tuple[str, ...]:
        """Every name the action is addressed by: its name, then its aliases."""
        return (self.name, *self.aliases)


@dataclass
class TriggerDefinition:
    """A trigger attached to an action.

    Args:
        trigger_type: The kind of trigger: one of the ``TRIGGER_*`` constants.
        trigger_expr: The trigger's expression, or the event type.
        func_name: The name of the function in the automation.
        func: The function.
        kwargs: The trigger's own options.
        automation_id: ID of the automation the trigger belongs to.
        constraints: The constraint arguments given to the trigger decorator, by name.
        action_name: The name of the action the function is; the function name if omitted.
        execution_mode: The execution mode of that action.
        timeout: The time limit of that action in seconds; None for the default timeout.
        logger: The automation's logger, for what the trigger has to tell the automation's author.
    """

    trigger_type: str
    trigger_expr: Any
    func_name: str
    func: Callable[..., Any]
    kwargs: dict[str, Any] = field(default_factory=dict[str, Any])
    automation_id: str | None = None
    constraints: dict[str, Any] = field(default_factory=dict[str, Any])
    action_name: str | None = None
    execution_mode: const.ActionMode = const.ActionMode.DROP
    timeout: float | None = None
    logger: logging.Logger | None = None


@dataclass
class AutomationMetadata:
    """Metadata about a loaded automation.

    Args:
        id: The automation's ID.
        path: Path of the automation's folder.
        filename: Name of the entry point within the folder.
        name: Display name, from ``metadata.json`` or the folder name.
        description: Short description, from ``metadata.json``.
        author: Author, from ``metadata.json``.
        version: Version string, from ``metadata.json``.
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
    name: str = ""
    description: str = ""
    author: str = ""
    version: str = DEFAULT_VERSION
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
        automation_id: str | None = None,
        status_manager: AutomationStatusManager,
        registry: AutomationRegistry,
        additional_imports: list[str] | None = None,
        allow_all_imports: bool = False,
    ) -> None:
        """Initialize an automation context.

        Args:
            host: The host the engine runs in.
            automation_path: Path of the automation's folder, which holds its ``main.py``.
            automation_id: The automation's ID. Derived from the folder name if omitted.
            status_manager: Where this automation's status is recorded.
            registry: The loaded automations, used by ``haa`` to reach other automations.
            additional_imports: Modules automations may import in addition to the default allowlist.
            allow_all_imports: If True, allow all imports.
        """
        self.host = host
        self._status_manager = status_manager
        self._registry = registry
        self.automation_path = automation_path
        self.folder = Path(automation_path)
        self.filename = MAIN_FILENAME
        self.automation_id = automation_id or derive_automation_id(self.folder.name)
        if not self.automation_id:
            raise HAAnimError(f"Folder name '{self.folder.name}' gives no automation ID")

        # Create logger for this automation
        self._logger = automation_logger(self.automation_id)

        # Initialize components
        self._import_controller = ImportController(
            additional=additional_imports,
            allow_all=allow_all_imports,
        )
        # print writes to the automation's logger at INFO level
        self._safe_builtins = SafeBuiltins(
            additional_allowed={"print": create_logger_wrapper(self._logger).print}
        )
        self._global_symbols = SymbolTable()
        self._evaluator: AstEvaluator | None = None

        # Automation metadata
        self._metadata: AutomationMetadata | None = None
        self._source: str | None = None

        # Extracted definitions
        self._actions: dict[str, ActionDefinition] = {}
        self._action_names: dict[str, ActionDefinition] = {}
        self._startup_name = self._shutdown_name = ""
        self._triggers: list[TriggerDefinition] = []

        # Lifecycle handlers
        self._startup_func: Callable[..., Any] | None = None
        self._shutdown_func: Callable[..., Any] | None = None

        # What the automation's code gets from 'haanim'
        self._decorators = DecoratorRegistry()
        self._haa: Any = None
        # The persistent variables of the running automation; None while its code is not loaded into memory
        self.variables: VariableStore | None = None

    def _build_modules(self) -> None:
        """Build the modules the engine supplies to this automation.

        Nothing is put into the automation's namespace: the automation gets
        its ``haa`` instance, decorators and logger by importing them from
        ``haanim``.
        """
        # Import here to avoid circular dependency
        from haanim.engine.haanim_api import (  # pylint: disable=import-outside-toplevel
            HAAnim,
        )

        self._haa = HAAnim(self.host, self.automation_id, self._registry, folder=self.folder)
        self.variables = self._haa.variables
        logging_module = create_logger_wrapper(self._logger)
        haanim_module = build_haanim_module(
            haa=self._haa,
            registry=self._decorators,
            logging_wrapper=logging_module,
            hass=self.host.hass,
            helpers={"sleep": self._haa.sleep},
        )

        # Register what the engine supplies for these imports
        self._import_controller.register_virtual_module("haanim", haanim_module)
        self._import_controller.register_virtual_module("logging", logging_module)
        if self.host.hass is not None:
            self._import_controller.register_virtual_module("hass", self.host.hass)

    def discard(self) -> None:
        """Discard everything the automation's code created.

        After this the automation's ``haa`` instance, its ``haanim`` module and
        its namespace are no longer referenced by the engine. The automation
        stays loaded and can be executed again.
        """
        self._import_controller.clear_virtual_modules()
        self._decorators.clear()
        self._global_symbols = SymbolTable()
        self._evaluator = None
        if self._haa is not None:
            self._haa.card.close()
        self._haa = None
        self.variables = None
        self._actions = {}
        self._action_names = {}
        self._triggers = []
        self._startup_func = None
        self._shutdown_func = None
        self._startup_name = self._shutdown_name = ""
        if self._metadata is not None:
            self._metadata.actions = []
            self._metadata.triggers = []
            self._metadata.has_startup = False
            self._metadata.has_shutdown = False

    def unload(self) -> None:
        """Discard the automation's namespace and release its checked code."""
        self.discard()
        self._metadata = None
        self._source = None

    async def load(self) -> AutomationMetadata:
        """Load the automation from its folder without running any of it.

        Reads ``metadata.json`` and checks every Python file of the folder for
        syntax errors, unsupported constructs and disallowed imports and
        builtins.

        Returns:
            AutomationMetadata of the loaded automation. Its actions and
            triggers are empty until the automation's code is executed.

        Raises:
            HAAnimError: If the folder has no ``main.py``, the metadata is
                invalid, or a file does not pass the checks.
        """
        files = self.host.files
        path = self.folder / MAIN_FILENAME
        self.unload()

        if not has_main(files, self.folder):
            raise HAAnimError(f"Automation has no {MAIN_FILENAME}: {self.automation_path}")

        info = await load_metadata(files, self.folder)

        try:
            sources = await source_files(files, self.folder)
            await validate_files(
                files,
                sources,
                imports=self._import_controller,
                restricted_builtins=self._safe_builtins.restricted,
                relative_to=self.folder,
            )
            source = await files.read_text(path)
            modified_at = await last_modified(files, self.folder)
        except OSError as err:
            raise HAAnimError(f"Failed to read automation '{self.automation_id}': {err}") from err

        self._source = source
        self._metadata = AutomationMetadata(
            id=self.automation_id,
            path=self.automation_path,
            filename=self.filename,
            name=info.name,
            description=info.description,
            author=info.author,
            version=info.version,
            loaded_at=self.host.clock.now(),
            modified_at=modified_at,
        )
        return self._metadata

    async def execute(self) -> AutomationMetadata:
        """Run ``main.py`` from top to bottom in a fresh namespace.

        This runs the decorators, which collect the automation's actions,
        triggers and lifecycle handlers. A namespace left from an earlier
        execution is discarded first. If the code raises, the new namespace is
        discarded too.

        Returns:
            The automation's metadata, now with its actions and triggers.

        Raises:
            AutomationNotLoadedError: If the automation has not been loaded.
            HAAnimError: If the code cannot be run.
        """
        if self._metadata is None or self._source is None:
            raise AutomationNotLoadedError(self.automation_id)

        self.discard()
        self._build_modules()
        # The variables are in memory before any code runs: reading them is synchronous
        assert self.variables is not None
        await self.variables.load()
        self._evaluator = AstEvaluator(
            name=self.automation_id,
            global_symbols=self._global_symbols,
            import_controller=self._import_controller,
            safe_builtins=self._safe_builtins,
            logger=self._logger,
            files=self.host.files,
            path=self.folder / MAIN_FILENAME,
            clock=self.host.clock,
        )

        try:
            self._evaluator.parse(self._source, filename=self.filename)
            await self._evaluator.execute()
            self._extract_definitions()
        except BaseException:
            self.discard()
            raise

        self._metadata.actions = list(self._actions.values())
        self._metadata.triggers = self._triggers
        self._metadata.has_startup = self._startup_func is not None
        self._metadata.has_shutdown = self._shutdown_func is not None

        _LOGGER.info(
            "Automation executed: %s (%d actions, %d triggers, startup=%s, shutdown=%s)",
            self.automation_id,
            len(self._actions),
            len(self._triggers),
            self._startup_func is not None,
            self._shutdown_func is not None,
        )
        return self._metadata

    def _extract_definitions(self) -> None:
        """Collect the actions, triggers and lifecycle handlers of the executed automation.

        They are the functions decorated with this automation's decorators, in
        any of its files.

        Raises:
            AutomationDefinitionError: If two actions share a name or alias, or
                there is more than one ``@startup`` or ``@shutdown`` handler.
        """
        for func in self._decorators.functions:
            metadata = get_metadata(func)
            if metadata is not None:
                self._process_function_metadata(getattr(func, "__name__", repr(func)), func, metadata)

    def _process_function_metadata(
        self,
        func_name: str,
        func: Callable[..., Any],
        metadata: FunctionMetadata,
    ) -> None:
        """Turn what the decorators recorded on one function into definitions.

        Args:
            func_name: Name of the function.
            func: The function object.
            metadata: What the decorators recorded.
        """
        # Data is never bound to parameters: these functions take the event or nothing
        problem = signature_problem(func)
        if problem is not None:
            raise AutomationDefinitionError(f"'{func_name}' cannot be called: {problem}")

        # A function with @action or with a trigger is one action
        if metadata.is_action:
            info = metadata.action_info or ActionInfo()
            definition = ActionDefinition(
                name=info.name or func_name,
                func_name=func_name,
                func=func,
                description=info.description,
                automation_id=self.automation_id,
                aliases=info.aliases,
                execution_mode=info.execution_mode,
                timeout=info.timeout,
                disabled=info.disabled,
            )
            for name in dict.fromkeys(definition.names):
                other = self._action_names.get(name)
                if other is not None:
                    raise AutomationDefinitionError(
                        f"Action name '{name}' is used by both '{other.func_name}' and '{func_name}'"
                    )
                self._action_names[name] = definition
            self._actions[func_name] = definition

            # The triggers of a disabled action are not registered
            if not definition.disabled:
                for trigger_info in metadata.triggers:
                    self._check_expressions(func_name, trigger_info)
                    self._triggers.append(
                        TriggerDefinition(
                            trigger_type=trigger_info.trigger_type,
                            trigger_expr=trigger_info.trigger_expr,
                            func_name=func_name,
                            func=func,
                            kwargs=trigger_info.kwargs,
                            automation_id=self.automation_id,
                            constraints=trigger_info.constraints,
                            action_name=definition.name,
                            execution_mode=definition.execution_mode,
                            timeout=definition.timeout,
                            logger=self._logger,
                        )
                    )

        if metadata.is_startup:
            if self._startup_func is not None:
                raise AutomationDefinitionError(
                    f"More than one @startup handler: '{self._startup_name}' and '{func_name}'"
                )
            self._startup_func, self._startup_name = func, func_name

        if metadata.is_shutdown:
            if self._shutdown_func is not None:
                raise AutomationDefinitionError(
                    f"More than one @shutdown handler: '{self._shutdown_name}' and '{func_name}'"
                )
            self._shutdown_func, self._shutdown_name = func, func_name

    @staticmethod
    def _check_expressions(func_name: str, trigger_info: TriggerInfo) -> None:
        """Check the state expressions of a trigger, so that a mistake is found at start.

        Raises:
            AutomationDefinitionError: If a state expression is not valid.
        """
        expressions = [trigger_info.constraints.get(name) for name in ("when", "when_not")]
        if trigger_info.trigger_type == const.TRIGGER_STATE:
            expressions.append(trigger_info.trigger_expr)
        for expression in expressions:
            if isinstance(expression, str):
                try:
                    parse_expression(expression)
                except AutomationSyntaxError as err:
                    raise AutomationDefinitionError(f"'{func_name}': {err}") from None

    def make_event(
        self,
        *,
        caller: str | None = None,
        data: dict[str, Any] | None = None,
        source: str | None = None,
    ) -> ActionEvent:
        """Build the event for a direct call of one of this automation's functions.

        Args:
            caller: ID of the calling automation, for a call from an automation.
            data: The arguments of the call. They become ``event.data``, by
                reference: the action sees the caller's objects.
            source: ``"trigger"`` for a call by the engine itself (the lifecycle
                handlers). Otherwise the source follows from ``caller``.

        Returns:
            An ``AutomationEvent`` if there is a caller, a plain ``ActionEvent``
            for ``source="trigger"``, else a ``ManualEvent``.
        """
        fields: dict[str, Any] = {
            "call_time": self.host.clock.now(),
            "automation_id": self.automation_id,
            "data": data if data is not None else {},
        }
        if caller is not None:
            return AutomationEvent(caller=caller, **fields)
        if source == SOURCE_TRIGGER:
            return ActionEvent(source=SOURCE_TRIGGER, **fields)
        return ManualEvent(**fields)

    @property
    def logger(self) -> logging.Logger:
        """The automation's logger: where its own log calls and its failures are written."""
        return self._logger

    async def run_action(
        self,
        action_name: str,
        data: dict[str, Any] | None = None,
        *,
        caller: str | None = None,
    ) -> Any:
        """Run an action directly, outside the lifecycle and the worker pool.

        Args:
            action_name: A name of the action.
            data: The arguments of the call; delivered as ``event.data``.
            caller: ID of the calling automation. Without it the call is a
                manual one.

        Returns:
            The return value of the action.

        Raises:
            ActionNotFoundError: If the automation has no such action or it is disabled.
            Exception: Whatever the action raises.
        """
        action = self.get_action(action_name)
        if action is None or action.disabled:
            raise ActionNotFoundError(self.automation_id, action_name)

        event = self.make_event(caller=caller, data=data)
        _LOGGER.debug("Running action '%s' (%s)", action.name, event.source)
        return await as_coroutine_function(action.func)(*event_arguments(action.func, event))

    def get_action(self, name: str) -> ActionDefinition | None:
        """Get one action by its name or one of its aliases.

        Args:
            name: A name of the action.

        Returns:
            The action definition, or None if the automation has no action by
            that name. A disabled action is returned; it is listed but cannot
            be called.
        """
        return self._action_names.get(name)

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
    def is_loaded(self) -> bool:
        """Check if the automation is loaded: its files have passed the checks."""
        return self._metadata is not None

    @property
    def is_executed(self) -> bool:
        """Check if the automation's code has been run and its namespace exists."""
        return self._evaluator is not None

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
