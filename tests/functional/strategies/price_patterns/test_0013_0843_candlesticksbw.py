"""Inlined regression test for the CandlesticksBW strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.

Data Used:
    XAUUSD 15-minute MT5 data from ``tests/datas/XAUUSD_M15.csv``.

Strategy Principle:
    Uses Awesome Oscillator / AC color shifts on resampled 4H bars to generate
    candle-color transition entries for trend continuation and uses stop-loss /
    take-profit for exits.

Strategy Logic:
    ``CandlesticksBW`` computes color codes from AO/AC momentum.
    ``ExpCandlesticksBWStrategy`` aligns signal bars with the configured shift and
    issues buy/sell orders on bullish-to-bearish or bearish-to-bullish transitions.
"""
from __future__ import annotations
import backtrader as bt

import datetime
from pathlib import Path

from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


class Mt5PandasFeed(bt.feeds.PandasData):
    """PandasData feed for M15/4H OHLCV input bars."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class ExpCandlesticksBWStrategy(bt.Strategy):
    """Execution strategy for CandlesticksBW signal transitions."""
    params = dict(
        length=2,
        signal_bar=1, stop_loss_points=1000, take_profit_points=2000,
        fixed_lot=0.1, point=0.01,
        buy_pos_open=True, sell_pos_open=True,
        buy_pos_close=True, sell_pos_close=True,
        indicator_minutes=240,
    )

    def __init__(self):
        """Initialize indicators, data references, and accounting counters."""
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.ind = bt.indicators.CandlesticksBW(self.signal_data)
        self.bar_num = 0
        self.signal_count = 0
        self.trade_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._last_signal_len = 0

    def _check_exit_levels(self):
        if not self.position:
            return False
        cp = float(self.base.close[0])
        pv = float(self.p.point)
        sd = self.p.stop_loss_points * pv
        td = self.p.take_profit_points * pv
        ep = float(self.position.price)
        if self.position.size > 0 and (cp <= ep - sd or cp >= ep + td):
            self.close()
            return True
        if self.position.size < 0 and (cp >= ep + sd or cp <= ep - td):
            self.close()
            return True
        return False

    def next(self):
        """Evaluate transitions and issue entry/exit orders on signal changes."""
        self.bar_num += 1
        if self._check_exit_levels():
            return
        sb = max(int(self.p.signal_bar) - 1, 0)
        if len(self.signal_data) < 40 + sb + 3:
            return
        if len(self.signal_data) == self._last_signal_len:
            return
        self._last_signal_len = len(self.signal_data)
        c0 = float(self.ind.color[-sb]) if sb else float(self.ind.color[0])
        c1 = float(self.ind.color[-(sb + 1)])
        buy_open = c1 < 2.0 and c0 > 1.0 and self.p.buy_pos_open
        sell_open = c1 > 3.0 and c0 < 4.0 and self.p.sell_pos_open
        buy_close = sell_open and self.p.buy_pos_close
        sell_close = buy_open and self.p.sell_pos_close
        if sell_close and self.position.size < 0:
            self.close()
        if buy_close and self.position.size > 0:
            self.close()
        if buy_open and self.position.size <= 0:
            self.signal_count += 1
            self.buy(size=float(self.p.fixed_lot))
        if sell_open and self.position.size >= 0:
            self.signal_count += 1
            self.sell(size=float(self.p.fixed_lot))

    def notify_trade(self, trade):
        """Track trade lifecycle state and win/loss statistics.

        Args:
            trade: Closed or opened trade notification.
        """
        if trade.isopen and not self._position_was_open:
            self._position_was_open = True
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False


def _build_signal_frame(df, minutes):
    out = df.resample(
        f"{int(minutes)}min", label="right", closed="right",
    ).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum", "openinterest": "sum",
    })
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["openinterest"] = out["openinterest"].fillna(0)
    return out


def test_13_0013_0843_candlesticksbw() -> None:
    """Migrated regression test for price_patterns/0013_0843_candlesticksbw."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)
    signal_df = _build_signal_frame(df, 240)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.adddata(Mt5PandasFeed(dataname=signal_df, timeframe=bt.TimeFrame.Minutes, compression=240))
    cerebro.addstrategy(
        ExpCandlesticksBWStrategy,
        length=2,
        signal_bar=1, stop_loss_points=1000, take_profit_points=2000,
        fixed_lot=0.1, point=0.01,
        buy_pos_open=True, sell_pos_open=True,
        buy_pos_close=True, sell_pos_close=True,
    )
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 5524, f"bar_num: expected=5524, got={strat.bar_num}"
    assert strat.buy_count == 33, f"buy_count: expected=33, got={strat.buy_count}"
    assert strat.sell_count == 33, f"sell_count: expected=33, got={strat.sell_count}"
    assert strat.win_count == 28, f"win_count: expected=28, got={strat.win_count}"
    assert strat.loss_count == 38, f"loss_count: expected=38, got={strat.loss_count}"
    assert strat.trade_count == 66, f"trade_count: expected=66, got={strat.trade_count}"
    assert total_trades == 66, f"total_trades: expected=66, got={total_trades}"
    assert abs(final_value - 1000512.3) < 0.01, f"final_value: expected=1000512.3, got={final_value}"
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
