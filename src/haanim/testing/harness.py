"""A harness for testing an automation with ``pytest`` and no Home Assistant.

The harness loads an automation folder exactly as the runtime does (the same
interpreter, import restrictions, triggers and ``haa`` instance) against the
fakes of ``haanim.testing``::

    from haanim.testing import AutomationHarness

    async def test_high_temperature_alert():
        async with AutomationHarness("automations/climate") as automation:
            automation.set_state("sensor.temperature", "25")
            automation.set_state("sensor.temperature", "31")
            await automation.wait_idle()
            assert automation.service_calls("notify.mobile_app")
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any
from zoneinfo import ZoneInfo

from haanim.engine.action_dispatcher import ActionDispatcher
from haanim.engine.action_pool import ActionWorkerPool
from haanim.engine.automation_context import ActionDefinition, AutomationContext
from haanim.engine.automation_status import AutomationStatusManager
from haanim.engine.card import CARD_PARTS
from haanim.engine.control import AutomationControl, EnabledFlags
from haanim.engine.discovery import ASSETS_DIRNAME
from haanim.engine.errors import (
    ActionNotFoundError,
    HAAnimError,
    NonExistingAutomationError,
)
from haanim.engine.lifecycle import ActionFailure, Automation, AutomationState, LifecycleSettings
from haanim.engine.triggers import TriggerManager
from haanim.engine.variables import storage_key
from haanim.events import SOURCE_AUTOMATION, SOURCE_MANUAL, SOURCE_TRIGGER, ActionEvent
from haanim.interfaces import AutomationTimes, Host
from haanim.testing.fakes import (
    FakeCardSink,
    FakeClock,
    FakeEventBus,
    FakeServiceCaller,
    FakeStateProvider,
    FakeStorage,
    FakeSunProvider,
    LocalFileSystem,
    ServiceCallRecord,
    make_host,
)
from haanim.types import EventData

__all__ = ["AutomationCall", "AutomationHarness", "HarnessCard", "HarnessError"]

# How often wait_idle lets the event loop run before it gives up on actions that do not finish
IDLE_ROUNDS = 200

# How often a lifecycle step gets the event loop before the clock is moved for it, and by how much
DRIVE_ROUNDS = 20
DRIVE_STEP_SECONDS = 0.5


class HarnessError(Exception):
    """The harness was used in a way that cannot work, or the automation did not do what was waited for."""


@dataclass(frozen=True)
class AutomationCall:
    """One call the automation made to an action of another (stubbed) automation.

    Args:
        automation_id: ID of the automation that was called.
        action: Name of the action.
        data: The arguments of the call.
        caller: ID of the calling automation.
    """

    automation_id: str
    action: str
    data: dict[str, Any] = field(default_factory=dict)
    caller: str | None = None


@dataclass(frozen=True)
class HarnessCard:
    """The content of the automation's card at one moment.

    Args:
        blocks: The blocks in order, each a dictionary with ``id``, ``type`` and its content.
        title: The title the automation gave the card; None while it shows the automation's name.
        options: Which fixed parts of the card are shown: ``title``, ``state``,
            ``message``, ``actions`` and ``log``.
    """

    blocks: list[dict[str, Any]] = field(default_factory=list)
    title: str | None = None
    options: dict[str, bool] = field(default_factory=lambda: dict.fromkeys(CARD_PARTS, True))

    def block(self, block_id: str) -> dict[str, Any]:
        """Return the block with an ID.

        Raises:
            KeyError: If the card has no such block.
        """
        for block in self.blocks:
            if block["id"] == block_id:
                return block
        raise KeyError(block_id)


class _Services(FakeServiceCaller):
    """Services that all exist unless a test says one is missing."""

    def __init__(self) -> None:
        super().__init__()
        self._missing: set[tuple[str, str]] = set()

    def has_service(self, domain: str, service: str) -> bool:
        """Return whether the service exists: every one does that was not marked missing."""
        return (domain, service) not in self._missing

    async def async_call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any] | None = None,
        *,
        return_response: bool = False,
    ) -> dict[str, Any] | None:
        """Record the call; a service nobody stubbed succeeds without a response."""
        key = (domain, service)
        if key not in self._missing and key not in self._services:
            self.register(domain, service)
        return await super().async_call(domain, service, data, return_response=return_response)

    def remove(self, domain: str, service: str) -> None:
        """Make a service not exist."""
        key = (domain, service)
        self._missing.add(key)
        self._services.pop(key, None)
        self._responses.pop(key, None)
        self._failures.pop(key, None)

    def restore(self, domain: str, service: str) -> None:
        """Make a service exist again."""
        self._missing.discard((domain, service))


class _Files(LocalFileSystem):
    """The real files of the automation, with assets from an in-memory mapping in front of them."""

    def __init__(self, assets_root: Path, assets: dict[str, bytes | str]) -> None:
        self._contents = {
            assets_root.joinpath(*name.split("/")): (
                content.encode("utf-8") if isinstance(content, str) else content
            )
            for name, content in assets.items()
        }

    def exists(self, path: Path) -> bool:
        """Return whether the path exists on disk or in the mapping."""
        return Path(path) in self._contents or self.is_dir(path) or super().exists(path)

    def is_dir(self, path: Path) -> bool:
        """Return whether the path is a directory on disk or has mapped files below it."""
        return any(Path(path) in mapped.parents for mapped in self._contents) or super().is_dir(path)

    def size(self, path: Path) -> int:
        """Return the size of a file in bytes."""
        mapped = self._contents.get(Path(path))
        return len(mapped) if mapped is not None else super().size(path)

    async def read_text(self, path: Path) -> str:
        """Return a file's contents decoded as UTF-8."""
        mapped = self._contents.get(Path(path))
        return mapped.decode("utf-8") if mapped is not None else await super().read_text(path)

    async def read_bytes(self, path: Path) -> bytes:
        """Return a file's contents."""
        mapped = self._contents.get(Path(path))
        return mapped if mapped is not None else await super().read_bytes(path)


