"""Helpers shared by the engine tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from haanim.engine.automation_context import AutomationContext
from haanim.engine.automation_status import AutomationStatusManager
from haanim.interfaces import Host
from haanim.testing import (
    FakeAutomationRegistry,
    FakeClock,
    FakeIssueReporter,
    FakeStorage,
    FakeSunProvider,
    LocalFileSystem,
    make_host,
)


def mock_host(states: Any = None, events: Any = None) -> Host:
    """Build a Host around mock state and event managers.

    For tests that assert on calls made to the state provider or event bus.
    The clock, sun and file system are fakes; services are a mock.

    Args:
        states: Object to use as the state provider. A MagicMock if omitted.
        events: Object to use as the event bus. A MagicMock if omitted.
    """
    clock = FakeClock()
    return Host(
        states=states if states is not None else MagicMock(),
        events=events if events is not None else MagicMock(),
        services=MagicMock(),
        clock=clock,
        sun=FakeSunProvider(),
        files=LocalFileSystem(),
        issues=FakeIssueReporter(),
        storage=FakeStorage(),
    )


def automation_file(root: Path, name: str) -> Path:
    """Create the folder of an automation and return the path of its ``main.py``.

    The file itself is not written; the test writes the source it needs.

    Args:
        root: The automations folder.
        name: Name of the automation's folder.
    """
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "main.py"


def make_context(automation_path: str, *, host: Host | None = None, **kwargs: Any) -> AutomationContext:
    """Build an AutomationContext for an automation on disk.

    Uses a fake host whose file system reads real files, a fresh status manager
    and an empty registry unless given. Storage goes next to the automation.

    Args:
        automation_path: Path of the automation's folder, or of its ``main.py``.
        host: Host to use. A fake host reading real files if omitted.
        **kwargs: Passed on to AutomationContext, overriding the defaults.
    """
    folder = Path(automation_path)
    if folder.name == "main.py":
        folder = folder.parent
    defaults: dict[str, Any] = {
        "status_manager": AutomationStatusManager(),
        "storage_path": str(folder.parent / ".storage"),
        "registry": FakeAutomationRegistry(),
    }
    defaults.update(kwargs)
    return AutomationContext(
        host=host or make_host(files=LocalFileSystem()),
        automation_path=str(folder),
        **defaults,
    )


async def load_and_run(context: AutomationContext) -> Any:
    """Load an automation and run its ``main.py``, as starting it does.

    For tests of what an automation's code does. The lifecycle itself (startup
    handler, triggers, states) is not involved.

    Args:
        context: The automation's context.

    Returns:
        The automation's metadata, with its actions and triggers.
    """
    await context.load()
    return await context.execute()


async def fire_trigger(manager: Any, trigger_id: str) -> None:
    """Fire a registered trigger now, as it does itself when its condition is met.

    The action is requested through the dispatcher, with the action's mode
    and timeout, and with a plain trigger event.
    """
    from haanim.events import ActionEvent  # pylint: disable=import-outside-toplevel

    trigger = manager.get_trigger(trigger_id)
    # pylint: disable-next=protected-access
    await trigger._execute_function(trigger._event(ActionEvent))
