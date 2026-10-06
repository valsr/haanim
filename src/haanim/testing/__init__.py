"""Test support for HAAnim: the automation harness and in-memory implementations of the host interfaces."""

from haanim.testing.fakes import (
    FakeAutomationRegistry,
    FakeClock,
    FakeEventBus,
    FakeFileSystem,
    FakeAssetSigner,
    FakeCardSink,
    FakeIssueReporter,
    FakeServiceCaller,
    FakeStateProvider,
    FakeStorage,
    FakeSunProvider,
    LocalFileSystem,
    ServiceCallRecord,
    make_host,
)

from haanim.testing.harness import AutomationCall, AutomationHarness, HarnessCard, HarnessError

__all__ = [
    "AutomationCall",
    "AutomationHarness",
    "HarnessCard",
    "HarnessError",
    "FakeAutomationRegistry",
    "FakeClock",
    "FakeEventBus",
    "FakeFileSystem",
    "FakeAssetSigner",
    "FakeCardSink",
    "FakeIssueReporter",
    "FakeServiceCaller",
    "FakeStateProvider",
    "FakeStorage",
    "FakeSunProvider",
    "LocalFileSystem",
    "ServiceCallRecord",
    "make_host",
]
