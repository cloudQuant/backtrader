"""Exercise the direct ledger hook's real crash windows with local fixtures.

These events are *not* Backtrader's ``notify_order`` / ``notify_trade``:
reconstructing those callbacks requires separate durable framework state.
"""

from __future__ import annotations

import multiprocessing
import os
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py.strategy_event_feed")

from bt_api_py.strategy_ledger import LedgerIntent, SqliteStrategyLedger  # noqa: E402
from backtrader.brokers.btapibroker import BtApiBroker  # noqa: E402

_ACCOUNT = "synthetic-ledger-account"
_INSTRUMENT = "PAPER:SIM:SA2701"


def _ledger(path):
    return SqliteStrategyLedger(path, account_ref=_ACCOUNT, require_budget=False)


class _Recorder:
    def __init__(self):
        self.events = []

    def notify_ledger_event(self, event):
        self.events.append(event)


class _ChildRecorder:
    def __init__(self, stage, observed_path):
        self.stage = stage
        self.observed_path = observed_path

    def notify_ledger_event(self, event):
        if self.stage == "before_hook":
            os._exit(71)
        # This file represents a strategy side effect. It is deliberately not
        # atomic with the cursor: a crash in between can repeat the side effect.
        with open(self.observed_path, "a", encoding="utf-8") as stream:
            stream.write(event.event_id + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if self.stage == "after_hook_before_cursor":
            os._exit(72)


def _run_child(ledger_path, cursor_path, observed_path, stage):
    ledger = _ledger(ledger_path)
    broker = BtApiBroker(store=SimpleNamespace())
    recorder = _ChildRecorder(stage, observed_path)
    broker._bind_strategy_ledger_events(recorder, ledger, "strategy-a", cursor_path)
    # The binding has delivered the event and saved the cursor at this point.
    os._exit(73)


@pytest.mark.parametrize(
    ("stage", "expected_exit", "already_observed", "expect_replay"),
    [
        ("before_hook", 71, False, True),
        ("after_hook_before_cursor", 72, True, True),
        ("after_cursor", 73, True, False),
    ],
)
def test_direct_ledger_hook_process_restart_keeps_scopes_and_event_identity(
    tmp_path, stage, expected_exit, already_observed, expect_replay
):
    ledger_path = tmp_path / "ledger.sqlite3"
    cursor_path = tmp_path / "strategy-a-cursor.sqlite3"
    observed_path = tmp_path / "child-side-effect.txt"
    ledger = _ledger(ledger_path)
    try:
        for strategy, intent in (("strategy-a", "intent-a"), ("strategy-b", "intent-b")):
            ledger.reserve(
                LedgerIntent(intent, strategy, _INSTRUMENT, "BUY", Decimal("1"), Decimal("1500"))
            )
        expected_a = ledger.read_events("strategy-a").events[0]
        expected_b = ledger.read_events("strategy-b").events[0]
    finally:
        ledger.close()

    context = multiprocessing.get_context("spawn")
    child = context.Process(
        target=_run_child,
        args=(str(ledger_path), str(cursor_path), str(observed_path), stage),
    )
    child.start()
    try:
        child.join(timeout=30)
        assert child.exitcode == expected_exit
    finally:
        # Only this test's freshly spawned synthetic process is controlled.
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)
        if child.exitcode is not None:
            child.close()

    observed = Path(observed_path).read_text(encoding="utf-8").splitlines() if observed_path.exists() else []
    assert observed == ([expected_a.event_id] if already_observed else [])

    ledger = _ledger(ledger_path)
    broker = BtApiBroker(store=SimpleNamespace())
    first = _Recorder()
    second = _Recorder()
    try:
        broker._bind_strategy_ledger_events(first, ledger, "strategy-a", str(cursor_path))
        assert [event.event_id for event in first.events] == (
            [expected_a.event_id] if expect_replay else []
        )
        assert all(event.strategy_ref == "strategy-a" for event in first.events)
        assert broker.deliver_strategy_ledger_events(first) == 0

        broker._bind_strategy_ledger_events(
            second, ledger, "strategy-b", str(tmp_path / "strategy-b-cursor.sqlite3")
        )
        assert [event.event_id for event in second.events] == [expected_b.event_id]
        assert second.events[0].strategy_ref == "strategy-b"
    finally:
        broker.close_strategy_ledger_events()
        ledger.close()
