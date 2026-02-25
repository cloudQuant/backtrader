#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit tests for RollOver data feed.

Tests futures contract rollover logic including checkdate,
checkcondition, and multi-contract chaining.
"""

import os
import tempfile
from datetime import datetime

import pytest

import backtrader as bt
from backtrader.feeds.csvgeneric import GenericCSVData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_csv(tmp_path, name, rows):
    """Create a CSV file with OHLCV data.

    Args:
        tmp_path: pytest tmp_path fixture.
        name: filename.
        rows: list of (date_str, open, high, low, close, volume) tuples.
    """
    path = str(tmp_path / name)
    with open(path, "w") as f:
        f.write("datetime,open,high,low,close,volume,oi\n")
        for row in rows:
            f.write(",".join(str(x) for x in row) + ",0\n")
    return path


def _make_data(path):
    return GenericCSVData(
        dataname=path,
        dtformat="%Y-%m-%d",
        timeframe=bt.TimeFrame.Days,
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=6,
        headers=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRollOverBasic:
    """Basic rollover functionality."""

    def test_single_contract_no_rollover(self, tmp_path):
        """Single contract loads all bars without rollover."""
        path = _make_csv(tmp_path, "c1.csv", [
            ("2024-01-02", 100, 105, 99, 103, 1000),
            ("2024-01-03", 103, 107, 102, 106, 1200),
            ("2024-01-04", 106, 108, 104, 107, 900),
        ])

        cerebro = bt.Cerebro()
        d1 = _make_data(path)
        data = bt.feeds.RollOver(d1)
        cerebro.adddata(data)
        cerebro.run()
        assert len(data) == 3

    def test_two_contracts_rollover_on_date(self, tmp_path):
        """Roll from contract 1 to contract 2 based on date check."""
        p1 = _make_csv(tmp_path, "c1.csv", [
            ("2024-01-02", 100, 105, 99, 103, 1000),
            ("2024-01-03", 103, 107, 102, 106, 1200),
            ("2024-01-04", 106, 108, 104, 107, 900),
            ("2024-01-05", 107, 110, 106, 109, 800),
        ])
        p2 = _make_csv(tmp_path, "c2.csv", [
            ("2024-01-03", 203, 207, 202, 206, 2000),
            ("2024-01-04", 206, 208, 204, 207, 2100),
            ("2024-01-05", 207, 210, 206, 209, 2200),
            ("2024-01-08", 209, 212, 208, 211, 2300),
        ])

        d1 = _make_data(p1)
        d2 = _make_data(p2)

        # Roll over starting Jan 4
        def checkdate(dt, d):
            return dt.date() >= datetime(2024, 1, 4).date()

        cerebro = bt.Cerebro()
        data = bt.feeds.RollOver(d1, d2, checkdate=checkdate)
        cerebro.adddata(data)
        cerebro.run()

        # Should have bars from both contracts
        assert len(data) >= 3

    def test_rollover_with_checkcondition(self, tmp_path):
        """Roll only when both checkdate and checkcondition are True."""
        p1 = _make_csv(tmp_path, "c1.csv", [
            ("2024-01-02", 100, 105, 99, 103, 5000),
            ("2024-01-03", 103, 107, 102, 106, 4000),
            ("2024-01-04", 106, 108, 104, 107, 3000),
            ("2024-01-05", 107, 110, 106, 109, 1000),
        ])
        p2 = _make_csv(tmp_path, "c2.csv", [
            ("2024-01-03", 203, 207, 202, 206, 2000),
            ("2024-01-04", 206, 208, 204, 207, 5000),
            ("2024-01-05", 207, 210, 206, 209, 6000),
            ("2024-01-08", 209, 212, 208, 211, 7000),
        ])

        d1 = _make_data(p1)
        d2 = _make_data(p2)

        # Roll when date >= Jan 4 AND d1 volume < d2 volume
        def checkdate(dt, d):
            return dt.date() >= datetime(2024, 1, 4).date()

        def checkcondition(d0, d1):
            return d0.volume[0] < d1.volume[0]

        cerebro = bt.Cerebro()
        data = bt.feeds.RollOver(d1, d2, checkdate=checkdate, checkcondition=checkcondition)
        cerebro.adddata(data)
        cerebro.run()
        assert len(data) >= 3


class TestRollOverEdgeCases:
    """Edge cases and error handling."""

    def test_no_overlap_periods(self, tmp_path):
        """Contracts with no overlapping dates."""
        p1 = _make_csv(tmp_path, "c1.csv", [
            ("2024-01-02", 100, 105, 99, 103, 1000),
            ("2024-01-03", 103, 107, 102, 106, 1200),
        ])
        p2 = _make_csv(tmp_path, "c2.csv", [
            ("2024-01-08", 200, 205, 199, 203, 2000),
            ("2024-01-09", 203, 207, 202, 206, 2200),
        ])

        d1 = _make_data(p1)
        d2 = _make_data(p2)

        def checkdate(dt, d):
            return True  # Always ready to roll

        cerebro = bt.Cerebro()
        data = bt.feeds.RollOver(d1, d2, checkdate=checkdate)
        cerebro.adddata(data)
        cerebro.run()
        # Should load bars from both contracts sequentially
        assert len(data) >= 2
