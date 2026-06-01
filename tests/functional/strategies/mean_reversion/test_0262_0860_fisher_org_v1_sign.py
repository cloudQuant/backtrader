"""Inlined regression test for mean_reversion/0262_0860_fisher_org_v1_sign.

Self-contained single-file test (manually authored). Runs with runonce=True only.

Data Used:
- XAUUSD M15 (primary): 2025-12-03 01:15 to 2026-03-10 09:00
- XAUUSD H4 (signal): resampled from M15

Strategy Principle:
Fisher Transform Org V1 Sign is a dual-timeframe mean-reversion strategy
that applies the Fisher Transform to normalized price (range position) to
identify extreme readings that signal impending reversals. The indicator
detects crossovers of the Fisher line through configurable threshold levels.

Strategy Logic:
- FisherOrgV1Sign indicator normalizes price using highest-high/lowest-low
  over `length` bars, smooths it through a recursive formula, then applies
  the Fisher Transform (atanh) to produce a Gaussian-like signal
- Buy signal: Fisher crosses above dn_level from below (extreme low reversal)
- Sell signal: Fisher crosses below up_level from above (extreme high reversal)
- Signal lines store ATR-scaled price levels (low - 3/8 ATR for buys,
  high + 3/8 ATR for sells)
- The strategy fires once per new H4 bar, with stop-loss/take-profit at
  fixed point distances, configurable buy/sell open/close gating
"""
from __future__ import annotations
import backtrader as bt

import datetime
import math
from pathlib import Path

from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


def _build_signal_frame(df, minutes):
    """Resample a DataFrame to a lower-frequency signal frame for dual-timeframe strategies."""
    out = df.resample(f"{int(minutes)}min", label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum", "openinterest": "sum",
    })
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["openinterest"] = out["openinterest"].fillna(0)
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    """PandasData feed configured for MT5-exported CSV column ordering."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


def _price(data, mode, ago=0):
    """Return a price value from OHLC data based on a mode selector.

    Parameters
    ----------
    data : DataFeed
        Data feed with open/high/low/close lines.
    mode : int
        Price mode: 2=open, 3=high, 4=low, 5=(h+l)/2, 6=(h+l+c)/3,
        7=(2c+h+l)/4, 8=(o+c)/2, 9=(o+h+l+c)/4; default returns close.
    ago : int
        Bar offset.

    Returns
    -------
    float
        Selected price value.
    """
    o = float(data.open[-ago])
    h = float(data.high[-ago])
    l = float(data.low[-ago])
    c = float(data.close[-ago])
    if mode == 2:
        return o
    if mode == 3:
        return h
    if mode == 4:
        return l
    if mode == 5:
        return (h + l) / 2.0
    if mode == 6:
        return (h + l + c) / 3.0
    if mode == 7:
        return (2.0 * c + h + l) / 4.0
    if mode == 8:
        return (o + c) / 2.0
    if mode == 9:
        return (o + h + l + c) / 4.0
    return c


class ExpFisherOrgV1SignStrategy(bt.Strategy):
    """Dual-timeframe strategy trading FisherOrgV1Sign signals on H4 data."""
    params = dict(
        atr_period=14, length=7, ipc=1, up_level=1.5, dn_level=-1.5,
        signal_bar=1,
        stop_loss_points=1000, take_profit_points=2000,
        fixed_lot=0.1, point=0.01,
        buy_pos_open=True, sell_pos_open=True,
        buy_pos_close=True, sell_pos_close=True,
        indicator_minutes=240,
    )

    def __init__(self):
        """Initialize strategy state, indicators, and tracking counters.

        This binds both M15 and H4 data feeds, creates the signal indicator,
        and prepares performance counters used by assertions in the regression
        test.
        """
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.ind = bt.indicators.FisherOrgV1Sign(
            self.signal_data,
            atr_period=self.p.atr_period, length=self.p.length, ipc=self.p.ipc,
            up_level=self.p.up_level, dn_level=self.p.dn_level,
        )
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
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
        """Process a new bar: check exit levels, fire buy/sell signals on H4 transitions."""
        self.bar_num += 1
        if self._check_exit_levels():
            return
        sb = max(int(self.p.signal_bar) - 1, 0)
        if len(self.signal_data) < max(int(self.p.atr_period), int(self.p.length)) + sb + 4:
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
        """Track trade lifecycle: count open direction and record win/loss on close."""
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False


def test_261_0262_0860_fisher_org_v1_sign() -> None:
    """Migrated regression test for mean_reversion/0262_0860_fisher_org_v1_sign."""
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
    cerebro.addstrategy(ExpFisherOrgV1SignStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 5876
    assert strat.buy_count == 5
    assert strat.sell_count == 15
    assert strat.win_count == 5
    assert strat.loss_count == 15
    assert strat.trade_count == 20
    assert total_trades == 20
    assert abs(final_value - 1000346.2) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
