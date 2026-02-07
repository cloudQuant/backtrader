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
import json
import os
import shutil
import tempfile

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
    # Disable file output by default in tests
    observer_kwargs.setdefault('log_file_enabled', False)
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
    cerebro.addobserver(bt.observers.TradeLogger, log_file_enabled=False)
    cerebro.run()
    strat = cerebro.runstrats[0][0]

    assert strat.checked_position_log, "position_log should be available during run"
    assert strat.checked_data_log, "data_log should be available during run"
    assert strat.checked_order_log, "order_log should be available during run"


def test_file_output_log_format():
    """Verify that .log files (tab-separated, default) are created in real-time."""
    tmp_dir = tempfile.mkdtemp()
    try:
        cerebro, strat = _create_cerebro(observer_kwargs=dict(
            log_file_enabled=True,
            log_dir=tmp_dir,
            file_format="log",
        ))
        tl = _find_tradelogger(strat)
        assert tl is not None

        run_dir = os.path.join(tmp_dir, tl._run_id)
        assert os.path.isdir(run_dir), f"run directory not created: {run_dir}"

        # run_info.json
        info_path = os.path.join(run_dir, "run_info.json")
        assert os.path.isfile(info_path)
        with open(info_path, "r") as f:
            info = json.load(f)
        assert info["strategy_name"] == "SMAStrategy"

        # .log files should exist
        assert os.path.isfile(os.path.join(run_dir, "order.log"))
        assert os.path.isfile(os.path.join(run_dir, "trade.log"))
        assert os.path.isfile(os.path.join(run_dir, "position.log"))
        assert os.path.isfile(os.path.join(run_dir, "data.log"))

        # check tab-separated content
        with open(os.path.join(run_dir, "data.log"), "r") as f:
            header = f.readline()
        assert "\t" in header, "log format should be tab-separated"

        # current_position.json should exist
        pos_path = os.path.join(run_dir, "current_position.json")
        assert os.path.isfile(pos_path)
        with open(pos_path, "r") as f:
            positions = json.load(f)
        assert isinstance(positions, list)
        assert len(positions) >= 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_file_output_csv_format():
    """Verify that .csv files are created when file_format='csv'."""
    tmp_dir = tempfile.mkdtemp()
    try:
        cerebro, strat = _create_cerebro(observer_kwargs=dict(
            log_file_enabled=True,
            log_dir=tmp_dir,
            file_format="csv",
        ))
        tl = _find_tradelogger(strat)
        assert tl is not None

        run_dir = os.path.join(tmp_dir, tl._run_id)
        assert os.path.isdir(run_dir)

        # .csv files should exist
        assert os.path.isfile(os.path.join(run_dir, "order.csv"))
        assert os.path.isfile(os.path.join(run_dir, "trade.csv"))
        assert os.path.isfile(os.path.join(run_dir, "position.csv"))
        assert os.path.isfile(os.path.join(run_dir, "data.csv"))

        # check comma-separated content
        with open(os.path.join(run_dir, "data.csv"), "r") as f:
            header = f.readline()
        assert "," in header, "csv format should be comma-separated"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_current_position_json():
    """Verify current_position.json contains all data feeds with valid structure."""
    tmp_dir = tempfile.mkdtemp()
    try:
        cerebro, strat = _create_cerebro(observer_kwargs=dict(
            log_file_enabled=True,
            log_dir=tmp_dir,
        ))
        tl = _find_tradelogger(strat)
        assert tl is not None

        run_dir = os.path.join(tmp_dir, tl._run_id)
        pos_path = os.path.join(run_dir, "current_position.json")
        assert os.path.isfile(pos_path)
        with open(pos_path, "r") as f:
            positions = json.load(f)
        assert isinstance(positions, list)
        assert len(positions) >= 1
        for p in positions:
            assert "data_name" in p
            assert "size" in p
            assert "price" in p
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_log_indicators():
    """Verify that strategy indicators appear in data_log when log_indicators=True."""
    cerebro, strat = _create_cerebro(observer_kwargs=dict(
        log_indicators=True,
    ))
    tl = _find_tradelogger(strat)
    assert tl is not None

    # data_log entries should contain indicator columns
    # SMAStrategy has SMA and CrossOver indicators
    last_entry = tl.data_log[-1]
    indicator_cols = [k for k in last_entry.keys() if "." in k]
    assert len(indicator_cols) > 0, (
        f"Expected indicator columns in data_log, got keys: {list(last_entry.keys())}"
    )


