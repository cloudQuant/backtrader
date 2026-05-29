"""Inlined regression test for trend_following/0245_0808_trigger_line.

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


class TriggerLine(bt.Indicator):
    lines = ("main", "signal")
    params = dict(rperiod=24, lsma_period=6, price="close")

    def __init__(self):
        self.addminperiod(int(self.p.rperiod) + 3)
        self.lengthvar = (int(self.p.rperiod) + 1) / 3.0
        self.kr = 6.0 / (float(self.p.rperiod) * (float(self.p.rperiod) + 1.0))
        self.klsma = 2.0 / (float(self.p.lsma_period) + 1.0)

    def _price(self, index=0):
        p = str(self.p.price).lower()
        if p == "open":
            return float(self.data.open[index])
        if p == "high":
            return float(self.data.high[index])
        if p == "low":
            return float(self.data.low[index])
        if p == "median":
            return (float(self.data.high[index]) + float(self.data.low[index])) / 2.0
        if p == "typical":
            return (float(self.data.high[index]) + float(self.data.low[index]) + float(self.data.close[index])) / 3.0
        if p == "weighted":
            return (float(self.data.high[index]) + float(self.data.low[index]) + 2.0 * float(self.data.close[index])) / 4.0
        return float(self.data.close[index])

    def next(self):
        total = 0.0
        rp = int(self.p.rperiod)
        for iii in range(rp, 0, -1):
            idx = -(rp - iii)
            total += (iii - self.lengthvar) * self._price(idx)
        main = total * self.kr
        prev_main = float(self.lines.main[-1]) if len(self) > 1 else main
        self.lines.main[0] = main
        self.lines.signal[0] = prev_main + (main - prev_main) * self.klsma


class ExpTriggerLineStrategy(bt.Strategy):
    params = dict(
        rperiod=24, lsma_period=6, price="close",
        signal_bar=1, stop_loss_points=1000, take_profit_points=2000,
        fixed_lot=0.1, point=0.01,
        buy_pos_open=True, sell_pos_open=True,
        buy_pos_close=True, sell_pos_close=True,
        indicator_minutes=240,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.ind = TriggerLine(
            self.signal_data,
            rperiod=self.p.rperiod, lsma_period=self.p.lsma_period, price=self.p.price,
        )
        self.signal_count = 0
        self.trade_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.bar_num = 0
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
        if len(self.signal_data) < int(self.p.rperiod) + sb + 4:
            return
        if len(self.signal_data) == self._last_signal_len:
            return
        self._last_signal_len = len(self.signal_data)
        ind0 = float(self.ind.main[-sb]) if sb else float(self.ind.main[0])
        ind1 = float(self.ind.main[-(sb + 1)])
        sig0 = float(self.ind.signal[-sb]) if sb else float(self.ind.signal[0])
        sig1 = float(self.ind.signal[-(sb + 1)])
        buy_open = ind1 > sig1 and ind0 <= sig0 and self.p.buy_pos_open
        sell_open = ind1 < sig1 and ind0 >= sig0 and self.p.sell_pos_open
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


def test_244_0245_0808_trigger_line() -> None:
    """Migrated regression test for trend_following/0245_0808_trigger_line."""
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
        ExpTriggerLineStrategy,
        rperiod=24, lsma_period=6, price="close",
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

    assert strat.bar_num == 5724, f"bar_num: expected=5724, got={strat.bar_num}"
    assert strat.buy_count == 20, f"buy_count: expected=20, got={strat.buy_count}"
    assert strat.sell_count == 20, f"sell_count: expected=20, got={strat.sell_count}"
    assert strat.win_count == 15, f"win_count: expected=15, got={strat.win_count}"
    assert strat.loss_count == 25, f"loss_count: expected=25, got={strat.loss_count}"
    assert strat.trade_count == 40, f"trade_count: expected=40, got={strat.trade_count}"
    assert total_trades == 40, f"total_trades: expected=40, got={total_trades}"
    assert abs(final_value - 999870.8) < 0.01, f"final_value: expected=999870.8, got={final_value}"
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
