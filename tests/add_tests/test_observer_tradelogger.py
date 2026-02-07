#!/usr/bin/env python
"""Test module for the TradeLogger observer in backtrader.

This module contains tests to verify that the TradeLogger observer correctly
records order, trade, position, and bar data during backtesting.

The test strategy uses a simple moving average crossover system:
- Buy when price crosses above the SMA
- Close position when price crosses below the SMA
- The TradeLogger observer records all activity

Example:
    To run this test directly::
        python tests/add_tests/test_observer_tradelogger.py

    To run via pytest::
        pytest tests/add_tests/test_observer_tradelogger.py -v
"""

import datetime

import backtrader as bt

from . import testcommon


class SMAStrategy(bt.Strategy):
    """A simple moving average crossover strategy for testing the TradeLogger observer.

    Attributes:
        sma (bt.indicators.SMA): Simple Moving Average indicator with period 15.
        cross (bt.indicators.CrossOver): Crossover indicator tracking the
            relationship between price and SMA.

    Trading Logic:
        - Entry: Buy when close price crosses above SMA (cross > 0)
        - Exit: Close position when close price crosses below SMA (cross < 0)
        - Only one position open at a time (no pyramiding)
    """

    def __init__(self):
        """Initialize the strategy with indicators."""
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar."""
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def _create_cerebro(observer_kwargs=None):
    """Create a cerebro instance with test data and TradeLogger observer.

    Args:
        observer_kwargs: Optional dict of kwargs for TradeLogger.

    Returns:
        tuple: (cerebro, strategy) after running.
    """
    cerebro = bt.Cerebro(runonce=True, preload=True)
    data = testcommon.getdata(0)
    cerebro.adddata(data)
    cerebro.addstrategy(SMAStrategy)
    if observer_kwargs is None:
        observer_kwargs = {}
    cerebro.addobserver(bt.observers.TradeLogger, **observer_kwargs)
    cerebro.run()
    strat = cerebro.runstrats[0][0]
    return cerebro, strat


def _find_tradelogger(strat):
    """Find the TradeLogger observer in a strategy's observers.

    Args:
        strat: Strategy instance.

    Returns:
        TradeLogger observer instance, or None if not found.
    """
    for obs in strat.stats.items:
        if isinstance(obs, bt.observers.TradeLogger):
            return obs
    return None


def test_run(main=False):
    """Run the TradeLogger observer test.

    Verifies that the strategy runs successfully and the TradeLogger
    observer collects order, trade, position, and data logs.

    Args:
        main (bool, optional): If True, enables plotting mode. Defaults to False.
    """
    cerebro, strat = _create_cerebro()
    # Verify the strategy ran successfully
    assert len(strat) > 0

    tl = _find_tradelogger(strat)
    assert tl is not None, "TradeLogger observer not found"

    # data_log should have one entry per bar
    assert len(tl.data_log) > 0, "data_log should not be empty"
    assert len(tl.data_log) == len(strat), (
        f"data_log length {len(tl.data_log)} != strat length {len(strat)}"
    )

    # Verify data_log entry structure
    entry = tl.data_log[0]
    assert "dt" in entry, "data_log entry missing 'dt'"
    assert "open" in entry, "data_log entry missing 'open'"
    assert "high" in entry, "data_log entry missing 'high'"
    assert "low" in entry, "data_log entry missing 'low'"
    assert "close" in entry, "data_log entry missing 'close'"
    assert "volume" in entry, "data_log entry missing 'volume'"
    assert "openinterest" in entry, "data_log entry missing 'openinterest'"
    assert "data_name" in entry, "data_log entry missing 'data_name'"

    # position_log should have one entry per bar (one data feed)
    assert len(tl.position_log) > 0, "position_log should not be empty"
    assert len(tl.position_log) == len(strat), (
        f"position_log length {len(tl.position_log)} != strat length {len(strat)}"
    )

    # Verify position_log entry structure
    pos_entry = tl.position_log[0]
    assert "dt" in pos_entry
    assert "size" in pos_entry
    assert "price" in pos_entry
    assert "data_name" in pos_entry

    # There should be some orders (the strategy does trade)
    assert len(tl.order_log) > 0, "order_log should not be empty"

    # Verify order_log entry structure
    ord_entry = tl.order_log[0]
    assert "ref" in ord_entry
    assert "ordtype" in ord_entry
    assert "status" in ord_entry
    assert "size" in ord_entry
    assert "dt" in ord_entry
    assert "data_name" in ord_entry

    # There should be some trades
    assert len(tl.trade_log) > 0, "trade_log should not be empty"

    # Verify trade_log entry structure
    tr_entry = tl.trade_log[0]
    assert "ref" in tr_entry
    assert "status" in tr_entry
    assert "size" in tr_entry
    assert "price" in tr_entry
    assert "pnl" in tr_entry
    assert "pnlcomm" in tr_entry
    assert "data_name" in tr_entry

    # get_all_logs should return all four logs
    all_logs = tl.get_all_logs()
    assert "orders" in all_logs
    assert "trades" in all_logs
    assert "positions" in all_logs
    assert "data" in all_logs
    assert all_logs["orders"] is tl.order_log
    assert all_logs["data"] is tl.data_log

    if main:
        cerebro.plot()


def test_data_log_values():
    """Verify that data_log values are reasonable numbers (not NaN)."""
    cerebro, strat = _create_cerebro()
    tl = _find_tradelogger(strat)
    assert tl is not None

    for entry in tl.data_log:
        # All OHLCV values should be valid numbers
        assert entry["open"] == entry["open"], "open is NaN"
        assert entry["high"] == entry["high"], "high is NaN"
        assert entry["low"] == entry["low"], "low is NaN"
        assert entry["close"] == entry["close"], "close is NaN"
        # high >= low
        assert entry["high"] >= entry["low"], (
            f"high {entry['high']} < low {entry['low']}"
        )
        # high >= open and high >= close
        assert entry["high"] >= entry["open"]
        assert entry["high"] >= entry["close"]
        # low <= open and low <= close
        assert entry["low"] <= entry["open"]
        assert entry["low"] <= entry["close"]
        # dt should not be None
        assert entry["dt"] is not None


def test_no_data_log():
    """Test that log_data=False disables data logging."""
    cerebro, strat = _create_cerebro(observer_kwargs=dict(log_data=False))
    tl = _find_tradelogger(strat)
    assert tl is not None

    # data_log should be empty since log_data=False
    assert len(tl.data_log) == 0, "data_log should be empty when log_data=False"

    # Other logs should still work
    assert len(tl.position_log) > 0, "position_log should not be empty"
    assert len(tl.order_log) > 0, "order_log should not be empty"


def test_all_disabled():
    """Test that disabling all log flags results in all empty logs."""
    cerebro, strat = _create_cerebro(observer_kwargs=dict(
        log_orders=False, log_trades=False,
        log_positions=False, log_data=False,
    ))
    tl = _find_tradelogger(strat)
    assert tl is not None

    assert len(tl.order_log) == 0
    assert len(tl.trade_log) == 0
    assert len(tl.position_log) == 0
    assert len(tl.data_log) == 0


def test_trade_log_has_closed_trades():
    """Verify that trade_log contains at least one closed trade."""
    cerebro, strat = _create_cerebro()
    tl = _find_tradelogger(strat)
    assert tl is not None

    # Check that there is at least one closed trade
    closed_trades = [t for t in tl.trade_log if t["isclosed"]]
    assert len(closed_trades) > 0, "Should have at least one closed trade"

    # Closed trades should have barclose > 0 and dtclose set
    for ct in closed_trades:
        assert ct["barclose"] > 0, "Closed trade should have barclose > 0"
        assert ct["dtclose"] is not None, "Closed trade should have dtclose set"


def test_position_log_reflects_trades():
    """Verify position_log shows non-zero position after a trade opens."""
    cerebro, strat = _create_cerebro()
    tl = _find_tradelogger(strat)
    assert tl is not None

    # At some point, position should be non-zero (strategy does trade)
    has_position = any(p["size"] != 0 for p in tl.position_log)
    assert has_position, "Position should be non-zero at some point"

    # First bar should have zero position (no trade yet)
    assert tl.position_log[0]["size"] == 0, "First bar should have zero position"


def test_getter_methods():
    """Verify that getter methods return the same data as direct attribute access."""
    cerebro, strat = _create_cerebro()
    tl = _find_tradelogger(strat)
    assert tl is not None

    assert tl.get_order_log() is tl.order_log
    assert tl.get_trade_log() is tl.trade_log
    assert tl.get_position_log() is tl.position_log
    assert tl.get_data_log() is tl.data_log


def test_logs_available_during_run():
    """Verify that TradeLogger logs are populated in real-time during the run.

    Uses a strategy that checks logs from within its next() method to prove
    the observer populates data incrementally, not just after the run.
    """

    class CheckDuringRunStrategy(bt.Strategy):
        """Strategy that verifies TradeLogger logs are available mid-run."""

        def __init__(self):
            self.sma = bt.indicators.SMA(self.data, period=15)
            self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
            self.checked_position_log = False
            self.checked_data_log = False
            self.checked_order_log = False

        def next(self):
            # Find TradeLogger in observers
            tl = None
            for obs in self.stats.items:
                if isinstance(obs, bt.observers.TradeLogger):
                    tl = obs
                    break
            if tl is None:
                return

            # After the first bar, position_log and data_log from previous bars
            # should already be populated (observer next() runs after strategy next())
            if len(self) > 2:
                if len(tl.position_log) > 0:
                    self.checked_position_log = True
                if len(tl.data_log) > 0:
                    self.checked_data_log = True

            # After an order is placed, order_log should be populated
            if len(tl.order_log) > 0:
                self.checked_order_log = True

            if not self.position.size:
                if self.cross > 0.0:
                    self.buy()
            elif self.cross < 0.0:
                self.close()

    cerebro = bt.Cerebro(runonce=True, preload=True)
    data = testcommon.getdata(0)
    cerebro.adddata(data)
    cerebro.addstrategy(CheckDuringRunStrategy)
    cerebro.addobserver(bt.observers.TradeLogger)
    cerebro.run()
    strat = cerebro.runstrats[0][0]

    assert strat.checked_position_log, "position_log should be available during run"
    assert strat.checked_data_log, "data_log should be available during run"
    assert strat.checked_order_log, "order_log should be available during run"


if __name__ == "__main__":
    test_run(main=True)
