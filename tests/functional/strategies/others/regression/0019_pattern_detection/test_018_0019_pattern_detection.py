"""Inlined regression test for others/0019_pattern_detection.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[6]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_1d.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None):
    with open(filepath, "r", encoding="utf-8", errors="ignore") as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = "\n".join(lines)
    sep = "\t" if "\t" in lines[0] else ","
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = df["<DATE>"].astype(str) + " " + df["<TIME>"].astype(str)
    parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M", errors="coerce")
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M:%S", errors="coerce")
    df["datetime"] = parsed
    df = df.rename(columns={"<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low", "<CLOSE>": "close",
                             "<TICKVOL>": "tick_volume", "<VOL>": "real_volume"})
    df["openinterest"] = 0
    df["volume"] = df["tick_volume"] if "tick_volume" in df.columns else 0
    df = df[["datetime", "open", "high", "low", "close", "volume", "openinterest"]]
    df = df.dropna(subset=["datetime"]).set_index("datetime").sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def _calc_quality(neckline_diff, shoulder_symmetry, head_depth, threshold):
    neckline_score = max(0.0, 1.0 - neckline_diff / max(threshold, 1e-9))
    symmetry_score = max(0.0, 1.0 - shoulder_symmetry * 10.0)
    depth_score = 1.0 if 0.05 < head_depth < 0.3 else 0.5
    return neckline_score * 0.4 + symmetry_score * 0.3 + depth_score * 0.3


def prepare_pattern_features(df, params):
    smoothing = int(params.get("smoothing", 10))
    window_range = int(params.get("window_range", 10))
    neckline_threshold = float(params.get("neckline_threshold", 0.03))
    min_pattern_bars = int(params.get("min_pattern_bars", 20))
    min_quality = float(params.get("min_quality", 0.55))
    breakout_lookahead = int(params.get("breakout_lookahead", 20))
    atr_period = int(params.get("atr_period", 14))
    out = df[["open", "high", "low", "close", "volume", "openinterest"]].copy()
    out["smooth"] = out["close"].ewm(span=smoothing, adjust=False).mean()
    out["returns"] = out["close"].pct_change()
    prev_close = out["close"].shift(1)
    tr = pd.concat([(out["high"] - out["low"]), (out["high"] - prev_close).abs(), (out["low"] - prev_close).abs()], axis=1).max(axis=1)
    out["atr"] = tr.rolling(atr_period).mean()
    out["is_peak"] = (out["smooth"] == out["smooth"].rolling(window_range * 2 + 1, center=True).max()).astype(float)
    out["is_trough"] = (out["smooth"] == out["smooth"].rolling(window_range * 2 + 1, center=True).min()).astype(float)
    extrema = [(i, float(out["smooth"].iloc[i])) for i in range(len(out)) if out["is_peak"].iloc[i] > 0.5 or out["is_trough"].iloc[i] > 0.5]
    entry_signal = [0.0] * len(out)
    direction = [0.0] * len(out)
    neckline = [float("nan")] * len(out)
    stop_level = [float("nan")] * len(out)
    target_level = [float("nan")] * len(out)
    pattern_quality = [0.0] * len(out)
    pattern_type = [0.0] * len(out)
    used_until = -1
    for idx in range(len(extrema) - 4):
        bars = [extrema[idx + j][0] for j in range(5)]
        vals = [extrema[idx + j][1] for j in range(5)]
        if bars[-1] - bars[0] < min_pattern_bars or bars[0] <= used_until:
            continue
        A, B, C, D, E = vals
        pattern = None
        if C < min(A, B, D, E) and A < B and A < D and E < B and E < D:
            nl = (B + D) / 2.0
            nl_diff = abs(B - D) / max(abs(nl), 1e-9)
            if nl_diff <= neckline_threshold:
                quality = _calc_quality(nl_diff, abs(A - E) / max(abs(nl), 1e-9), (nl - C) / max(abs(C), 1e-9), neckline_threshold)
                if quality >= min_quality:
                    pattern = ("inverse_hs", 1.0, nl, C, quality)
        elif C > max(A, B, D, E) and A > B and A > D and E > B and E > D:
            nl = (B + D) / 2.0
            nl_diff = abs(B - D) / max(abs(nl), 1e-9)
            if nl_diff <= neckline_threshold:
                quality = _calc_quality(nl_diff, abs(A - E) / max(abs(nl), 1e-9), (C - nl) / max(abs(C), 1e-9), neckline_threshold)
                if quality >= min_quality:
                    pattern = ("hs_top", -1.0, nl, C, quality)
        if pattern is None:
            continue
        _, dirn, nl, head, quality = pattern
        scan_end = min(len(out), bars[-1] + breakout_lookahead + 1)
        breakout_bar = None
        for j in range(bars[-1] + 1, scan_end):
            close = float(out["close"].iloc[j])
            if dirn > 0 and close > nl:
                breakout_bar = j
                break
            if dirn < 0 and close < nl:
                breakout_bar = j
                break
        if breakout_bar is None:
            continue
        atr = float(out["atr"].iloc[breakout_bar]) if pd.notna(out["atr"].iloc[breakout_bar]) else float(out["close"].iloc[breakout_bar]) * 0.01
        if dirn > 0:
            stop = head - atr * 2.0
            target = nl + (nl - head) * 1.5
            ptype = 1.0
        else:
            stop = head + atr * 2.0
            target = nl - (head - nl) * 1.5
            ptype = -1.0
        entry_signal[breakout_bar] = 1.0
        direction[breakout_bar] = dirn
        neckline[breakout_bar] = nl
        stop_level[breakout_bar] = stop
        target_level[breakout_bar] = target
        pattern_quality[breakout_bar] = quality
        pattern_type[breakout_bar] = ptype
        used_until = breakout_bar
    out["entry_signal"] = entry_signal
    out["direction"] = direction
    out["neckline"] = neckline
    out["stop_level"] = stop_level
    out["target_level"] = target_level
    out["pattern_quality"] = pattern_quality
    out["pattern_type"] = pattern_type
    out["neckline"] = out["neckline"].fillna(out["close"])
    out["stop_level"] = out["stop_level"].fillna(out["close"])
    out["target_level"] = out["target_level"].fillna(out["close"])
    cols = ["open", "high", "low", "close", "volume", "openinterest", "atr", "entry_signal", "direction", "neckline", "stop_level", "target_level", "pattern_quality", "pattern_type"]
    out = out[cols].copy()
    return out.dropna(subset=["atr"]).copy()


class PatternDetectionFeed(bt.feeds.PandasData):
    lines = ("atr", "entry_signal", "direction", "neckline", "stop_level", "target_level", "pattern_quality", "pattern_type",)
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
        ("atr", 6), ("entry_signal", 7), ("direction", 8), ("neckline", 9),
        ("stop_level", 10), ("target_level", 11), ("pattern_quality", 12), ("pattern_type", 13),
    )


class PatternDetectionStrategy(bt.Strategy):
    params = dict(
        position_size=0.90, max_holding_bars=20,
        smoothing=10, window_range=10,
        neckline_threshold=0.03, min_pattern_bars=20,
        min_quality=0.55, breakout_lookahead=20,
        atr_period=14, atr_multiplier=2.0,
        take_profit_ratio=1.5, commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.entry_bar = 0
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.trade_direction = 0

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, "mult", 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        direction = 1.0 if target_notional_pct >= 0 else -1.0
        size = broker_value * abs(float(target_notional_pct)) / (execution_price * multiplier)
        return direction * round(size, 2)

    def next(self):
        self.bar_num += 1
        if self.pending_order is not None:
            return
        low = float(self.data.low[0])
        high = float(self.data.high[0])
        close = float(self.data.close[0])
        if self.position:
            if self.trade_direction > 0:
                if self.stop_price is not None and low <= self.stop_price:
                    self.sell_count += 1
                    self.pending_order = self.close()
                    return
                if self.take_profit_price is not None and high >= self.take_profit_price:
                    self.sell_count += 1
                    self.pending_order = self.close()
                    return
            elif self.trade_direction < 0:
                if self.stop_price is not None and high >= self.stop_price:
                    self.buy_count += 1
                    self.pending_order = self.close()
                    return
                if self.take_profit_price is not None and low <= self.take_profit_price:
                    self.buy_count += 1
                    self.pending_order = self.close()
                    return
            if self.bar_num - self.entry_bar >= int(self.p.max_holding_bars):
                if self.trade_direction > 0:
                    self.sell_count += 1
                else:
                    self.buy_count += 1
                self.pending_order = self.close()
                return
            return
        if float(self.data.entry_signal[0]) > 0.5:
            direction = int(float(self.data.direction[0]))
            self.entry_bar = self.bar_num
            self.entry_price = close
            self.stop_price = float(self.data.stop_level[0])
            self.take_profit_price = float(self.data.target_level[0])
            self.trade_direction = direction
            target_size = self._get_position_size(target_notional_pct=float(self.p.position_size) * direction)
            if target_size > 0:
                self.buy_count += 1
            else:
                self.sell_count += 1
            self.pending_order = self.order_target_size(target=target_size)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.stop_price = None
            self.take_profit_price = None
            self.trade_direction = 0

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_018_0019_pattern_detection() -> None:
    """Migrated regression test for others/0019_pattern_detection."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    params = dict(
        smoothing=10, window_range=10, neckline_threshold=0.03,
        min_pattern_bars=20, min_quality=0.55, breakout_lookahead=20,
        atr_period=14,
    )
    frame = prepare_pattern_features(raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.adddata(PatternDetectionFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.addstrategy(PatternDetectionStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4625
    assert strat.buy_count == 3
    assert strat.sell_count == 3
    assert strat.win_count == 1
    assert strat.loss_count == 2
    assert strat.trade_count == 3
    assert total_trades == 3
    assert abs(final_value - 983823.97) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
