"""Focused contracts for the Iteration 72 futures cleanup fixes."""

from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")

import backtrader.futures as futures
from backtrader.futures import CHINA_TIME, load_exchange_session_calendar
from backtrader.futures.ranking_projection import _aware_utc


def _session_calendar_document():
    source_id = "SHFE.hours"
    return {
        "schema": "backtrader.exchange_session_calendar.v1",
        "exchange_id": "SHFE",
        "calendar_source_id": source_id,
        "coverage_start": "2026-10-22",
        "coverage_through": "2026-10-22",
        "trading_days": ["2026-10-22"],
        "product_universe": [{"exchange_id": "SHFE", "product_id": "CU"}],
        "sources": [
            {
                "source_id": source_id,
                "source_url": "https://fixture.invalid/shfe-hours.html",
                "version": "fixture-2026-10-20",
                "available_at": "2026-10-20T00:00:00Z",
                "retrieved_at": "2026-10-20T01:00:00Z",
                "sha256": "0" * 64,
            }
        ],
        "product_days": [
            {
                "product": {"exchange_id": "SHFE", "product_id": "CU"},
                "trading_day": "2026-10-22",
                "source_id": source_id,
                "closed_reason": None,
                "windows": [
                    {
                        "session_id": "day-am",
                        "session_date": "2026-10-22",
                        "start": "2026-10-22T09:00:00+08:00",
                        "end": "2026-10-22T10:00:00+08:00",
                        "source_id": source_id,
                    }
                ],
            }
        ],
        "complete": True,
    }


def test_session_json_loader_preserves_immutable_window_tuple():
    calendar = load_exchange_session_calendar(_session_calendar_document())

    (row,) = calendar.product_days
    assert isinstance(row.windows, tuple)
    assert len(row.windows) == 1
    window = row.windows[0]
    assert window.session_id == "day-am"
    assert window.start == datetime(
        2026, 10, 22, 9, tzinfo=timezone(timedelta(hours=8))
    )
    assert window.end == datetime(
        2026, 10, 22, 10, tzinfo=timezone(timedelta(hours=8))
    )


class _ChangingOffset(tzinfo):
    def __init__(self):
        self.calls = 0

    def utcoffset(self, dt: Optional[datetime]) -> Optional[timedelta]:
        self.calls += 1
        return timedelta(0) if self.calls == 1 else None

    def dst(self, dt: Optional[datetime]) -> Optional[timedelta]:
        return timedelta(0)

    def tzname(self, dt: Optional[datetime]) -> str:
        return "changing UTC"


def test_aware_utc_reads_offset_once_and_keeps_utc_semantics():
    changing_offset = _ChangingOffset()
    value = datetime(2026, 10, 22, 9, tzinfo=changing_offset)
    changing_offset.calls = 0

    assert _aware_utc(value)
    assert changing_offset.calls == 1
    assert _aware_utc(datetime(2026, 10, 22, 9, tzinfo=timezone.utc))
    assert not _aware_utc(
        datetime(2026, 10, 22, 9, tzinfo=timezone(timedelta(hours=8)))
    )
    assert not _aware_utc(datetime(2026, 10, 22, 9))


def test_china_time_remains_an_explicit_and_star_export():
    star_exports = {}
    exec("from backtrader.futures import *", star_exports)  # noqa: S102

    assert CHINA_TIME is futures.CHINA_TIME
    assert futures.CHINA_TIME.utcoffset(None) == timedelta(hours=8)
    assert futures.CHINA_TIME.tzname(None) == "China Standard Time"
    assert star_exports["CHINA_TIME"] is futures.CHINA_TIME