class _StubContext:
    """Stands in for the context of another automation that a test stubbed."""

    def __init__(self, automation_id: str) -> None:
        self.automation_id = automation_id

    def get_metadata(self) -> None:
        """A stub has no metadata."""

    def get_actions(self) -> list[ActionDefinition]:
        """A stub lists no actions."""
        return []

    def get_action(self, name: str) -> None:  # noqa: ARG002
        """A stub has no action definitions."""


def _split(name: str) -> tuple[str, str]:
    """Split ``"domain.service"`` into its two parts."""
    domain, dot, service = name.partition(".")
    if not dot or not domain or not service:
        raise ValueError(f"A service is named 'domain.service', not {name!r}")
    return domain, service


def _start_time(now: str | datetime | None, time_zone: str) -> datetime | None:
    """Turn the ``now`` argument into a timezone-aware datetime."""
    if now is None:
        return None
    moment = datetime.fromisoformat(now) if isinstance(now, str) else now
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=ZoneInfo(time_zone))


class AutomationHarness:  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """One automation running against a fake Home Assistant.

    Use it as an async context manager: entering loads and starts the
    automation, leaving stops and unloads it. Time stands still until the test
    moves it with ``advance_time``.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        folder: str | Path,
        *,
        now: str | datetime | None = None,
        time_zone: str = "UTC",
        automation_id: str | None = None,
        start: bool = True,
        states: dict[str, Any] | None = None,
        variables: dict[str, Any] | None = None,
        assets: dict[str, bytes | str] | None = None,
        sunrise: str | None = "07:00",
        sunset: str | None = "19:00",
        additional_imports: list[str] | None = None,
        allow_all_imports: bool = False,
        settings: LifecycleSettings | None = None,
    ) -> None:
        """Set up the fake Home Assistant for an automation. Nothing is loaded yet.

        Args:
            folder: The automation's folder, which holds its ``main.py``.
            now: The time the clock starts at, as a datetime or ISO text
                (``"2025-01-06 08:59:00"``). Monday 2025-01-06 12:00 if omitted.
            time_zone: The time zone of a ``now`` that names none.
            automation_id: The automation's ID. Derived from the folder name if omitted.
            start: Load and start the automation on entering. With False the
                test drives the lifecycle itself.
            states: Entity states that exist before the automation starts:
                ``{"sensor.x": "21"}`` or ``{"sensor.x": ("21", {"unit": "C"})}``.
            variables: The automation's stored variables before it starts.
            assets: Assets served from memory, by name relative to ``assets/``,
                in addition to the files in the folder's own ``assets/``.
            sunrise: Time of sunrise as ``HH:MM``; None for no sunrise.
            sunset: Time of sunset as ``HH:MM``; None for no sunset.
            additional_imports: Modules the automation may import in addition to the default allowlist.
            allow_all_imports: Disable the import allowlist.
            settings: The lifecycle's time limits. The design's defaults if omitted.
        """
        self.folder = Path(folder)
        self._start_on_enter = start
        self._initial_variables = dict(variables) if variables is not None else None
        started_at = _start_time(now, time_zone)
        self.clock = FakeClock(started_at) if started_at is not None else FakeClock()
        self._services = _Services()
        self._sun = FakeSunProvider(sunrise, sunset)
        self._storage = FakeStorage()
        self._cards = FakeCardSink()
        self._states = FakeStateProvider(self.clock)
        self._bus = FakeEventBus(self.clock)
        self.host: Host = make_host(
            states=self._states,
            events=self._bus,
            clock=self.clock,
            services=self._services,
            sun=self._sun,
            files=_Files(self.folder / ASSETS_DIRNAME, assets or {}),
            storage=self._storage,
            cards=self._cards,
        )
        for entity_id, value in (states or {}).items():
            if isinstance(value, tuple):
                self.set_state(entity_id, value[0], value[1])
            else:
                self.set_state(entity_id, value)

        self._status = AutomationStatusManager()
        self._pool = ActionWorkerPool(status_manager=self._status, clock=self.clock)
        self._dispatcher = ActionDispatcher(self._pool)
        self._triggers = TriggerManager(self.host, self._dispatcher)
        self._flags = EnabledFlags(self._storage)
        self._control = AutomationControl(self._flags, self._dispatcher)
        self._context = AutomationContext(
            host=self.host,
            automation_path=str(self.folder),
            automation_id=automation_id,
            status_manager=self._status,
            registry=self,
            additional_imports=additional_imports,
            allow_all_imports=allow_all_imports,
        )
        self._automation = Automation(
            self._context, dispatcher=self._dispatcher, triggers=self._triggers, settings=settings
        )
        limits = settings or LifecycleSettings()
        # No step of the lifecycle waits longer than its three limits together
        self._longest_wait = limits.startup_timeout + limits.shutdown_timeout + limits.stop_grace_period + 1.0
        self._stubs: dict[str, dict[str, Any]] = {}
        self._automation_calls: list[AutomationCall] = []
        self._records: list[logging.LogRecord] = []
        self._handler = _Recorder(self._records)
        self._logger_level: int | None = None
        self._closed = False

    # --- Context manager ---------------------------------------------------------

    async def __aenter__(self) -> AutomationHarness:
        """Load and start the automation, unless the harness was made with ``start=False``.

        Raises:
            HAAnimError: If the automation cannot be loaded or started; the message says why.
        """
        logger = self._context.logger
        self._logger_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.addHandler(self._handler)
        await self._flags.load()
        if self._initial_variables is not None:
            await self._storage.save(storage_key(self.automation_id), self._initial_variables)
        if self._start_on_enter:
            try:
                if not await self.load() or not await self.start():
                    raise HAAnimError(self.error or f"Automation '{self.automation_id}' did not start")
            except BaseException:
                await self.close()
                raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Stop and unload the automation and stop everything the harness started."""
        await self.close()

    async def close(self) -> None:
        """Stop and unload the automation. Does nothing the second time."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._automation.state is not AutomationState.UNAVAILABLE:
                await self.unload()
            await self._triggers.async_teardown()
            await self._dispatcher.shutdown()
        finally:
            logger = self._context.logger
            logger.removeHandler(self._handler)
            if self._logger_level is not None:
                logger.setLevel(self._logger_level)

    # --- Lifecycle ---------------------------------------------------------------

    @property
    def automation_id(self) -> str:
        """The automation's ID."""
        return self._context.automation_id

    @property
    def state(self) -> str:
        """The automation's state: ``unavailable``, ``off``, ``on`` or ``error``."""
        return self._automation.state.value

    @property
    def error(self) -> str | None:
        """Why the automation is in the ``error`` state; None in every other state."""
        return self._automation.message

    @property
    def last_error(self) -> ActionFailure | None:
        """The most recent failure of a trigger-fired action or of ``@shutdown``; None if there was none."""
        return self._automation.last_error

    @property
    def message(self) -> str | None:
        """The status message the automation set with ``haa.set_message()``; None if it set none."""
        metadata = self._context.get_metadata()
        return metadata.message if metadata else None

    @property
    def enabled(self) -> bool:
        """Whether the automation is enabled."""
        return self._control.is_enabled(self.automation_id)

    @property
    def actions(self) -> list[str]:
        """The names of the automation's actions; empty unless it is running."""
        return [action.name for action in self._context.get_actions()]

    async def load(self) -> bool:
        """Load the automation: read its metadata and check its code. Returns whether that worked."""
        return await self._automation.load()

    async def start(self) -> bool:
        """Start the automation: run ``main.py`` and ``@startup``, register the triggers.

        A ``@startup`` that sleeps or waits gets the time it needs: the clock
        moves forward until it has finished or reached the startup timeout.

        Returns:
            Whether the automation started.
        """
        started = await self._drive(self._automation.start())
        await self.clock.settle()
        return bool(started)

    async def stop(self) -> None:
        """Stop the automation: triggers, running actions, ``@shutdown``.

        Actions that are still running get their grace period and are then
        cancelled, as in Home Assistant. The clock moves forward by the time that takes.
        """
        await self._drive(self._automation.stop())

    async def unload(self) -> None:
        """Unload the automation, stopping it first if it runs."""
        await self._drive(self._automation.unload())

    async def restart(self) -> bool:
        """Stop and start the automation. Returns whether it started."""
        await self.stop()
        return await self.start()

    async def reload(self) -> bool:
        """Do what a change of the automation's files does: stop, unload, load and start.

        Returns:
            Whether the automation started.
        """
        if self._automation.state is not AutomationState.UNAVAILABLE:
            await self.unload()
        return await self.load() and await self.start()

    async def _drive(self, step: Coroutine[Any, Any, Any]) -> Any:
        """Run a lifecycle step to its end, moving the clock when the step waits for time to pass.

        Time only moves if the step has not finished after the event loop had
        its turns: a step that waits for nothing leaves the clock alone.

        Raises:
            HarnessError: If the step has not finished after every time limit of the lifecycle has passed.
        """
        task = asyncio.ensure_future(step)
        try:
            for _ in range(DRIVE_ROUNDS):
                await self.clock.settle()
                if task.done():
                    return task.result()
            waited = 0.0
            while waited <= self._longest_wait:
                await self.clock.advance(seconds=DRIVE_STEP_SECONDS)
                waited += DRIVE_STEP_SECONDS
                if task.done():
                    return task.result()
        except BaseException:
            task.cancel()
            raise
        task.cancel()
        raise HarnessError("A lifecycle step did not finish within the lifecycle's own time limits")

    # --- States, events and time -------------------------------------------------

    @property
    def states(self) -> FakeStateProvider:
        """The fake entity states, for what ``set_state`` does not cover."""
        return self._states

    @property
    def bus(self) -> FakeEventBus:
        """The fake event bus."""
        return self._bus

    def set_state(self, entity_id: str, state: Any, attributes: dict[str, Any] | None = None) -> None:
        """Set the state and attributes of an entity. Triggers react when the test next awaits the harness."""
        self.states.set_state(entity_id, str(state), attributes)

    def remove_state(self, entity_id: str) -> None:
        """Make an entity not exist."""
        self.states.remove(entity_id)

    def get_state(self, entity_id: str) -> str | None:
        """Return the state of an entity; None if it does not exist."""
        return self.states.get(entity_id).state

    def fire_event(
        self, event_type: str, data: dict[str, Any] | None = None, *, user_id: str | None = None
    ) -> None:
        """Fire an event on the bus. Triggers react when the test next awaits the harness."""
        self.bus.fire(event_type, data, user_id=user_id)

    @property
    def now(self) -> datetime:
        """The current time of the frozen clock."""
        return self.clock.now()

    async def advance_time(self, delta: timedelta | None = None, **kwargs: float) -> datetime:
        """Move the clock forward, firing every trigger, sleep and timeout that falls due on the way.

        Args:
            delta: How far to move, or pass ``timedelta`` keyword arguments instead (``minutes=2``).
            **kwargs: Keyword arguments for ``timedelta``.

        Returns:
            The new time.
        """
        moment = await self.clock.advance(delta, **kwargs)
        await self.clock.settle()
        return moment

    def set_sun(self, sunrise: str | None = "07:00", sunset: str | None = "19:00") -> None:
        """Change when the sun rises and sets, as ``HH:MM``; None for a day without that event.

        Triggers that are already waiting for a sunrise or sunset keep the time they were scheduled for.
        """
        self._sun.set_times(sunrise, sunset)

    async def wait_idle(self) -> None:
        """Wait until every dispatched action has finished and nothing is left to react to.

        Time does not move: an action that sleeps or waits has to be helped
        along with ``advance_time``.

        Raises:
            HarnessError: If actions are still running after the event loop had its turns.
        """
        for _ in range(IDLE_ROUNDS):
            await self.clock.settle()
            if self._dispatcher.is_idle():
                await self.clock.settle()
                if self._dispatcher.is_idle():
                    return
        running = sorted(self._status.get_status(self.automation_id).running_actions.values())
        raise HarnessError(
            f"Actions are still running: {', '.join(running) or 'unknown'}. "
            "If they sleep or wait for a timeout, move time with advance_time()."
        )

    # --- Actions -----------------------------------------------------------------

    async def call(
        self,
        action_name: str,
        *,
        source: str = SOURCE_MANUAL,
        caller: str | None = None,
        event: ActionEvent | None = None,
        **data: Any,
    ) -> Any:
        """Call an action directly and return what it returns.

        Args:
            action_name: A name of the action, or of a trigger function.
            source: How the call looks to the action: ``"manual"`` (the default),
                ``"automation"`` (needs ``caller``) or ``"trigger"``.
            caller: ID of the automation the call seems to come from; implies ``source="automation"``.
            event: The exact event to call the action with, for instance a
                ``StateEvent`` for a state trigger function. Overrides the rest.
            **data: The arguments of the call; the action gets them as ``event.data``.

        Raises:
            ValueError: If the source is unknown, or ``"automation"`` without a caller.
            Exception: Whatever the call raises: the HAAnim errors and what the action itself raises.
        """
        if caller is not None:
            source = SOURCE_AUTOMATION
        if source not in (SOURCE_MANUAL, SOURCE_AUTOMATION, SOURCE_TRIGGER):
            raise ValueError(f"Unknown source {source!r}")
        if source == SOURCE_AUTOMATION and caller is None:
            raise ValueError("A call with source 'automation' needs a caller")
        if event is None and source == SOURCE_TRIGGER:
            event = ActionEvent(
                call_time=self.clock.now(), automation_id=self.automation_id, source=SOURCE_TRIGGER, data=data
            )
        return await self._automation.call_action(action_name, data, caller=caller, event=event)

    # --- Services ----------------------------------------------------------------

    def service_calls(self, name: str | None = None) -> list[ServiceCallRecord]:
        """Return the service calls the automation made, oldest first.

        Args:
            name: Only the calls to this service, as ``"domain.service"``. All calls if omitted.
        """
        if name is None:
            return list(self._services.calls)
        return self._services.calls_to(*_split(name))

    def stub_service(
        self,
        name: str,
        *,
        response: dict[str, Any] | None = None,
        success: bool = True,
        reason: str = "failed",
    ) -> None:
        """Decide what a service does when the automation calls it.

        Without a stub every service exists, succeeds and returns no response.

        Args:
            name: The service as ``"domain.service"``.
            response: The response data given to callers that ask for it.
            success: With False the call fails: the automation gets a result
                whose ``success`` is False and whose ``error`` has the reason.
            reason: The reason of that failure.
        """
        domain, service = _split(name)
        self._services.restore(domain, service)
        self._services.register(domain, service, response=response)
        if not success:
            self._services.fail(domain, service, reason)

    def remove_service(self, name: str) -> None:
        """Make a service not exist, as ``"domain.service"``."""
        self._services.remove(*_split(name))

    # --- Other automations -------------------------------------------------------

    def stub_automation(self, automation_id: str, **actions: Any) -> None:
        """Make another automation exist, with the given actions.

        Args:
            automation_id: ID of the other automation.
            **actions: What each action returns: a value, or a function that
                is called with the arguments of the call (it may be a coroutine function).
        """
        self._stubs[automation_id] = dict(actions)

    def automation_calls(self, automation_id: str | None = None) -> list[AutomationCall]:
        """Return the calls made to stubbed automations, oldest first; to one of them if an ID is given."""
        return [
            call
            for call in self._automation_calls
            if automation_id is None or call.automation_id == automation_id
        ]

    # --- What the automation did -------------------------------------------------

    def events(self, event_type: str | None = None) -> list[EventData]:
        """Return the events fired on the bus, oldest first; of one type if given.

        That includes the events the test fired itself and ``haanim_action_error``.
        """
        return [event for event in self.bus.fired if event_type is None or event.event_type == event_type]

    @property
    def log_records(self) -> list[logging.LogRecord]:
        """Everything the automation logged or printed, oldest first, as log records."""
        return list(self._records)

    def logs(self, level: int | str | None = None) -> list[str]:
        """Return the formatted messages the automation logged, oldest first.

        Args:
            level: Only records of exactly this level (``"WARNING"`` or ``logging.WARNING``). All if omitted.
        """
        wanted = logging.getLevelName(level) if isinstance(level, int) else level
        return [
            record.getMessage() for record in self._records if wanted is None or record.levelname == wanted
        ]

    @property
    def variables(self) -> dict[str, Any]:
        """A copy of the automation's stored variables, as they are now."""
        store = self._context.variables
        if store is not None:
            return {key: store.get(key) for key in store.keys()}
        stored = self._storage.peek(storage_key(self.automation_id))
        return dict(stored) if isinstance(stored, dict) else {}

    def get_variable(self, key: str, default: Any = None) -> Any:
        """Return one stored variable of the automation, or the default if it is not set."""
        return self.variables.get(key, default)

    # --- Card --------------------------------------------------------------------

    @property
    def card(self) -> HarnessCard:
        """The content of the automation's card now; empty while the automation is not running."""
        haa = self._context._haa  # pylint: disable=protected-access
        if haa is None:
            return HarnessCard()
        return HarnessCard(haa.card.blocks, haa.card.title, haa.card.options)

    @property
    def card_updates(self) -> list[list[dict[str, Any]]]:
        """Every update of the card that was sent to the frontend, oldest first."""
        return [blocks for _, blocks in self._cards.updates]

    async def press(self, block_id: str) -> Any:
        """Press a button on the automation's card and return what its action returns.

        The action is called as the card does it: a manual call with the
        button's data. A confirmation is taken as given.

        Raises:
            KeyError: If the card has no such block.
            HarnessError: If the block is not a button.
        """
        block = self.card.block(block_id)
        if block["type"] != "button":
            raise HarnessError(f"Block '{block_id}' is a {block['type']} block, not a button")
        return await self.call(block["action"], **block["data"])

    # --- AutomationRegistry: what haa sees of the automations ---------------------

    def get_all_contexts(self) -> list[Any]:
        """Return the contexts of the automation and of the stubbed ones."""
        return [self._context, *(_StubContext(automation_id) for automation_id in self._stubs)]

    def get_context_by_name(self, automation_id: str) -> Any:
        """Return the context of an automation, or None."""
        if automation_id == self.automation_id:
            return self._context
        return _StubContext(automation_id) if automation_id in self._stubs else None

    async def async_call_action(
        self,
        automation_id: str,
        action_name: str,
        data: dict[str, Any] | None = None,
        *,
        caller: str | None = None,
    ) -> Any:
        """Call an action of the automation, or of a stubbed one."""
        if automation_id == self.automation_id:
            return await self._automation.call_action(action_name, data, caller=caller)
        if automation_id not in self._stubs:
            raise NonExistingAutomationError(automation_id)
        self._automation_calls.append(AutomationCall(automation_id, action_name, dict(data or {}), caller))
        actions = self._stubs[automation_id]
        if action_name not in actions:
            raise ActionNotFoundError(automation_id, action_name)
        outcome = actions[action_name]
        if callable(outcome):
            outcome = outcome(**(data or {}))
            if inspect.isawaitable(outcome):
                outcome = await outcome
        return outcome

    def _own(self, automation_id: str) -> Automation:
        if automation_id != self.automation_id:
            raise NonExistingAutomationError(automation_id)
        return self._automation

    async def async_enable_automation(self, automation_id: str) -> None:
        """Enable and start the automation."""
        await self._control.enable(self._own(automation_id))

    async def async_disable_automation(self, automation_id: str) -> None:
        """Stop and disable the automation."""
        await self._control.disable(self._own(automation_id))

    async def async_start_automation(self, automation_id: str) -> None:
        """Start the automation."""
        await self._control.start(self._own(automation_id))

    async def async_stop_automation(self, automation_id: str) -> None:
        """Stop the automation."""
        await self._control.stop(self._own(automation_id))

    async def async_restart_automation(self, automation_id: str) -> None:
        """Restart the automation."""
        await self._control.restart(self._own(automation_id))

    def automation_state(self, automation_id: str) -> str:
        """Return the state of an automation; a stubbed one is ``on``."""
        if automation_id == self.automation_id:
            return self.state
        return AutomationState.ON.value if automation_id in self._stubs else AutomationState.UNAVAILABLE.value

    def automation_message(self, automation_id: str) -> str | None:
        """Return why an automation is in the ``error`` state, or None."""
        return self.error if automation_id == self.automation_id else None

    def is_automation_enabled(self, automation_id: str) -> bool:
        """Return whether an automation is enabled."""
        return self._control.is_enabled(automation_id)

    def automation_times(self, automation_id: str) -> AutomationTimes:
        """Return when an automation was loaded, last started and last ran an action."""
        return self._automation.times if automation_id == self.automation_id else AutomationTimes()


class _Recorder(logging.Handler):
    """Keeps every record it is given."""

    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__(logging.DEBUG)
        self._kept = records

    def emit(self, record: logging.LogRecord) -> None:
        """Keep the record."""
        self._kept.append(record)
