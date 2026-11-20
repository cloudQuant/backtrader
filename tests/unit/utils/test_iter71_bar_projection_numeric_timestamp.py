"""Regression coverage for numeric timestamp validation in bar projection."""

import datetime as dt
import math

import pytest

from backtrader.utils.bar_projection import normalize_bar, normalize_datetime


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_normalize_datetime_rejects_non_finite_numeric_timestamps(value):
    with pytest.raises(ValueError, match="Numeric datetime timestamp must be finite"):
        normalize_datetime(value)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_normalize_bar_rejects_non_finite_numeric_timestamps(value):
    bar = {"timestamp": value, "open": 1, "high": 2, "low": 0, "close": 1, "volume": 3}

    with pytest.raises(ValueError, match="Numeric datetime timestamp must be finite"):
        normalize_bar(bar)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1_700_000_000, dt.datetime(2023, 11, 14, 22, 13, 20)),
        (1_700_000_000_000, dt.datetime(2023, 11, 14, 22, 13, 20)),
        (10_000_000_000, dt.datetime(2286, 11, 20, 17, 46, 40)),
        (10_000_000_001, dt.datetime(1970, 4, 26, 17, 46, 40, 1000)),
    ],
)
def test_normalize_datetime_preserves_seconds_milliseconds_and_threshold(value, expected):
    assert normalize_datetime(value) == expected


def test_normalize_bar_preserves_finite_numeric_timestamp_conversion():
    projected = normalize_bar(
        {"timestamp": 1_700_000_000_000, "open": 1, "high": 2, "low": 0, "close": 1, "volume": 3}
    )

    assert projected["datetime"] == dt.datetime(2023, 11, 14, 22, 13, 20)
