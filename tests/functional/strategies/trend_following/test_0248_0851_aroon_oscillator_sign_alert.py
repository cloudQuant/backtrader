"""Inlined regression test for trend_following/0248_0851_aroon_oscillator_sign_alert.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations
import backtrader as bt

import datetime
import math
from pathlib import Path

from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


class Mt5PandasFeed(bt.feeds.PandasData):
    """Pandas feed mapping default OHLCV columns for this test."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class ExpAroonOscillatorSignAlertStrategy(bt.Strategy):
    """Crosses-based trend-following strategy using Aroon oscillator alerts."""
    params = dict(
        atr_period=14, aroon_period=9, up_level=50, dn_level=-50,
        signal_bar=1, stop_loss_points=1000, take_profit_points=2000,
        fixed_lot=0.1, point=0.01,
        buy_pos_open=True, sell_pos_open=True,
        buy_pos_close=True, sell_pos_close=True,
        indicator_minutes=240,
    )

    def __init__(self):
        """Attach data feeds and indicator; initialize counters/state."""
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.ind = bt.indicators.AroonOscillatorSignAlert(
            self.signal_data,
            atr_period=self.p.atr_period, aroon_period=self.p.aroon_period,
            up_level=self.p.up_level, dn_level=self.p.dn_level,
        )
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

    def _has(self, line, offset):
        v = float(line[-offset]) if offset else float(line[0])
        return not math.isnan(v) and v != 0.0

    def next(self):
        """Evaluate exit conditions, optional signal history, and place entries."""
        self.bar_num += 1
        if self._check_exit_levels():
            return
        sb = max(int(self.p.signal_bar) - 1, 0)
        if len(self.signal_data) < max(int(self.p.atr_period), int(self.p.aroon_period)) + sb + 4:
            return
        if len(self.signal_data) == self._last_signal_len:
            return
        self._last_signal_len = len(self.signal_data)
        buy_open = self._has(self.ind.buy, sb) and self.p.buy_pos_open
        sell_open = self._has(self.ind.sell, sb) and self.p.sell_pos_open
        buy_close = sell_open and self.p.buy_pos_close
        sell_close = buy_open and self.p.sell_pos_close
        if (self.p.buy_pos_open and self.p.buy_pos_close) or (self.p.sell_pos_open and self.p.sell_pos_close):
            if not buy_close and self.p.sell_pos_close:
                for bar in range(sb + 1, len(self.signal_data) - 1):
                    if self._has(self.ind.buy, bar):
                        sell_close = True
                        break
            if not sell_close and self.p.buy_pos_close:
                for bar in range(sb + 1, len(self.signal_data) - 1):
                    if self._has(self.ind.sell, bar):
                        buy_close = True
                        break
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
        """Track entry direction and win/loss counters for closed trades."""
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


def test_247_0248_0851_aroon_oscillator_sign_alert() -> None:
    """Migrated regression test for trend_following/0248_0851_aroon_oscillator_sign_alert."""
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
        ExpAroonOscillatorSignAlertStrategy,
        atr_period=14, aroon_period=9, up_level=50, dn_level=-50,
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

    assert strat.bar_num == 5876, f"bar_num: expected=5876, got={strat.bar_num}"
    assert strat.buy_count == 28, f"buy_count: expected=28, got={strat.buy_count}"
    assert strat.sell_count == 13, f"sell_count: expected=13, got={strat.sell_count}"
    assert strat.win_count == 18, f"win_count: expected=18, got={strat.win_count}"
    assert strat.loss_count == 23, f"loss_count: expected=23, got={strat.loss_count}"
    assert strat.trade_count == 41, f"trade_count: expected=41, got={strat.trade_count}"
    assert total_trades == 41, f"total_trades: expected=41, got={total_trades}"
    assert abs(final_value - 1001300.2) < 0.01, f"final_value: expected=1001300.2, got={final_value}"
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
