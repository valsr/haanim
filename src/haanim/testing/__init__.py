"""Test support for HAAnim: the automation harness and in-memory implementations of the host interfaces."""

from haanim.testing import fakes as _fakes
from haanim.testing.fakes import (
    FakeAutomationRegistry,
    FakeClock,
    FakeEventBus,
    FakeFileSystem,
    FakeAssetSigner,
    FakeCardSink,
    FakeEntitySink,
    FakeIssueReporter,
    FakeServiceCaller,
    FakeStateProvider,
    FakeStatistics,
    FakeStorage,
    FakeSunProvider,
    LocalFileSystem,
    ServiceCallRecord,
    make_host,
)

from haanim.testing.harness import (
    AutomationCall,
    AutomationHarness,
    HarnessCard,
    HarnessError,
    HarnessFailure,
)

__all__ = ["AutomationCall", "AutomationHarness", "HarnessCard", "HarnessError", "HarnessFailure"]
__all__ += _fakes.__all__
