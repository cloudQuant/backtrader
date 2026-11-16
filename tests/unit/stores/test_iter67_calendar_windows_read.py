"""SDK calendar-store Windows read path through an injected fake lock backend.

macOS cannot execute the Windows branch: the SDK module imports no ``msvcrt``
here, so these tests replace the module's ``fcntl`` and ``msvcrt`` globals with a
fake backend and exercise the same code path.  The Windows native run is
**NOT_RUN**; no Windows behavior is claimed from these code-path tests.
"""

import os

import pytest

import bt_api_py.trading_calendar_store as store_module
from bt_api_py.trading_calendar_runtime_status import TradingCalendarStatusReader
from bt_api_py.trading_calendar_store import (
    CalendarStoreError,
    TradingCalendarStore,
)

from tests.unit.stores.test_iter67_trading_calendar_status import publish

ROUTE = "CTP___FUTURE"


class FakeMsvcrt:
    """The ``msvcrt`` surface used by the read path, with recorded calls."""

    LK_NBRLCK = 1
    LK_UNLCK = 2

    def __init__(self, *, busy=False):
        self.calls = []
        self.busy = busy

    def locking(self, fd, mode, nbytes):
        self.calls.append((mode, nbytes))
        if mode == self.LK_NBRLCK and self.busy:
            raise OSError("shared lock is held by a writer")


def inject(monkeypatch, backend):
    monkeypatch.setattr(store_module, "fcntl", None)
    monkeypatch.setattr(store_module, "msvcrt", backend)


@pytest.fixture
def published(tmp_path):
    root = tmp_path / "calendars/ctp"
    root.mkdir(parents=True)
    publish(root)
    return root


def test_injected_windows_backend_reads_the_same_snapshot_as_posix(monkeypatch, published):
    expected = TradingCalendarStore(published).read_current_with_consistent_receipts()
    backend = FakeMsvcrt()
    inject(monkeypatch, backend)

    observed = TradingCalendarStore(published).read_current_with_consistent_receipts()

    assert observed == expected
    assert backend.calls == [(backend.LK_NBRLCK, 1), (backend.LK_UNLCK, 1)]


def test_injected_windows_backend_honors_the_read_budget(monkeypatch, published):
    from bt_api_py.trading_calendar_store import CalendarReadBudget

    backend = FakeMsvcrt()
    inject(monkeypatch, backend)
    budget = CalendarReadBudget(64, 128, 2)
    with pytest.raises(CalendarStoreError, match="current receipt consistency unavailable"):
        TradingCalendarStore(published).read_current_with_consistent_receipts(budget=budget)
    assert backend.calls[-1] == (backend.LK_UNLCK, 1)


def test_status_reader_observes_current_through_the_injected_backend(monkeypatch, published):
    reader = TradingCalendarStatusReader()
    reader.configure({ROUTE: str(published)})
    backend = FakeMsvcrt()
    inject(monkeypatch, backend)

    status = reader.status(ROUTE)

    assert (status.status, status.reason) == (
        "OBSERVED_UNAUTHENTICATED",
        "CURRENT_RECEIPTS_CONSISTENT",
    )
    assert status.published == "CURRENT_OBSERVED"


def test_a_held_shared_lock_fails_closed(monkeypatch, published):
    inject(monkeypatch, FakeMsvcrt(busy=True))
    with pytest.raises(CalendarStoreError, match="current receipt consistency unavailable"):
        TradingCalendarStore(published).read_current_with_consistent_receipts()


class NoPrimitives:
    """A backend whose ``locking`` exists but whose lock constants do not."""

    def locking(self, fd, mode, nbytes):
        raise AssertionError("a backend without lock constants must not be used")


@pytest.mark.parametrize("backend", [None, object(), NoPrimitives()])
def test_a_missing_platform_primitive_fails_closed(monkeypatch, published, backend):
    inject(monkeypatch, backend)
    with pytest.raises(CalendarStoreError, match="current receipt consistency unavailable"):
        TradingCalendarStore(published).read_current_with_consistent_receipts()


def test_windows_read_rejects_a_symlinked_lock(monkeypatch, published):
    real = published / "lock-real"
    (published / ".lock").rename(real)
    try:
        os.symlink(real, published / ".lock")
    except (OSError, NotImplementedError):  # pragma: no cover - depends on the host
        pytest.skip("symlinks are unavailable")
    inject(monkeypatch, FakeMsvcrt())
    with pytest.raises(CalendarStoreError, match="current receipt consistency unavailable"):
        TradingCalendarStore(published).read_current_with_consistent_receipts()
