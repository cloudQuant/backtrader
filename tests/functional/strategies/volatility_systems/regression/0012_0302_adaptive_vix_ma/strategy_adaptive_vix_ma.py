from __future__ import absolute_import, division, print_function, unicode_literals

import io
import backtrader as bt
import pandas as pd
import numpy as np


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
    df = df.rename(
        columns={
            "<OPEN>": "open",
            "<HIGH>": "high",
            "<LOW>": "low",
            "<CLOSE>": "close",
            "<TICKVOL>": "tick_volume",
            "<VOL>": "real_volume",
        }
    )
    df["openinterest"] = 0
    df["volume"] = df["tick_volume"] if "tick_volume" in df.columns else 0
    df = df[["datetime", "open", "high", "low", "close", "volume", "openinterest"]]
    df = df.set_index("datetime").sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_adaptive_vix_ma_features(df, params):
    vol_lookback = int(params.get("vol_lookback", 20))
    vol_sma_period = int(params.get("vol_sma_period", 10))
    pr_lookback = int(params.get("percentrank_lookback", 500))
    alpha_constant = float(params.get("alpha_constant", 4.6))

    out = df.copy()
    returns = out["close"].pct_change()
    vol = returns.rolling(vol_lookback).std() * np.sqrt(252)
    sma_vol = vol.rolling(vol_sma_period).mean()
    inv_sma_vol = 1.0 / sma_vol.replace(0, np.inf)

    # PercentRank using rolling rank
    pr = inv_sma_vol.rolling(min(pr_lookback, len(inv_sma_vol)), min_periods=20).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
    )

    # Ehlers Alpha
    alpha = np.exp(-alpha_constant * (pr - 1))
    alpha = alpha.clip(0.01, 1.0)

    # Adaptive EMA
    adaptive_ema = pd.Series(index=out.index, dtype=float)
    adaptive_ema.iloc[0] = out["close"].iloc[0]
    for i in range(1, len(out)):
        a = alpha.iloc[i] if not np.isnan(alpha.iloc[i]) else 0.1
        adaptive_ema.iloc[i] = (
            a * out["close"].iloc[i] + (1 - a) * adaptive_ema.iloc[i - 1]
        )

    out["adaptive_ema"] = adaptive_ema
    out["signal"] = (out["close"] > out["adaptive_ema"]).astype(float)

    out = out[
        [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "openinterest",
            "adaptive_ema",
            "signal",
        ]
    ].copy()
    return out.dropna()


class Mt5AdaptiveVixMaFeed(bt.feeds.PandasData):
    lines = (
        "adaptive_ema",
        "signal",
    )
    params = (
        ("datetime", None),
        ("open", 0),
        ("high", 1),
        ("low", 2),
        ("close", 3),
        ("volume", 4),
        ("openinterest", 5),
        ("adaptive_ema", 6),
        ("signal", 7),
    )


class AdaptiveVixMaStrategy(bt.Strategy):
    params = dict(
        vol_sma_period=10,
        percentrank_lookback=500,
        alpha_constant=4.6,
        vol_lookback=20,
        lot_size=1.0,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.broker_value_series = []

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        if target_notional_pct <= 0:
            return 0.0
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = (
            broker_value * float(target_notional_pct) / (execution_price * multiplier)
        )
        return max(0.01, round(size, 2))

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append(
            (bt.num2date(self.data.datetime[0]), float(self.broker.getvalue()))
        )

        if self.pending_order is not None:
            return

        signal = float(self.data.signal[0])

        if not self.position:
            if signal > 0.5:
                self.buy_count += 1
                self.pending_order = self.buy(size=self._get_position_size())
        else:
            if signal < 0.5:
                self.sell_count += 1
                self.pending_order = self.close()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        pass
