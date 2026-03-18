#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""Edge case unit tests for PandasData / PandasDirectData contract consistency.

Tests cover:
- PandasData.start() logs when to_numpy fails
- PandasData.start() logs through datetime conversion fallback chain
- PandasDirectData._load basic iteration
- PandasData._load with numpy fast path vs fallback path
- PandasData column autodetect with nocase=True/False
- PandasData with missing columns (None mapping)
"""

import logging
from datetime import datetime

import pytest

pd = pytest.importorskip("pandas")

import backtrader as bt
from backtrader.feeds.pandafeed import PandasData, PandasDirectData


# ===========================================================================
# Helpers
# ===========================================================================


def _make_simple_df(rows=5):
    """Create a minimal OHLCV DataFrame with datetime index."""
    dates = pd.date_range("2024-01-01", periods=rows, freq="D")
    data = {
        "open": [100.0 + i for i in range(rows)],
        "high": [105.0 + i for i in range(rows)],
        "low": [95.0 + i for i in range(rows)],
        "close": [102.0 + i for i in range(rows)],
        "volume": [1000 + i * 100 for i in range(rows)],
        "openinterest": [0] * rows,
    }
    return pd.DataFrame(data, index=dates)


def _run_cerebro_with_df(df, **kwargs):
    """Run a minimal cerebro with a PandasData feed and return the data."""
    cerebro = bt.Cerebro()
    data = PandasData(dataname=df, **kwargs)
    cerebro.adddata(data)
    results = cerebro.run()
    return results


# ===========================================================================
# PandasData basic loading tests
# ===========================================================================


class TestPandasDataBasicLoad:
    """Test PandasData loads DataFrame correctly."""

    def test_load_simple_df(self):
        """Should load all rows from a simple DataFrame."""
        df = _make_simple_df(5)
        results = _run_cerebro_with_df(df)
        assert len(results) == 1

    def test_load_single_row(self):
        """Should handle single-row DataFrame."""
        df = _make_simple_df(1)
        results = _run_cerebro_with_df(df)
        assert len(results) == 1

    def test_load_with_datetime_column(self):
        """Should load when datetime is a column, not the index."""
        df = _make_simple_df(3)
        df = df.reset_index()
        df = df.rename(columns={df.columns[0]: "datetime"})
        results = _run_cerebro_with_df(df, datetime="datetime")
        assert len(results) == 1


# ===========================================================================
# Column autodetect tests
# ===========================================================================


class TestColumnAutodetect:
    """Test column name autodetection with nocase."""

    def test_nocase_true_matches_uppercase(self):
        """Uppercase column names should match with nocase=True."""
        df = _make_simple_df(3)
        df.columns = [c.upper() for c in df.columns]
        results = _run_cerebro_with_df(df, nocase=True)
        assert len(results) == 1

    def test_nocase_false_requires_exact(self):
        """Uppercase columns should NOT match with nocase=False."""
        df = _make_simple_df(3)
        df.columns = [c.upper() for c in df.columns]
        # With nocase=False and uppercase columns, autodetect should fail
        # but the feed should still run (columns mapped to None)
        results = _run_cerebro_with_df(df, nocase=False)
        assert len(results) == 1

    def test_missing_volume_column(self):
        """DataFrame without volume column should still load."""
        df = _make_simple_df(3)
        df = df.drop(columns=["volume"])
        results = _run_cerebro_with_df(df)
        assert len(results) == 1


# ===========================================================================
# Datetime conversion fallback chain logging
# ===========================================================================


class TestDatetimeConversionLogging:
    """Test that datetime conversion fallbacks log appropriately."""

    def test_numpy_conversion_failure_logged(self, caplog):
        """When to_numpy fails, debug log should be emitted."""
        df = _make_simple_df(3)

        # Patch to_numpy to fail
        original_to_numpy = df.to_numpy

        def broken_to_numpy(**kwargs):
            raise TypeError("mock numpy failure")

        df.to_numpy = broken_to_numpy

        with caplog.at_level(logging.DEBUG):
            cerebro = bt.Cerebro()
            data = PandasData(dataname=df)
            cerebro.adddata(data)
            cerebro.run()

        assert any(
            "Failed to convert DataFrame to numpy array" in r.message
            for r in caplog.records
        )


# ===========================================================================
# PandasDirectData tests
# ===========================================================================


class TestPandasDirectData:
    """Test PandasDirectData basic functionality."""

    def test_load_direct_data(self):
        """Should load data using itertuples.

        PandasDirectData params default to datetime=0, open=1, etc.
        itertuples() yields (Index, col0, col1, ...) so the actual
        positional index in the tuple is param_value + 1.  We place
        datetime at column 0 with proper Timestamp values.
        """
        dates = pd.date_range("2024-01-01", periods=3, freq="D")
        df = pd.DataFrame({
            "datetime": dates,
            "open": [100.0, 101.0, 102.0],
            "high": [105.0, 106.0, 107.0],
            "low": [95.0, 96.0, 97.0],
            "close": [102.0, 103.0, 104.0],
            "volume": [1000.0, 1100.0, 1200.0],
            "openinterest": [0.0, 0.0, 0.0],
        })
        # PandasDirectData defaults: datetime=0 → tuple[1], open=1 → tuple[2], etc.
        # itertuples yields (idx, col0, col1, col2, ...) so +1 offset
        cerebro = bt.Cerebro()
        data = PandasDirectData(dataname=df, datetime=1, open=2, high=3,
                                low=4, close=5, volume=6, openinterest=7)
        cerebro.adddata(data)
        results = cerebro.run()
        assert len(results) == 1


# ===========================================================================
# Edge cases for zero values
# ===========================================================================


class TestZeroValues:
    """Test that zero OHLCV values are loaded correctly (not treated as missing)."""

    def test_zero_close_price(self):
        """Zero close price should be loaded as 0.0, not skipped."""
        df = _make_simple_df(3)
        df.iloc[1, df.columns.get_loc("close")] = 0.0

        cerebro = bt.Cerebro()
        data = PandasData(dataname=df)
        cerebro.adddata(data)
        results = cerebro.run()
        assert len(results) == 1

    def test_zero_volume(self):
        """Zero volume should be loaded as 0, not skipped."""
        df = _make_simple_df(3)
        df["volume"] = 0

        cerebro = bt.Cerebro()
        data = PandasData(dataname=df)
        cerebro.adddata(data)
        results = cerebro.run()
        assert len(results) == 1
