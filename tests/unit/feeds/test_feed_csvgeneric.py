#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit tests for GenericCSVData feed.

Tests column mapping, datetime parsing (string, unix int, unix float,
callable), nullvalue handling, time field merging, and sessionend logic.
"""

import os
import tempfile
from datetime import datetime, timezone

import pytest

import backtrader as bt
from backtrader.feeds.csvgeneric import GenericCSVData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_csv(lines, header=True):
    """Write CSV lines to a temporary file and return the file path.

    This helper function creates a temporary CSV file with optional header
    row for testing purposes. The file is automatically cleaned up by the
    caller or the operating system.

    Args:
        lines (list of str): List of CSV data lines (without newlines).
        header (bool, optional): Whether to write a standard header row.
            Defaults to True.

    Returns:
        str: Path to the created temporary CSV file.
    """
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w") as f:
        if header:
            f.write("datetime,open,high,low,close,volume,openinterest\n")
        for line in lines:
            f.write(line + "\n")
    return path


def _run_feed(path, **kwargs):
    """Create a Cerebro, add GenericCSVData, run, and return data lines.

    This helper function creates a minimal Cerebro instance with default
    parameters for CSV data loading, runs the backtest, and returns the
    data object for validation.

    Args:
        path (str): Path to the CSV file to load.
        **kwargs: Optional keyword arguments to override default parameters
            (e.g., dtformat, datetime column mapping, nullvalue).

    Returns:
        GenericCSVData: The loaded data object with processed lines.
    """
    cerebro = bt.Cerebro()
    defaults = dict(
        dataname=path,
        dtformat="%Y-%m-%d",
        timeframe=bt.TimeFrame.Days,
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=6,
        headers=True,
    )
    defaults.update(kwargs)
    data = GenericCSVData(**defaults)
    cerebro.adddata(data)
    cerebro.run()
    return data


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGenericCSVBasic:
    """Basic CSV parsing tests."""

    def test_load_simple_csv(self, tmp_path):
        """Test basic CSV loading with standard format."""
        path = str(tmp_path / "test.csv")
        with open(path, "w") as f:
            f.write("datetime,open,high,low,close,volume,oi\n")
            f.write("2024-01-02,100.0,105.0,99.0,103.0,1000,0\n")
            f.write("2024-01-03,103.0,107.0,102.0,106.0,1200,0\n")

        data = _run_feed(path)
        assert len(data) == 2
        assert data.close[0] == 106.0
        assert data.open[-1] == 100.0

    def test_column_mapping(self, tmp_path):
        """Test non-default column order."""
        path = str(tmp_path / "test.csv")
        with open(path, "w") as f:
            f.write("date,close,volume,open,high,low\n")
            f.write("2024-01-02,103.0,1000,100.0,105.0,99.0\n")

        data = _run_feed(
            path,
            datetime=0, close=1, volume=2, open=3, high=4, low=5,
            openinterest=-1,
        )
        assert len(data) == 1
        assert data.close[0] == 103.0
        assert data.open[0] == 100.0
        assert data.high[0] == 105.0
        assert data.low[0] == 99.0

    def test_nullvalue_handling(self, tmp_path):
        """Empty CSV fields use nullvalue parameter."""
        path = str(tmp_path / "test.csv")
        with open(path, "w") as f:
            f.write("datetime,open,high,low,close,volume,oi\n")
            f.write("2024-01-02,100.0,105.0,99.0,103.0,,0\n")

        # Use a specific nullvalue so we can detect it
        data = _run_feed(path, nullvalue=-999.0)
        assert len(data) == 1
        assert data.volume[0] == -999.0


class TestGenericCSVDatetime:
    """Datetime parsing format tests."""

    def test_dtformat_string(self, tmp_path):
        """Parse datetime from string format."""
        path = str(tmp_path / "test.csv")
        with open(path, "w") as f:
            f.write("datetime,open,high,low,close,volume,oi\n")
            f.write("2024-01-15,100.0,105.0,99.0,103.0,1000,0\n")

        data = _run_feed(path, dtformat="%Y-%m-%d")
        assert len(data) == 1
        dt = data.datetime.datetime(0)
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15

    def test_dtformat_unix_int(self, tmp_path):
        """Parse datetime from unix timestamp (int)."""
        ts = int(datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp())
        path = str(tmp_path / "test.csv")
        with open(path, "w") as f:
            f.write("datetime,open,high,low,close,volume,oi\n")
            f.write(f"{ts},100.0,105.0,99.0,103.0,1000,0\n")

        data = _run_feed(path, dtformat=1, timeframe=bt.TimeFrame.Minutes)
        assert len(data) == 1

    def test_dtformat_unix_float(self, tmp_path):
        """Parse datetime from unix timestamp (float)."""
        ts = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        path = str(tmp_path / "test.csv")
        with open(path, "w") as f:
            f.write("datetime,open,high,low,close,volume,oi\n")
            f.write(f"{ts},100.0,105.0,99.0,103.0,1000,0\n")

        data = _run_feed(path, dtformat=2, timeframe=bt.TimeFrame.Minutes)
        assert len(data) == 1

    def test_dtformat_callable(self, tmp_path):
        """Parse datetime with custom callable."""
        path = str(tmp_path / "test.csv")
        with open(path, "w") as f:
            f.write("datetime,open,high,low,close,volume,oi\n")
            f.write("20240115,100.0,105.0,99.0,103.0,1000,0\n")

        custom_parser = lambda x: datetime.strptime(x, "%Y%m%d")
        data = _run_feed(path, dtformat=custom_parser)
        assert len(data) == 1
        dt = data.datetime.datetime(0)
        assert dt.year == 2024

    def test_separate_time_field(self, tmp_path):
        """Date and time in separate columns."""
        path = str(tmp_path / "test.csv")
        with open(path, "w") as f:
            f.write("date,time,open,high,low,close,volume,oi\n")
            f.write("2024-01-15,09:30:00,100.0,105.0,99.0,103.0,1000,0\n")

        data = _run_feed(
            path,
            dtformat="%Y-%m-%d",
            tmformat="%H:%M:%S",
            datetime=0,
            time=1,
            open=2, high=3, low=4, close=5, volume=6, openinterest=7,
            timeframe=bt.TimeFrame.Minutes,
        )
        assert len(data) == 1
        dt = data.datetime.datetime(0)
        assert dt.hour == 9
        assert dt.minute == 30


class TestGenericCSVMultiBar:
    """Multi-bar data loading tests."""

    def test_multiple_bars(self, tmp_path):
        """Test loading multiple bars of data from CSV."""
        path = str(tmp_path / "test.csv")
        with open(path, "w") as f:
            f.write("datetime,open,high,low,close,volume,oi\n")
            for i in range(1, 11):
                f.write(f"2024-01-{i:02d},{100+i}.0,{105+i}.0,{99+i}.0,{103+i}.0,{1000+i*100},0\n")

        data = _run_feed(path)
        assert len(data) == 10

    def test_ohlcv_values_correct(self, tmp_path):
        """Verify OHLCV values are loaded correctly."""
        path = str(tmp_path / "test.csv")
        with open(path, "w") as f:
            f.write("datetime,open,high,low,close,volume,oi\n")
            f.write("2024-01-02,100.5,110.25,95.75,105.0,50000,123\n")

        data = _run_feed(path)
        assert data.open[0] == 100.5
        assert data.high[0] == 110.25
        assert data.low[0] == 95.75
        assert data.close[0] == 105.0
        assert data.volume[0] == 50000.0
        assert data.openinterest[0] == 123.0
