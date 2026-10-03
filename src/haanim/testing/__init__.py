"""Test support for HAAnim: in-memory implementations of the host interfaces."""

from haanim.testing.fakes import (
    FakeAutomationRegistry,
    FakeClock,
    FakeEventBus,
    FakeFileSystem,
    FakeIssueReporter,
    FakeServiceCaller,
    FakeStateProvider,
    FakeStorage,
    FakeSunProvider,
    LocalFileSystem,
    ServiceCallRecord,
    make_host,
)

__all__ = [
    "FakeAutomationRegistry",
    "FakeClock",
    "FakeEventBus",
    "FakeFileSystem",
    "FakeIssueReporter",
    "FakeServiceCaller",
    "FakeStateProvider",
    "FakeStorage",
    "FakeSunProvider",
    "LocalFileSystem",
    "ServiceCallRecord",
    "make_host",
]
