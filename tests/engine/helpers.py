"""Helpers shared by the engine tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from haanim.engine.automation_context import AutomationContext
from haanim.engine.automation_status import AutomationStatusManager
from haanim.interfaces import Host
from haanim.testing import FakeAutomationRegistry, FakeClock, FakeSunProvider, LocalFileSystem, make_host


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
    )


def make_context(automation_path: str, *, host: Host | None = None, **kwargs: Any) -> AutomationContext:
    """Build an AutomationContext for an automation file on disk.

    Uses a fake host whose file system reads real files, a fresh status manager
    and an empty registry unless given. Storage goes next to the automation file.

    Args:
        automation_path: Path to the automation file.
        host: Host to use. A fake host reading real files if omitted.
        **kwargs: Passed on to AutomationContext, overriding the defaults.
    """
    defaults: dict[str, Any] = {
        "status_manager": AutomationStatusManager(),
        "storage_path": str(Path(automation_path).parent / ".storage"),
        "registry": FakeAutomationRegistry(),
    }
    defaults.update(kwargs)
    return AutomationContext(
        host=host or make_host(files=LocalFileSystem()),
        automation_path=automation_path,
        **defaults,
    )
