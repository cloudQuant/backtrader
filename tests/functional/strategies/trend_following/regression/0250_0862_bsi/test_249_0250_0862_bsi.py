"""Inlined regression test for trend_following/0250_0862_bsi.

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


class BSIIndicator(bt.Indicator):
    lines = ("bsi", "color")
    params = dict(range_period=20, slowing=3, avg_period=3, volume_mode="TICK")

    def __init__(self):
        self.addminperiod(int(self.p.range_period) + int(self.p.slowing) + int(self.p.avg_period) + 3)

    def _component(self, ago):
        sumpos = 0.0
        sumneg = 0.0
        sumhigh = 0.0
        for k in range(int(self.p.slowing)):
            idx = ago + k
            highs = [float(self.data.high[-(idx + j)]) for j in range(int(self.p.range_period))]
            lows = [float(self.data.low[-(idx + j)]) for j in range(int(self.p.range_period))]
            hh = max(highs)
            ll = min(lows)
            rng = max(hh - ll, 1e-12)
            bark_close = float(self.data.close[-idx])
            bark_prev_close = float(self.data.close[-(idx + 1)])
            bark_high = float(self.data.high[-idx])
            bark_low = float(self.data.low[-idx])
            sp = bark_high - bark_low
            if self.p.volume_mode == "NONE":
                vol = 1.0
            elif self.p.volume_mode == "VOLUME":
                vmax = max(float(self.data.openinterest[-(idx + j)]) for j in range(int(self.p.range_period)))
                vol = float(self.data.openinterest[-idx]) / vmax if vmax else 0.0
            else:
                vmax = max(float(self.data.volume[-(idx + j)]) for j in range(int(self.p.range_period)))
                vol = float(self.data.volume[-idx]) / vmax if vmax else 0.0
            ratio = 0.0
            if not (bark_prev_close - sp * 0.2 > bark_close):
                ratio = 1.0 if bark_low == ll else (hh - bark_low) / rng
                sumpos += (bark_close - bark_low) * ratio * vol
            if not (bark_prev_close + sp * 0.2 < bark_close):
                ratio = 1.0 if bark_high == hh else (bark_high - ll) / rng
                sumneg += (bark_high - bark_close) * ratio * vol * -1.0
            sumhigh += rng
        if not sumhigh:
            return 0.0
        return (sumpos / sumhigh * 100.0) + (sumneg / sumhigh * 100.0)

    def next(self):
        vals = [self._component(i) for i in range(int(self.p.avg_period))]
        bsi = sum(vals) / float(int(self.p.avg_period))
        self.lines.bsi[0] = bsi
        if len(self) < 2:
            self.lines.color[0] = 1.0
            return
        prev = float(self.lines.bsi[-1])
        color = 1.0
        if prev > bsi:
            color = 0.0
        if prev < bsi:
            color = 2.0
        self.lines.color[0] = color


class ExpBSIStrategy(bt.Strategy):
    params = dict(
        range_period=20, slowing=3, avg_period=3, volume_mode="TICK",
        signal_bar=1, stop_loss_points=1000, take_profit_points=2000,
        fixed_lot=0.1, point=0.01,
        buy_pos_open=True, sell_pos_open=True,
        buy_pos_close=True, sell_pos_close=True,
        indicator_minutes=240,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.ind = BSIIndicator(
            self.signal_data,
            range_period=self.p.range_period, slowing=self.p.slowing,
            avg_period=self.p.avg_period, volume_mode=self.p.volume_mode,
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

    def next(self):
        self.bar_num += 1
        if self._check_exit_levels():
            return
        sb = max(int(self.p.signal_bar) - 1, 0)
        if len(self.signal_data) < int(self.p.range_period) + int(self.p.slowing) + int(self.p.avg_period) + sb + 4:
            return
        if len(self.signal_data) == self._last_signal_len:
            return
        self._last_signal_len = len(self.signal_data)
        c0 = float(self.ind.color[-sb]) if sb else float(self.ind.color[0])
        c1 = float(self.ind.color[-(sb + 1)])
        buy_open = c1 == 2.0 and c0 != 2.0 and self.p.buy_pos_open
        sell_open = c1 == 0.0 and c0 != 0.0 and self.p.sell_pos_open
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


def test_249_0250_0862_bsi() -> None:
    """Migrated regression test for trend_following/0250_0862_bsi."""
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
        ExpBSIStrategy,
        range_period=20, slowing=3, avg_period=3, volume_mode="TICK",
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

    assert strat.bar_num == 5692
    assert strat.buy_count == 61
    assert strat.sell_count == 62
    assert strat.win_count == 47
    assert strat.loss_count == 76
    assert strat.trade_count == 123
    assert total_trades == 123
    assert abs(final_value - 999641.6) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