def test_log_indicators_with_file():
    """Verify indicator columns appear in data_log file."""
    tmp_dir = tempfile.mkdtemp()
    try:
        cerebro, strat = _create_cerebro(observer_kwargs=dict(
            log_file_enabled=True,
            log_dir=tmp_dir,
            log_indicators=True,
        ))
        tl = _find_tradelogger(strat)
        assert tl is not None

        run_dir = os.path.join(tmp_dir, tl._run_id)
        data_path = os.path.join(run_dir, "data.log")
        assert os.path.isfile(data_path)

        with open(data_path, "r") as f:
            header = f.readline().strip()
        # header should contain indicator columns with dots
        cols = header.split("\t")
        indicator_cols = [c for c in cols if "." in c]
        assert len(indicator_cols) > 0, (
            f"Expected indicator columns in header, got: {cols}"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_run_id_contains_strategy_name():
    """Verify run_id includes strategy name and timestamp."""
    cerebro, strat = _create_cerebro()
    tl = _find_tradelogger(strat)
    assert tl is not None
    assert tl._run_id is not None
    assert "SMAStrategy" in tl._run_id
    assert tl._strategy_name == "SMAStrategy"
    assert tl._strategy_params is not None


def test_realtime_file_writing():
    """Verify files are written in real-time during the run, not just at stop()."""

    class FileCheckStrategy(bt.Strategy):
        """Strategy that checks files exist mid-run."""

        params = (("tmp_dir", None),)

        def __init__(self):
            self.sma = bt.indicators.SMA(self.data, period=15)
            self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
            self.file_existed_during_run = False

        def next(self):
            if len(self) > 20 and not self.file_existed_during_run:
                # Check if log files already exist mid-run
                tl = None
                for obs in self.stats.items:
                    if isinstance(obs, bt.observers.TradeLogger):
                        tl = obs
                        break
                if tl is not None and tl._log_dir is not None:
                    data_path = os.path.join(tl._log_dir, "data.log")
                    if os.path.isfile(data_path) and os.path.getsize(data_path) > 0:
                        self.file_existed_during_run = True

            if not self.position.size:
                if self.cross > 0.0:
                    self.buy()
            elif self.cross < 0.0:
                self.close()

    tmp_dir = tempfile.mkdtemp()
    try:
        cerebro = bt.Cerebro(runonce=True, preload=True)
        data = testcommon.getdata(0)
        cerebro.adddata(data)
        cerebro.addstrategy(FileCheckStrategy, tmp_dir=tmp_dir)
        cerebro.addobserver(
            bt.observers.TradeLogger,
            log_file_enabled=True,
            log_dir=tmp_dir,
        )
        cerebro.run()
        strat = cerebro.runstrats[0][0]
        assert strat.file_existed_during_run, (
            "Log files should exist during the run (real-time writing)"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_log_time_field():
    """Verify that all log records contain a log_time field as the first key."""
    cerebro, strat = _create_cerebro()
    tl = _find_tradelogger(strat)
    assert tl is not None

    # Check order_log
    assert len(tl.order_log) > 0
    for entry in tl.order_log:
        keys = list(entry.keys())
        assert keys[0] == "log_time", f"First key should be log_time, got {keys[0]}"
        assert entry["log_time"] is not None
        # log_time should look like a datetime string with microseconds
        assert "." in entry["log_time"], "log_time should include microseconds"

    # Check trade_log
    assert len(tl.trade_log) > 0
    for entry in tl.trade_log:
        keys = list(entry.keys())
        assert keys[0] == "log_time"

    # Check position_log
    assert len(tl.position_log) > 0
    for entry in tl.position_log:
        keys = list(entry.keys())
        assert keys[0] == "log_time"

    # Check data_log
    assert len(tl.data_log) > 0
    for entry in tl.data_log:
        keys = list(entry.keys())
        assert keys[0] == "log_time"


def test_log_time_in_file():
    """Verify that log_time appears as the first column in log files."""
    tmp_dir = tempfile.mkdtemp()
    try:
        cerebro, strat = _create_cerebro(observer_kwargs=dict(
            log_file_enabled=True,
            log_dir=tmp_dir,
        ))
        tl = _find_tradelogger(strat)
        assert tl is not None

        run_dir = os.path.join(tmp_dir, tl._run_id)
        for fname in ["data.log", "position.log"]:
            fpath = os.path.join(run_dir, fname)
            assert os.path.isfile(fpath), f"{fname} should exist"
            with open(fpath, "r") as f:
                header = f.readline().strip()
            first_col = header.split("\t")[0]
            assert first_col == "log_time", (
                f"First column in {fname} should be log_time, got {first_col}"
            )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_mysql_save():
    """Test MySQL persistence of order, trade, position logs.

    This test requires a running MySQL server with the backtrder_web database.
    It is skipped if MySQL is not available.
    """
    try:
        import pymysql
    except ImportError:
        import pytest
        pytest.skip("pymysql not installed")

    # Try to connect - skip if unavailable
    try:
        conn = pymysql.connect(
            host="localhost", port=3306, user="root",
            password="backtrader_web_123",
            database="backtrder_web",
            charset="utf8mb4",
        )
        conn.close()
    except Exception:
        import pytest
        pytest.skip("MySQL backtrder_web database not available")

    # Use a unique table prefix to avoid conflicts
    import time
    test_prefix = f"test_{int(time.time())}"

    tmp_dir = tempfile.mkdtemp()
    try:
        cerebro, strat = _create_cerebro(observer_kwargs=dict(
            log_file_enabled=True,
            log_dir=tmp_dir,
            mysql_enabled=True,
            mysql_host="localhost",
            mysql_port=3306,
            mysql_user="root",
            mysql_password="backtrader_web_123",
            mysql_database="backtrder_web",
            mysql_table_prefix=test_prefix,
        ))
        tl = _find_tradelogger(strat)
        assert tl is not None
        assert tl._run_id is not None

        # Verify data was inserted into MySQL
        conn = pymysql.connect(
            host="localhost", port=3306, user="root",
            password="backtrader_web_123",
            database="backtrder_web",
            charset="utf8mb4",
        )
        try:
            cursor = conn.cursor()

            # Check order_log
            cursor.execute(
                f"SELECT COUNT(*) FROM `{test_prefix}_order` WHERE run_id=%s",
                (tl._run_id,)
            )
            order_count = cursor.fetchone()[0]
            assert order_count > 0, "order_log should have records in MySQL"
            assert order_count == len(tl.order_log), (
                f"MySQL order count {order_count} != memory {len(tl.order_log)}"
            )

            # Check trade_log
            cursor.execute(
                f"SELECT COUNT(*) FROM `{test_prefix}_trade` WHERE run_id=%s",
                (tl._run_id,)
            )
            trade_count = cursor.fetchone()[0]
            assert trade_count > 0, "trade_log should have records in MySQL"
            assert trade_count == len(tl.trade_log)

            # Check position_log
            cursor.execute(
                f"SELECT COUNT(*) FROM `{test_prefix}_position` WHERE run_id=%s",
                (tl._run_id,)
            )
            pos_count = cursor.fetchone()[0]
            assert pos_count > 0, "position_log should have records in MySQL"
            assert pos_count == len(tl.position_log)

            # Verify strategy_name is correct
            cursor.execute(
                f"SELECT DISTINCT strategy_name FROM `{test_prefix}_order` WHERE run_id=%s",
                (tl._run_id,)
            )
            row = cursor.fetchone()
            assert row[0] == "SMAStrategy"

            # Verify log_time is populated
            cursor.execute(
                f"SELECT log_time FROM `{test_prefix}_order` WHERE run_id=%s LIMIT 1",
                (tl._run_id,)
            )
            row = cursor.fetchone()
            assert row[0] is not None, "log_time should be populated in MySQL"

            cursor.close()
        finally:
            # Clean up test tables
            cursor = conn.cursor()
            for tbl in ["order", "trade", "position"]:
                cursor.execute(f"DROP TABLE IF EXISTS `{test_prefix}_{tbl}`")
            conn.commit()
            cursor.close()
            conn.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_mysql_no_data_log_table():
    """Verify that data_log table is NOT created in MySQL."""
    try:
        import pymysql
    except ImportError:
        import pytest
        pytest.skip("pymysql not installed")

    try:
        conn = pymysql.connect(
            host="localhost", port=3306, user="root",
            password="backtrader_web_123",
            database="backtrder_web",
            charset="utf8mb4",
        )
        conn.close()
    except Exception:
        import pytest
        pytest.skip("MySQL backtrder_web database not available")

    import time
    test_prefix = f"test_nd_{int(time.time())}"

    tmp_dir = tempfile.mkdtemp()
    try:
        cerebro, strat = _create_cerebro(observer_kwargs=dict(
            log_file_enabled=True,
            log_dir=tmp_dir,
            mysql_enabled=True,
            mysql_host="localhost",
            mysql_port=3306,
            mysql_user="root",
            mysql_password="backtrader_web_123",
            mysql_database="backtrder_web",
            mysql_table_prefix=test_prefix,
        ))

        # Check that data_log table does NOT exist
        conn = pymysql.connect(
            host="localhost", port=3306, user="root",
            password="backtrader_web_123",
            database="backtrder_web",
            charset="utf8mb4",
        )
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema='backtrder_web' AND table_name=%s",
                (f"{test_prefix}_data",)
            )
            count = cursor.fetchone()[0]
            assert count == 0, "data table should NOT be created in MySQL"
            cursor.close()
        finally:
            # Clean up
            cursor = conn.cursor()
            for tbl in ["order", "trade", "position"]:
                cursor.execute(f"DROP TABLE IF EXISTS `{test_prefix}_{tbl}`")
            conn.commit()
            cursor.close()
            conn.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    test_run(main=True)
