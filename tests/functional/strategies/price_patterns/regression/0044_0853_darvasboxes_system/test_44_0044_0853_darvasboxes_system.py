"""Inlined regression test for price_patterns/0044_0853_darvasboxes_system.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[6]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.read().strip().split("\n")
    cleaned = "\n".join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep="\t")
    df["datetime"] = pd.to_datetime(df["<DATE>"] + " " + df["<TIME>"], format="%Y.%m.%d %H:%M:%S")
    df = df.rename(columns={
        "<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low",
        "<CLOSE>": "close", "<TICKVOL>": "volume", "<VOL>": "openinterest",
    })
    df = df[["datetime", "open", "high", "low", "close", "volume", "openinterest"]]
    df = df.set_index("datetime").sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class DarvasBoxesSystem(bt.Indicator):
    lines = ("color",)
    params = dict(symmetry=True, shift=2)

    def __init__(self):
        self.addminperiod(int(self.p.shift) + 8)
        self.state = 0
        self.box_top = None
        self.box_bottom = None

    def next(self):
        if self.box_top is None:
            self.box_top = float(self.data.high[-1])
            self.box_bottom = float(self.data.low[-1])
            self.state = 1
        bar_high = float(self.data.high[0])
        bar_low = float(self.data.low[0])
        if self.state == 1:
            self.box_top = bar_high
            if self.p.symmetry:
                self.box_bottom = bar_low
        elif self.state == 2:
            if self.box_top <= bar_high:
                self.box_top = bar_high
        elif self.state == 3:
            if self.box_top > bar_high:
                self.box_bottom = bar_low
            else:
                self.box_top = bar_high
        elif self.state == 4:
            if self.box_top > bar_high:
                if self.box_bottom >= bar_low:
                    self.box_bottom = bar_low
            else:
                self.box_top = bar_high
        elif self.state == 5:
            if self.box_top > bar_high:
                if self.box_bottom >= bar_low:
                    self.box_bottom = bar_low
            else:
                self.box_top = bar_high
            self.state = 0
        self.state += 1
        shift = int(self.p.shift)
        close = float(self.data.close[0])
        open_ = float(self.data.open[0])
        color = 2.0
        if len(self.data) > shift and close > self.box_top:
            color = 4.0 if open_ < close else 3.0
        if len(self.data) > shift and close < self.box_bottom:
            color = 0.0 if open_ > close else 1.0
        self.lines.color[0] = color


class ExpDarvasBoxesSystemStrategy(bt.Strategy):
    params = dict(
        symmetry=True, shift=2,
        signal_bar=1, stop_loss_points=1000, take_profit_points=2000,
        fixed_lot=0.1, point=0.01,
        buy_pos_open=True, sell_pos_open=True,
        buy_pos_close=True, sell_pos_close=True,
        indicator_minutes=240,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.ind = DarvasBoxesSystem(self.signal_data, symmetry=self.p.symmetry, shift=self.p.shift)
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
        ep = float(self.position.price)
        sd = self.p.stop_loss_points * pv
        td = self.p.take_profit_points * pv
        if self.position.size > 0 and (cp <= ep - sd or cp >= ep + td):
            self.close()
            return True
        if self.position.size < 0 and (cp >= ep + sd or cp <= ep - td):
            self.close()
            return True
        return False

    def next(self):
        self.bar_num += 1
        if self._check_exit_levels():
            return
        sb = max(int(self.p.signal_bar) - 1, 0)
        if len(self.signal_data) < int(self.p.shift) + sb + 8:
            return
        if len(self.signal_data) == self._last_signal_len:
            return
        self._last_signal_len = len(self.signal_data)
        c0 = float(self.ind.color[-sb]) if sb else float(self.ind.color[0])
        c1 = float(self.ind.color[-(sb + 1)])
        buy_open = c1 > 2.0 and c0 < 3.0 and self.p.buy_pos_open
        sell_open = c1 < 2.0 and c0 > 1.0 and self.p.sell_pos_open
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


def test_44_0044_0853_darvasboxes_system() -> None:
    """Migrated regression test for price_patterns/0044_0853_darvasboxes_system."""
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
        ExpDarvasBoxesSystemStrategy,
        symmetry=True, shift=2,
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

    assert strat.bar_num == 5984, f"bar_num: expected=5984, got={strat.bar_num}"
    assert strat.buy_count == 0, f"buy_count: expected=0, got={strat.buy_count}"
    assert strat.sell_count == 11, f"sell_count: expected=11, got={strat.sell_count}"
    assert strat.win_count == 3, f"win_count: expected=3, got={strat.win_count}"
    assert strat.loss_count == 8, f"loss_count: expected=8, got={strat.loss_count}"
    assert strat.trade_count == 11, f"trade_count: expected=11, got={strat.trade_count}"
    assert total_trades == 11, f"total_trades: expected=11, got={total_trades}"
    assert abs(final_value - 999221.4) < 0.01, f"final_value: expected=999221.4, got={final_value}"
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
