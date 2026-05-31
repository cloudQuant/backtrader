"""Inlined regression test for machine_learning/0011_0384_ais2_trading_robot.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime as dt
import io
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M1.csv"


class Mt5PandasFeed(bt.feeds.PandasData):
    """Custom MT5 data feed that includes spread as an extra line."""
    lines = ("spread",)
    params = (
        ("datetime", None),
        ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4),
        ("openinterest", 5), ("spread", 6),
    )


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    """Load MT5 tab-separated bars and return a sorted DataFrame index by datetime."""
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.read().strip().split("\n")
    cleaned = "\n".join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep="\t")
    df["datetime"] = pd.to_datetime(df["<DATE>"] + " " + df["<TIME>"], format="%Y.%m.%d %H:%M:%S")
    df = df.rename(columns={
        "<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low",
        "<CLOSE>": "close", "<TICKVOL>": "volume",
        "<VOL>": "openinterest", "<SPREAD>": "spread",
    })
    df = df[["datetime", "open", "high", "low", "close", "volume", "openinterest", "spread"]]
    df = df.set_index("datetime").sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Ais2TradingRobotStrategy(bt.Strategy):
    """Timeframe-based breakout strategy with dynamic position sizing and exits."""
    params = dict(
        account_reserve=0.20,
        order_reserve=0.04,
        symbol="EURUSD",
        take_factor=1.7,
        stop_factor=1.7,
        trail_factor=0.5,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=5.0,
        margin_per_lot=1000.0,
        contract_size=100.0,
        point=0.0001,
    )

    def __init__(self):
        """Initialize feed references and lifecycle counters."""
        self.data0 = self.datas[0]
        self.data1 = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.data2 = self.datas[2] if len(self.datas) > 2 else self.data0
        self.order = None
        self.pending_action = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def _round_lot(self, size):
        lot_min = float(self.p.lot_min)
        lot_step = float(self.p.lot_step)
        lot_max = float(self.p.lot_max)
        if size < lot_min:
            return 0.0
        steps = int((size - lot_min) // lot_step)
        rounded = lot_min + steps * lot_step
        return max(lot_min, min(lot_max, rounded))

    def _compute_position_size(self, quote_risk):
        if quote_risk <= 0:
            return 0.0
        equity = float(self.broker.getvalue())
        var_limit = equity * float(self.p.order_reserve)
        point = max(float(self.p.point), 1e-6)
        contract_size = max(float(self.p.contract_size), 1e-6)
        risk_points = max(1.0, quote_risk / point)
        nominal_point_value = contract_size * point
        size_limit = var_limit / (risk_points * nominal_point_value)
        return self._round_lot(size_limit)

    def _manage_trailing(self, quote_trail, trail_step):
        if not self.position or self.order is not None:
            return
        if quote_trail <= 0:
            return
        if self.position.size > 0:
            if float(self.data0.close[0]) <= self.entry_price:
                return
            new_stop = float(self.data0.close[0]) - quote_trail
            if self.stop_price is None or new_stop - self.stop_price > trail_step:
                if new_stop < float(self.data0.close[0]):
                    self.stop_price = new_stop
        elif self.position.size < 0:
            if float(self.data0.close[0]) >= self.entry_price:
                return
            new_stop = float(self.data0.close[0]) + quote_trail
            if self.stop_price is None or self.stop_price - new_stop > trail_step:
                if new_stop > float(self.data0.close[0]):
                    self.stop_price = new_stop

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data0.high[0])
        low = float(self.data0.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.pending_action = "close"
                self.order = self.close()
                return
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.pending_action = "close"
                self.order = self.close()
                return
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.pending_action = "close"
                self.order = self.close()
                return
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.pending_action = "close"
                self.order = self.close()
                return

    def next(self):
        """Generate trade commands from multi-timeframe range context."""
        self.bar_num += 1
        if self.order is not None:
            return
        if len(self.data1) < 2 or len(self.data2) < 2:
            return

        low_1 = float(self.data1.low[-1])
        high_1 = float(self.data1.high[-1])
        close_1 = float(self.data1.close[-1])
        low_2 = float(self.data2.low[-1])
        high_2 = float(self.data2.high[-1])
        range_1 = high_1 - low_1
        range_2 = high_2 - low_2
        average_1 = (high_1 + low_1) / 2.0
        quote_take = range_1 * float(self.p.take_factor)
        quote_stop = range_1 * float(self.p.stop_factor)
        quote_trail = range_2 * float(self.p.trail_factor)
        trail_step = float(self.p.point) * 2.0

        self._manage_trailing(quote_trail, trail_step)
        self._check_exit_levels()
        if self.order is not None:
            return

        signal_dt = bt.num2date(self.data1.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        if self.position:
            return

        ask = float(self.data0.close[0])
        bid = float(self.data0.close[0])

        command = None
        price = None
        stop = None
        take = None

        if close_1 > average_1 and ask > high_1:
            price = ask
            stop = high_1 - quote_stop
            take = ask + quote_take
            if take > price and stop < price:
                command = "buy"

        if close_1 < average_1 and bid < low_1:
            price = bid
            stop = low_1 + quote_stop
            take = bid - quote_take
            if take < price and stop > price:
                command = "sell"

        if command is None:
            return

        size = self._compute_position_size(abs(price - stop))
        if size <= 0:
            return

        self.entry_price = price
        self.stop_price = stop
        self.take_profit_price = take

        if command == "buy":
            self.pending_action = "open_long"
            self.order = self.buy(size=size)
        else:
            self.pending_action = "open_short"
            self.order = self.sell(size=size)

    def notify_order(self, order):
        """Track completion or rejection of currently pending orders."""
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            action = self.pending_action or ""
            if action == "open_long":
                self.buy_count += 1
            elif action == "open_short":
                self.sell_count += 1
            self.pending_action = None
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.pending_action = None
            self.order = None

    def notify_trade(self, trade):
        """Update PnL counters and clear level state after closing trade."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None


