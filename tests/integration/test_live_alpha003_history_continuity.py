"""Focused source-continuity projection tests for the 028 live runner."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace


_RUNNER = None
_SCOPES = {
    "account_scope": "history-continuity-account",
    "strategy_scope": "alpha003",
    "logical_run_id": "history-continuity-run",
}
_SOURCE_KIND = "ALPHA003_GRID"
_FILE_ID = "decision-tape-file-1"
_FINGERPRINT = "f" * 64
_RECORD_ID = "record-1"
_BATCH_ID = "batch-1"


def _load_runner():
    global _RUNNER
    if _RUNNER is not None:
        return _RUNNER

    root = Path(__file__).resolve().parents[2]
    example = root / "examples" / "unified" / "028_alpha003_simnow_minute"
    entry_path = example / "entry_tier.py"
    entry_spec = importlib.util.spec_from_file_location("entry_tier", entry_path)
    assert entry_spec is not None and entry_spec.loader is not None
    entry = importlib.util.module_from_spec(entry_spec)
    previous_entry = sys.modules.get("entry_tier")
    sys.modules["entry_tier"] = entry
    try:
        entry_spec.loader.exec_module(entry)
        runner_path = example / "run.py"
        runner_spec = importlib.util.spec_from_file_location(
            "i51_history_continuity_runner_source_test", runner_path
        )
        assert runner_spec is not None and runner_spec.loader is not None
        runner = importlib.util.module_from_spec(runner_spec)
        sys.modules[runner_spec.name] = runner
        runner_spec.loader.exec_module(runner)
    finally:
        if previous_entry is None:
            sys.modules.pop("entry_tier", None)
        else:
            sys.modules["entry_tier"] = previous_entry
    _RUNNER = runner
    return runner


class _DecisionTapeProjection:
    def __init__(self, record_count=1):
        self.file_id = _FILE_ID
        self.calendar_fingerprint = _FINGERPRINT
        self._record_count = record_count

    def summary(self):
        last = None
        if self._record_count:
            last = {
                "record_index": self._record_count,
                "record_id": _RECORD_ID,
                "batch_id": _BATCH_ID,
            }
        return {
            "record_count": self._record_count,
            "file_id": self.file_id,
            "last_record_reference": last,
        }


def _matching_highwater():
    receipt = SimpleNamespace(
        tape_file_id=_FILE_ID,
        tape_record_index=1,
        tape_record_id=_RECORD_ID,
        batch_id=_BATCH_ID,
        calendar_fingerprint=_FINGERPRINT,
    )
    return SimpleNamespace(anchor_kind="GRID", receipt=receipt)


class _JournalProjection:
    def __init__(self, highwater=None, error=None):
        self.highwater = highwater
        self.error = error
        self.calls = []

    def source_highwater(self, *args):
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.highwater


def test_sticky_strategy_failure_wins_over_matching_final_highwater():
    runner = _load_runner()
    journal = _JournalProjection(highwater=_matching_highwater())
    strategy = SimpleNamespace(
        source_continuity_failure_count=1,
        source_continuity_first_error="SOURCE_RECEIPT_WRITE_FAILED",
    )

    result = runner._live_source_continuity_status(
        journal, _SCOPES, _DecisionTapeProjection(), strategy
    )

    assert journal.calls == [
        (
            _SCOPES["account_scope"],
            _SCOPES["strategy_scope"],
            _SCOPES["logical_run_id"],
            _SOURCE_KIND,
        )
    ]
    assert result == {
        "status": "UNAVAILABLE",
        "available": False,
        "record_count": 1,
        "failure_count": 1,
        "first_error": "SOURCE_RECEIPT_WRITE_FAILED",
        "final_highwater_matches_tape": True,
    }


def test_zero_rows_do_not_read_source_highwater():
    runner = _load_runner()
    journal = _JournalProjection(error=AssertionError("unexpected HWM read"))

    result = runner._live_source_continuity_status(
        journal, _SCOPES, _DecisionTapeProjection(record_count=0), None
    )

    assert journal.calls == []
    assert result == {
        "status": "NOT_APPLICABLE",
        "available": False,
        "record_count": 0,
        "failure_count": 0,
        "first_error": None,
        "final_highwater_matches_tape": None,
        "reason": "NO_ROWS",
    }


def test_sqlite_highwater_error_is_finite_and_unavailable():
    runner = _load_runner()
    journal = _JournalProjection(error=sqlite3.OperationalError("synthetic read failure"))

    result = runner._live_source_continuity_status(
        journal, _SCOPES, _DecisionTapeProjection(), None
    )

    assert len(journal.calls) == 1
    assert result == {
        "status": "UNAVAILABLE",
        "available": False,
        "record_count": 1,
        "failure_count": 1,
        "first_error": "SOURCE_HIGHWATER_FINAL_READ_FAILED",
        "final_highwater_matches_tape": False,
    }


def test_exact_final_highwater_reference_is_available():
    runner = _load_runner()
    journal = _JournalProjection(highwater=_matching_highwater())

    result = runner._live_source_continuity_status(
        journal, _SCOPES, _DecisionTapeProjection(), SimpleNamespace()
    )

    assert len(journal.calls) == 1
    assert result == {
        "status": "AVAILABLE",
        "available": True,
        "record_count": 1,
        "failure_count": 0,
        "first_error": None,
        "final_highwater_matches_tape": True,
    }
