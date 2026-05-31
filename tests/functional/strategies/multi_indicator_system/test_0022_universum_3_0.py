"""Inlined regression test for the Universum 3.0 DeMarker multi-indicator strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.

Data Used:
    XAUUSD (gold) 15-minute ``M15`` bars loaded from
    ``tests/datas/XAUUSD_M15.csv`` through the MetaTrader-5 style CSV reader.
    The backtest window runs from 2025-12-03 01:15 to 2026-03-10 09:00 with a
    15-minute bar shift, delivered to the engine through a single
    :class:`Mt5PandasFeed` data source on the 15-minute timeframe.

Strategy Principle:
    Trades a single DeMarker oscillator, which compares directional high/low
    movement to gauge whether buyers or sellers dominate over a lookback
    window. A reading above 0.5 is treated as buy-biased and at or below 0.5 as
    sell-biased. The system pairs this directional bias with a martingale-style
    money-management scheme that scales position size up after losing trades to
    recover prior losses, capped by a maximum lot and a consecutive-loss limit.

Strategy Logic:
    ``__init__`` builds the :class:`DeMarkerIndicator` and initialises bar,
    signal, order and loss counters. ``next`` waits for the indicator warm-up,
    manages open positions against fixed take-profit/stop-loss levels, and
    otherwise opens a long or short of the next martingale-scaled lot based on
    the DeMarker bias. ``notify_order`` tracks completed and rejected orders
    and clears the pending order reference, while ``notify_trade`` tallies wins
    and losses and resets or increments the loss streak that drives lot sizing.
    The test asserts bar, trade and final-value counts against the captured
    baseline.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    """Load a MetaTrader-5 style CSV export into an OHLCV DataFrame.

    Args:
        filepath: Path to the tab-separated MT5 CSV export to read.
        fromdate: Optional inclusive lower bound used to trim the index.
        todate: Optional inclusive upper bound used to trim the index.
        bar_shift_minutes: Minutes to shift the datetime index forward.

    Returns:
        A datetime-indexed DataFrame with open, high, low, close, volume and
        openinterest columns in ascending time order.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.read().strip().split("\n")
    cleaned = "\n".join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep="\t")
    df["datetime"] = pd.to_datetime(df["<DATE>"] + " " + df["<TIME>"], format="%Y.%m.%d %H:%M:%S")
    df = df.rename(columns={
        "<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low", "<CLOSE>": "close",
        "<TICKVOL>": "tick_volume", "<VOL>": "real_volume",
    })
    df["openinterest"] = 0
    df["volume"] = df["tick_volume"]
    df = df[["datetime", "open", "high", "low", "close", "volume", "openinterest"]]
    df = df.set_index("datetime")
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    """PandasData feed mapping standard OHLCV columns by position.

    Binds the open, high, low, close, volume and openinterest lines to fixed
    column indices so the prepared DataFrame can be consumed directly by the
    engine.
    """

    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class DeMarkerIndicator(bt.Indicator):
    """DeMarker oscillator measuring directional high/low pressure.

    Sums the positive high-to-high and low-to-low moves over ``period`` bars
    and normalises the up moves by the total, producing a single ``dem`` line
    bounded in [0, 1] where higher values indicate stronger buying pressure.
    """

    lines = ("dem",)
    params = (("period", 14),)

    def __init__(self):
        """Reserve the minimum lookback needed for the period-based window."""
        self.addminperiod(self.p.period + 1)

    def next(self):
        """Compute the DeMarker value for the current bar."""
        de_max_sum = 0.0
        de_min_sum = 0.0
        for i in range(self.p.period):
            high_now = float(self.data.high[-i])
            high_prev = float(self.data.high[-(i + 1)])
            low_now = float(self.data.low[-i])
            low_prev = float(self.data.low[-(i + 1)])
            de_max_sum += max(high_now - high_prev, 0.0)
            de_min_sum += max(low_prev - low_now, 0.0)
        denom = de_max_sum + de_min_sum
        if denom == 0:
            self.lines.dem[0] = 0.0
        else:
            self.lines.dem[0] = de_max_sum / denom


class Universum30Strategy(bt.Strategy):
    """DeMarker-driven strategy with martingale position sizing.

    Enters long or short each bar based on whether the DeMarker oscillator is
    above or below 0.5, protects positions with fixed take-profit and
    stop-loss offsets, and scales the lot size up after consecutive losses up
    to a maximum lot and loss-streak limit.
    """

    params = dict(
        ma_period=10,
        take_profit=50, stop_loss=50,
        lots=0.01,
        losseslimit=1000000,
        point=0.01, digits_adjust=10, price_digits=2,
        max_lot=100.0,
    )

    def __init__(self):
        """Build the DeMarker indicator and initialise counters and state."""
        self.demarker = DeMarkerIndicator(self.data, period=self.p.ma_period)
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.order = None
        self.stop_price = None
        self.take_profit_price = None
        self.current_lot = float(self.p.lots)
        self.losses = 0

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _lot_multiplier(self):
        spread = 0.0
        if float(self.p.take_profit) <= spread:
            return 1.0
        return (float(self.p.take_profit) + float(self.p.stop_loss)) / (float(self.p.take_profit) - spread)

    def _next_lot(self):
        if self.losses <= 0:
            return float(self.p.lots)
        lot = float(self.p.lots) * (self._lot_multiplier() ** self.losses)
        return min(lot, float(self.p.max_lot))

    def _set_risk(self, side, price=None):
        unit = self._unit()
        if price is None:
            price = float(self.data.close[0])
        if side == "buy":
            self.stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits))
        else:
            self.stop_price = round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits))

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if high >= self.take_profit_price or low <= self.stop_price:
                self.order = self.close()
                return True
        else:
            if low <= self.take_profit_price or high >= self.stop_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        """Evaluate Demarker bias, open/exit positions, and apply martingale sizing."""
        self.bar_num += 1
        if len(self) < self.p.ma_period + 1:
            return
        if self.order is not None:
            return
        if self.losses >= int(self.p.losseslimit):
            return
        if self.position:
            self._manage_position()
            return
        size = self._next_lot()
        self.current_lot = size
        if float(self.demarker[0]) > 0.5:
            self.signal_count += 1
            self._set_risk("buy")
            self.order = self.buy(size=size)
        else:
            self.signal_count += 1
            self._set_risk("sell")
            self.order = self.sell(size=size)

    def notify_order(self, order):
        """Update counters, reset risk state, and clear pending references."""
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        """Update trade statistics and reset/increment the consecutive-loss counter."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm > 0:
            self.win_count += 1
            self.losses = 0
        else:
            self.loss_count += 1
            self.losses += 1


def test_021_0022_universum_3_0() -> None:
    """Migrated regression test for multi_indicator_system/0022_universum_3_0."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.addstrategy(Universum30Strategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 6119
    assert strat.buy_count == 1176
    assert strat.sell_count == 1259
    assert strat.win_count == 1189
    assert strat.loss_count == 1245
    assert strat.trade_count == 2434
    assert total_trades == 2434
    assert abs(final_value - 1027839.38) < 0.1
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
