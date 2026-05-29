"""Inlined regression test for trend_following/0076_0830_fibonacci_retracement.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
import io
from collections import deque
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


class ZigZagRetracementState:
    def __init__(self, depth=12, deviation=5, backstep=3, trend_precision=-5, point=0.0001):
        self.depth = int(depth)
        self.deviation = float(deviation) * float(point)
        self.backstep = int(backstep)
        self.trend_precision = float(trend_precision) * float(point)
        self.pivots = deque(maxlen=8)
        self._last_pivot_price = None
        self._last_pivot_kind = None

    def update(self, highs, lows, times):
        if len(highs) < self.depth * 2 + 1:
            return
        idx = len(highs) - self.depth - 1
        center_high = highs[idx]
        center_low = lows[idx]
        left = max(0, idx - self.depth)
        right = min(len(highs), idx + self.depth + 1)
        win_high = max(highs[left:right])
        win_low = min(lows[left:right])
        pivot = None
        if center_high == win_high:
            pivot = ("high", center_high, times[idx])
        if center_low == win_low:
            low_pivot = ("low", center_low, times[idx])
            if pivot is None or abs(center_low - lows[max(left, idx - 1)]) >= abs(center_high - highs[max(left, idx - 1)]):
                pivot = low_pivot
        if pivot is None:
            return
        kind, price, when = pivot
        if self._last_pivot_price is not None:
            if kind == self._last_pivot_kind:
                better = (kind == "high" and price >= self._last_pivot_price) or (kind == "low" and price <= self._last_pivot_price)
                if better and self.pivots:
                    self.pivots[-1] = pivot
                    self._last_pivot_price = price
                return
            if abs(price - self._last_pivot_price) < self.deviation:
                return
            if self.pivots and (when - self.pivots[-1][2]).total_seconds() <= self.backstep * 60:
                return
        self.pivots.append(pivot)
        self._last_pivot_kind = kind
        self._last_pivot_price = price

    def trend(self):
        if len(self.pivots) < 4:
            return 0
        hl0 = self.pivots[-1][1]
        hl1 = self.pivots[-2][1]
        hl2 = self.pivots[-3][1]
        hl3 = self.pivots[-4][1]
        if (hl2 - hl0) > self.trend_precision and (hl3 - hl1) > self.trend_precision:
            return -1
        if (hl0 - hl2) > self.trend_precision and (hl1 - hl3) > self.trend_precision:
            return 1
        return 0

    def levels(self):
        if len(self.pivots) < 2:
            return None
        fibo00 = self.pivots[-1][1]
        fibo100 = self.pivots[-2][1]
        trend = self.trend()
        if trend == 1:
            base = fibo00 - fibo100
            return {"trend": trend, "fibo00": fibo00, "fibo100": fibo100, "base": base,
                    "levels": [fibo00 - 0.236 * base, fibo00 - 0.382 * base, fibo00 - 0.618 * base, fibo00 - 0.764 * base]}
        if trend == -1:
            base = fibo100 - fibo00
            return {"trend": trend, "fibo00": fibo00, "fibo100": fibo100, "base": base,
                    "levels": [fibo00 + 0.236 * base, fibo00 + 0.382 * base, fibo00 + 0.618 * base, fibo00 + 0.764 * base]}
        return {"trend": 0, "fibo00": fibo00, "fibo100": fibo100, "base": abs(fibo100 - fibo00), "levels": []}


class FibonacciRetracementStrategy(bt.Strategy):
    params = dict(
        ext_depth=12,
        ext_deviation=5,
        ext_backstep=3,
        trade_value=0.1,
        stop_loss_points=15,
        take_profit_at=0.2,
        safety_buffer=1,
        trend_precision=-5,
        close_bar_pause=5,
        signal_bar=1,
        point=0.01,
        indicator_minutes=15,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.state = ZigZagRetracementState(
            depth=self.p.ext_depth, deviation=self.p.ext_deviation,
            backstep=self.p.ext_backstep, trend_precision=self.p.trend_precision,
            point=self.p.point,
        )
        self._last_signal_len = 0
        self._last_closed_bar = -10**9
        self.signal_count = 0
        self.trade_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.bar_num = 0
        self._position_was_open = False
        self._entry_tp = None

    def _check_position_exit(self):
        if not self.position:
            return False
        close = float(self.base.close[0])
        entry = float(self.position.price)
        sl_dist = self.p.stop_loss_points * float(self.p.point)
        if self.position.size > 0:
            if close <= entry - sl_dist or (self._entry_tp is not None and close >= self._entry_tp):
                self.close()
                return True
        if self.position.size < 0:
            if close >= entry + sl_dist or (self._entry_tp is not None and close <= self._entry_tp):
                self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self._check_position_exit():
            return
        if len(self.signal_data) < self.p.ext_depth * 2 + 5:
            return
        if len(self.signal_data) == self._last_signal_len:
            return
        self._last_signal_len = len(self.signal_data)
        highs = [float(self.signal_data.high[-i]) for i in range(len(self.signal_data) - 1, -1, -1)]
        lows = [float(self.signal_data.low[-i]) for i in range(len(self.signal_data) - 1, -1, -1)]
        times = [bt.num2date(self.signal_data.datetime[-i]) for i in range(len(self.signal_data) - 1, -1, -1)]
        self.state.update(highs, lows, times)
        fib = self.state.levels()
        if fib is None or fib["trend"] == 0 or self.position:
            return
        if self.bar_num - self._last_closed_bar < int(self.p.close_bar_pause):
            return
        current_close = float(self.signal_data.close[0])
        prev_close = float(self.signal_data.close[-1])
        buf = float(self.p.safety_buffer) * float(self.p.point)
        if fib["trend"] == 1:
            crossed = any((current_close - level) > buf and (level - prev_close) > buf for level in fib["levels"])
            if crossed:
                self.signal_count += 1
                self._entry_tp = fib["fibo00"] + float(self.p.take_profit_at) * fib["base"]
                self.buy(size=float(self.p.trade_value))
        elif fib["trend"] == -1:
            crossed = any((level - current_close) > buf and (level - prev_close) < buf for level in fib["levels"])
            if crossed:
                self.signal_count += 1
                self._entry_tp = fib["fibo00"] - float(self.p.take_profit_at) * fib["base"]
                self.sell(size=float(self.p.trade_value))

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
        self._last_closed_bar = self.bar_num
        self._entry_tp = None
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


def test_075_0076_0830_fibonacci_retracement() -> None:
    """Migrated regression test for trend_following/0076_0830_fibonacci_retracement."""
    fromdate = datetime.datetime(2026, 3, 1, 0, 0)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)
    signal_df = _build_signal_frame(df, 15)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.adddata(Mt5PandasFeed(dataname=signal_df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.addstrategy(FibonacciRetracementStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 581, f"bar_num: expected=581, got={strat.bar_num}"
    assert strat.buy_count == 14, f"buy_count: expected=14, got={strat.buy_count}"
    assert strat.sell_count == 9, f"sell_count: expected=9, got={strat.sell_count}"
    assert strat.win_count == 3, f"win_count: expected=3, got={strat.win_count}"
    assert strat.loss_count == 20, f"loss_count: expected=20, got={strat.loss_count}"
    assert strat.trade_count == 23, f"trade_count: expected=23, got={strat.trade_count}"
    assert total_trades == 23, f"total_trades: expected=23, got={total_trades}"
    assert abs(final_value - 998354.8) < 0.01, f"final_value: expected=998354.8, got={final_value}"
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
