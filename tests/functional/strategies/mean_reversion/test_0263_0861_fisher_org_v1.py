"""Inlined regression test for mean_reversion/0263_0861_fisher_org_v1.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
import io
import math
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.read().strip().split("\n")
    cleaned = "\n".join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep="\t")
    df["datetime"] = pd.to_datetime(df["<DATE>"] + " " + df["<TIME>"], format="%Y.%m.%d %H:%M:%S")
    df = df.rename(columns={
        "<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low", "<CLOSE>": "close",
        "<TICKVOL>": "volume", "<VOL>": "openinterest",
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


def _build_signal_frame(df, minutes):
    out = df.resample(f"{int(minutes)}min", label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum", "openinterest": "sum",
    })
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["openinterest"] = out["openinterest"].fillna(0)
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


def _price(data, mode, ago=0):
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


class FisherOrgV1(bt.Indicator):
    lines = ("fisher", "trigger")
    params = dict(length=7, ipc=1)

    def __init__(self):
        self.addminperiod(int(self.p.length) + 2)
        self._value1 = 0.0

    def next(self):
        length = int(self.p.length)
        highs = [float(self.data.high[-i]) for i in range(length)]
        lows = [float(self.data.low[-i]) for i in range(length)]
        smax = max(highs)
        smin = min(lows)
        if smax == smin:
            smax += 1e-12
        price = _price(self.data, int(self.p.ipc), 0)
        wpr = (price - smin) / (smax - smin)
        value0 = (wpr - 0.5) + 0.67 * self._value1
        value0 = min(max(value0, -0.999), 0.999)
        fisher_prev = float(self.lines.fisher[-1]) if len(self) > 1 else 0.0
        if not math.isfinite(fisher_prev):
            fisher_prev = 0.0
        res2 = (1.0 + value0) / (1.0 - value0)
        if res2 < 1e-7:
            res2 = 1.0
        fisher = 0.5 * math.log(res2) + 0.5 * fisher_prev
        self.lines.fisher[0] = fisher
        self.lines.trigger[0] = fisher_prev
        self._value1 = value0


class ExpFisherOrgV1Strategy(bt.Strategy):
    params = dict(
        length=7, ipc=1,
        signal_bar=1, stop_loss_points=1000, take_profit_points=2000,
        fixed_lot=0.1, point=0.01,
        buy_pos_open=True, sell_pos_open=True,
        buy_pos_close=True, sell_pos_close=True,
        indicator_minutes=480,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.ind = FisherOrgV1(self.signal_data, length=self.p.length, ipc=self.p.ipc)
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

    def next(self):
        self.bar_num += 1
        if self._check_exit_levels():
            return
        sb = max(int(self.p.signal_bar) - 1, 0)
        if len(self.signal_data) < int(self.p.length) + sb + 4:
            return
        if len(self.signal_data) == self._last_signal_len:
            return
        self._last_signal_len = len(self.signal_data)
        ind0 = float(self.ind.fisher[-sb]) if sb else float(self.ind.fisher[0])
        ind1 = float(self.ind.fisher[-(sb + 1)])
        sig0 = float(self.ind.trigger[-sb]) if sb else float(self.ind.trigger[0])
        sig1 = float(self.ind.trigger[-(sb + 1)])
        buy_open = ind1 > sig1 and ind0 <= sig0 and self.p.buy_pos_open
        sell_open = ind1 < sig1 and ind0 >= sig0 and self.p.sell_pos_open
        if not buy_open and not sell_open:
            buy_open = ind0 > sig0 and self.p.buy_pos_open
            sell_open = ind0 < sig0 and self.p.sell_pos_open
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


def test_262_0263_0861_fisher_org_v1() -> None:
    """Migrated regression test for mean_reversion/0263_0861_fisher_org_v1."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)
    signal_df = _build_signal_frame(df, 480)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.adddata(Mt5PandasFeed(dataname=signal_df, timeframe=bt.TimeFrame.Minutes, compression=480))
    cerebro.addstrategy(ExpFisherOrgV1Strategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 5860
    assert strat.buy_count == 95
    assert strat.sell_count == 90
    assert strat.win_count == 86
    assert strat.loss_count == 98
    assert strat.trade_count == 184
    assert total_trades == 184
    assert abs(final_value - 1005259.6) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
