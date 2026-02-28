#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit tests for PandasData and PandasDirectData feeds.

Tests DataFrame loading, column mapping, datetime index handling,
and edge cases like missing columns and empty DataFrames.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime

import backtrader as bt
from backtrader.feeds.pandafeed import PandasData, PandasDirectData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(n=5, start="2024-01-02"):
    """Create a simple OHLCV DataFrame with DatetimeIndex.

    Generates synthetic price data with realistic OHLC relationships
    and random volume values. Uses fixed random seed for reproducibility.

    Args:
        n: Number of bars to generate. Defaults to 5.
        start: Start date string. Defaults to "2024-01-02".

    Returns:
        pandas.DataFrame: DataFrame with columns: open, high, low, close,
            volume, openinterest. Index is DatetimeIndex of business days.
    """
    dates = pd.bdate_range(start=start, periods=n)
    np.random.seed(42)
    base = 100.0 + np.cumsum(np.random.randn(n))
    df = pd.DataFrame({
        "open": base,
        "high": base + np.abs(np.random.randn(n)),
        "low": base - np.abs(np.random.randn(n)),
        "close": base + np.random.randn(n) * 0.5,
        "volume": np.random.randint(1000, 10000, n).astype(float),
        "openinterest": np.zeros(n),
    }, index=dates)
    return df


def _run_with_pandas(df, feed_cls=PandasData, **kwargs):
    """Run cerebro with a PandasData feed and return the data object.

    Creates a minimal Cerebro instance, adds the feed, runs the
    backtest, and returns the processed data object.

    Args:
        df: pandas DataFrame with OHLCV data.
        feed_cls: Feed class to use (PandasData or PandasDirectData).
            Defaults to PandasData.
        **kwargs: Additional keyword arguments passed to feed_cls.

    Returns:
        Data feed object after cerebro.run() completes.
    """
    cerebro = bt.Cerebro()
    data = feed_cls(dataname=df, **kwargs)
    cerebro.adddata(data)
    cerebro.run()
    return data


# ---------------------------------------------------------------------------
# PandasData tests
# ---------------------------------------------------------------------------

class TestPandasDataBasic:
    """Test suite for basic PandasData loading functionality.

    Tests loading pandas DataFrames as Backtrader data feeds with
    OHLCV data and DatetimeIndex.
    """

    def test_load_dataframe(self):
        """Verify DataFrame loads with correct number of bars.

        Creates a 10-bar DataFrame and verifies that all bars are
        loaded into the Backtrader data feed.

        Args:
            self: Test instance.
        """
        df = _make_df(10)
        data = _run_with_pandas(df)
        assert len(data) == 10

    def test_ohlcv_values_match(self):
        """Verify OHLCV values are correctly transferred from DataFrame.

        Tests that the last bar in the data feed contains the same
        OHLCV values as the last row in the input DataFrame.

        Args:
            self: Test instance.
        """
        df = _make_df(3)
        data = _run_with_pandas(df)
        # Last bar should match last row of df
        assert abs(data.close[0] - df["close"].iloc[-1]) < 1e-6
        assert abs(data.open[0] - df["open"].iloc[-1]) < 1e-6
        assert abs(data.volume[0] - df["volume"].iloc[-1]) < 1e-6

    def test_datetime_from_index(self):
        """DatetimeIndex is used as datetime source."""
        df = _make_df(3, start="2024-06-10")
        data = _run_with_pandas(df)
        dt = data.datetime.datetime(0)
        assert dt.year == 2024
        assert dt.month == 6

    def test_datetime_from_column(self):
        """Datetime can come from a named column instead of index."""
        df = _make_df(3)
        df = df.reset_index()
        df.rename(columns={"index": "date"}, inplace=True)
        data = _run_with_pandas(df, datetime="date")
        assert len(data) == 3

    def test_single_bar(self):
        """Verify DataFrame with a single bar loads correctly.

        Tests the minimum valid case of a one-bar DataFrame.

        Args:
            self: Test instance.
        """
        df = _make_df(1)
        data = _run_with_pandas(df)
        assert len(data) == 1

    def test_many_bars(self):
        """Verify DataFrame with many bars loads correctly.

        Tests that a large DataFrame (500 bars) is fully loaded
        without data loss.

        Args:
            self: Test instance.
        """
        df = _make_df(500)
        data = _run_with_pandas(df)
        assert len(data) == 500


class TestPandasDataColumnMapping:
    """Test suite for column name mapping.

    Tests custom column name mappings and handling of missing columns.
    """

    def test_custom_column_names(self):
        """Map non-standard column names."""
        df = _make_df(3)
        df.columns = ["Open", "High", "Low", "Close", "Vol", "OI"]
        data = _run_with_pandas(
            df,
            open="Open", high="High", low="Low",
            close="Close", volume="Vol", openinterest="OI",
        )
        assert len(data) == 3

    def test_missing_volume_column(self):
        """Volume set to -1 when column is absent."""
        df = _make_df(3)
        df = df.drop(columns=["volume"])
        data = _run_with_pandas(df, volume=-1)
        assert len(data) == 3

    def test_missing_openinterest(self):
        """OpenInterest set to -1 when absent."""
        df = _make_df(3)
        df = df.drop(columns=["openinterest"])
        data = _run_with_pandas(df, openinterest=-1)
        assert len(data) == 3


class TestPandasDataEdgeCases:
    """Test suite for edge cases in PandasData loading.

    Tests small DataFrames, NaN values, and other edge case scenarios.
    """

    def test_two_bar_dataframe(self):
        """Small DataFrame loads correctly."""
        df = _make_df(2)
        data = _run_with_pandas(df)
        assert len(data) == 2

    def test_nan_in_data(self):
        """NaN values in DataFrame are handled."""
        df = _make_df(3)
        df.iloc[1, df.columns.get_loc("volume")] = np.nan
        data = _run_with_pandas(df)
        # Should still load all 3 bars
        assert len(data) == 3


# ---------------------------------------------------------------------------
# PandasDirectData tests
# ---------------------------------------------------------------------------

class TestPandasDirectData:
    """Test suite for PandasDirectData feed.

    PandasDirectData uses itertuples() where index 0 is the pandas Index
    (used as datetime) and columns map to indices 1, 2, 3, ...
    """

    def test_load_direct(self):
        """Verify PandasDirectData loads from DatetimeIndex DataFrame correctly."""
        df = _make_df(5)
        # itertuples: (Index=datetime, open, high, low, close, volume, oi)
        # So datetime=0, open=1, high=2, low=3, close=4, volume=5, oi=6
        data = _run_with_pandas(df, feed_cls=PandasDirectData)
        assert len(data) == 5

    def test_direct_values_correct(self):
        """Verify PandasDirectData loads OHLCV values correctly."""
        df = _make_df(3)
        data = _run_with_pandas(df, feed_cls=PandasDirectData)
        assert len(data) == 3
        assert abs(data.close[0] - df["close"].iloc[-1]) < 1e-6