def test_11_0011_0384_ais2_trading_robot() -> None:
    """Migrated regression test for machine_learning/0011_0384_ais2_trading_robot."""
    fromdate = dt.datetime(2025, 12, 19, 15, 0, 0)
    todate = dt.datetime(2025, 12, 19, 20, 0, 0)
    frame = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)

    cerebro = bt.Cerebro()
    base_feed = Mt5PandasFeed(dataname=frame.copy(), timeframe=bt.TimeFrame.Minutes, compression=1)
    tf1_source = Mt5PandasFeed(dataname=frame.copy(), timeframe=bt.TimeFrame.Minutes, compression=1)
    tf2_source = Mt5PandasFeed(dataname=frame.copy(), timeframe=bt.TimeFrame.Minutes, compression=1)
    cerebro.adddata(base_feed, name="XAUUSD_M1")
    cerebro.resampledata(tf1_source, timeframe=bt.TimeFrame.Minutes, compression=15, name="XAUUSD_M15")
    cerebro.resampledata(tf2_source, timeframe=bt.TimeFrame.Minutes, compression=1, name="XAUUSD_M1B")

    cerebro.addstrategy(
        Ais2TradingRobotStrategy,
        account_reserve=0.20, order_reserve=0.04, symbol="XAUUSD",
        take_factor=1.7, stop_factor=1.7, trail_factor=0.5,
        lot_min=0.01, lot_step=0.01, lot_max=5.0,
        margin_per_lot=1000.0, contract_size=100.0, point=0.01,
    )

    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0, stocklike=False,
    )
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 301, f"bar_num: expected=301, got={strat.bar_num}"
    assert strat.buy_count == 3, f"buy_count: expected=3, got={strat.buy_count}"
    assert strat.sell_count == 0, f"sell_count: expected=0, got={strat.sell_count}"
    assert strat.win_count == 3, f"win_count: expected=3, got={strat.win_count}"
    assert strat.loss_count == 0, f"loss_count: expected=0, got={strat.loss_count}"
    assert strat.trade_count == 3, f"trade_count: expected=3, got={strat.trade_count}"
    assert total_trades == 3, f"total_trades: expected=3, got={total_trades}"
    assert abs(final_value - 1001145.0) < 1.0, f"final_value: expected≈1001145.0, got={final_value}"
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
