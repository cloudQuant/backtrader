"""Backtrader-owned bar and datetime projection helpers."""

import datetime as dt

import pytest

from backtrader.stores._bt_projection import (
    datetime_to_utc_naive,
    normalize_bar,
    normalize_datetime,
)


def test_normalize_datetime_returns_naive_utc():
    aware = dt.datetime(2026, 1, 2, 3, 4, tzinfo=dt.timezone(dt.timedelta(hours=8)))

    assert normalize_datetime(aware) == dt.datetime(2026, 1, 1, 19, 4)
    assert normalize_datetime(aware).tzinfo is None
    assert normalize_datetime(dt.date(2026, 1, 2)) == dt.datetime(2026, 1, 2)
    assert normalize_datetime("2026-01-02T03:04:00Z") == dt.datetime(2026, 1, 2, 3, 4)


def test_normalize_datetime_accepts_epoch_seconds_and_milliseconds():
    seconds = 1767312000
    milliseconds = seconds * 1000

    assert normalize_datetime(seconds) == normalize_datetime(milliseconds)


def test_normalize_datetime_rejects_unsupported_values():
    with pytest.raises(ValueError, match="Unsupported datetime string"):
        normalize_datetime("not-a-date")
    with pytest.raises(ValueError, match="Unsupported datetime value"):
        normalize_datetime(object())


def test_datetime_to_utc_naive_leaves_naive_values_unchanged():
    naive = dt.datetime(2026, 1, 2, 3, 4)

    assert datetime_to_utc_naive(naive) == naive


def test_normalize_bar_accepts_mapping_and_sequence():
    mapping = normalize_bar(
        {
            "timestamp": "2026-01-02T03:04:00Z",
            "open": "1",
            "high": "2",
            "low": "0.5",
            "close": "1.5",
            "volume": "10",
        }
    )
    assert mapping == {
        "datetime": dt.datetime(2026, 1, 2, 3, 4),
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 10.0,
        "openinterest": 0.0,
    }

    sequence = normalize_bar(["2026-01-02T03:04:00Z", 1, 2, 0.5, 1.5, 10, 7])
    assert sequence["openinterest"] == 7.0
    assert sequence["datetime"] == dt.datetime(2026, 1, 2, 3, 4)


def test_normalize_bar_rejects_unknown_payloads():
    with pytest.raises(ValueError):
        normalize_bar({"open": 1})
    with pytest.raises(ValueError, match="Unsupported bar payload"):
        normalize_bar([1, 2, 3])
