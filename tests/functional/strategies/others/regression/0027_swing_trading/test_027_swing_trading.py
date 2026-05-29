"""Inlined regression test for others/0027_swing_trading.

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


def prepare_swing_trading_features(df, params):
    swing_n = int(params.get("swing_n", 4))
    trend_ma_period = int(params.get("trend_ma_period", 50))
    atr_period = int(params.get("atr_period", 14))
    max_atr_multiple = float(params.get("max_atr_multiple", 3.0))
    min_breakout_pct = float(params.get("min_breakout_pct", 0.005))

    out = df.copy()
    out["ma_trend"] = out["close"].rolling(trend_ma_period).mean()
    tr = pd.concat([
        out["high"] - out["low"],
        (out["high"] - out["close"].shift(1)).abs(),
        (out["low"] - out["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    out["atr"] = tr.rolling(atr_period).mean()
    out["atr_long_mean"] = out["atr"].rolling(atr_period * 5).mean()

    swing_high = [float("nan")] * len(out)
    swing_low = [float("nan")] * len(out)
    latest_swing_high = [float("nan")] * len(out)
    latest_swing_low = [float("nan")] * len(out)
    breakout_signal = [0.0] * len(out)
    breakout_direction = [0.0] * len(out)

    recent_high = None
    recent_low = None
    highs = out["high"].tolist()
    lows = out["low"].tolist()
    closes = out["close"].tolist()

    for i in range(len(out)):
        if i >= swing_n and i < len(out) - swing_n:
            center_high = highs[i]
            center_low = lows[i]
            is_swing_high = all(center_high > highs[i - j] and center_high > highs[i + j] for j in range(1, swing_n + 1))
            is_swing_low = all(center_low < lows[i - j] and center_low < lows[i + j] for j in range(1, swing_n + 1))
            if is_swing_high:
                swing_high[i] = center_high
                recent_high = center_high
            if is_swing_low:
                swing_low[i] = center_low
                recent_low = center_low

        latest_swing_high[i] = recent_high if recent_high is not None else float("nan")
        latest_swing_low[i] = recent_low if recent_low is not None else float("nan")

        if recent_high is None or recent_low is None:
            continue
        trend_up = closes[i] > (out["ma_trend"].iloc[i] if pd.notna(out["ma_trend"].iloc[i]) else float("inf"))
        trend_down = closes[i] < (out["ma_trend"].iloc[i] if pd.notna(out["ma_trend"].iloc[i]) else float("-inf"))
        vol_ok = pd.notna(out["atr"].iloc[i]) and pd.notna(out["atr_long_mean"].iloc[i]) and out["atr"].iloc[i] <= out["atr_long_mean"].iloc[i] * max_atr_multiple
        if vol_ok and trend_up and closes[i] > recent_high * (1.0 + min_breakout_pct):
            breakout_signal[i] = 1.0
            breakout_direction[i] = 1.0
        elif vol_ok and trend_down and closes[i] < recent_low * (1.0 - min_breakout_pct):
            breakout_signal[i] = 1.0
            breakout_direction[i] = -1.0

    out["swing_high"] = swing_high
    out["swing_low"] = swing_low
    out["latest_swing_high"] = latest_swing_high
    out["latest_swing_low"] = latest_swing_low
    out["breakout_signal"] = breakout_signal
    out["breakout_direction"] = breakout_direction
    out = out[[
        "open", "high", "low", "close", "volume", "openinterest",
        "ma_trend", "atr", "atr_long_mean",
        "swing_high", "swing_low", "latest_swing_high", "latest_swing_low",
        "breakout_signal", "breakout_direction",
    ]].copy()
    required_cols = ["ma_trend", "atr", "atr_long_mean", "latest_swing_high", "latest_swing_low"]
    return out.dropna(subset=required_cols)


class Mt5SwingTradingFeed(bt.feeds.PandasData):
    lines = (
        "ma_trend", "atr", "atr_long_mean",
        "swing_high", "swing_low", "latest_swing_high", "latest_swing_low",
        "breakout_signal", "breakout_direction",
    )
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("ma_trend", 6), ("atr", 7), ("atr_long_mean", 8),
        ("swing_high", 9), ("swing_low", 10), ("latest_swing_high", 11), ("latest_swing_low", 12),
        ("breakout_signal", 13), ("breakout_direction", 14),
    )


class SwingTradingStrategy(bt.Strategy):
    params = dict(
        take_profit_ratio=2.5,
        max_holding_days=12,
        position_size=0.95,
        swing_n=4,
        min_breakout_pct=0.005,
        trend_ma_period=50,
        atr_period=14,
        max_atr_multiple=3.0,
        commission_pct=0.0005,
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
            if self.bar_num - self.entry_bar >= int(self.p.max_holding_days):
                if self.trade_direction > 0:
                    self.sell_count += 1
                else:
                    self.buy_count += 1
                self.pending_order = self.close()
                return
            return

        if float(self.data.breakout_signal[0]) > 0.5:
            direction = int(float(self.data.breakout_direction[0]))
            swing_high = float(self.data.latest_swing_high[0])
            swing_low = float(self.data.latest_swing_low[0])
            self.entry_bar = self.bar_num
            self.trade_direction = direction
            if direction > 0:
                risk = max(close - swing_low, close * 0.005)
                self.stop_price = swing_low
                self.take_profit_price = close + risk * float(self.p.take_profit_ratio)
                self.buy_count += 1
            else:
                risk = max(swing_high - close, close * 0.005)
                self.stop_price = swing_high
                self.take_profit_price = close - risk * float(self.p.take_profit_ratio)
                self.sell_count += 1
            target_size = self._get_position_size(target_notional_pct=float(self.p.position_size) * direction)
            self.pending_order = self.order_target_size(target=target_size)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
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


def test_027_swing_trading() -> None:
    """Migrated regression test for others/0027_swing_trading."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    params = dict(
        swing_n=4,
        min_breakout_pct=0.005,
        trend_ma_period=50,
        atr_period=14,
        max_atr_multiple=3.0,
    )
    frame = prepare_swing_trading_features(raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.adddata(Mt5SwingTradingFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.addstrategy(SwingTradingStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4556
    assert strat.buy_count == 174
    assert strat.sell_count == 174
    assert strat.win_count == 94
    assert strat.loss_count == 79
    assert strat.trade_count == 173
    assert total_trades == 173
    assert abs(final_value - 2897469.4145) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
