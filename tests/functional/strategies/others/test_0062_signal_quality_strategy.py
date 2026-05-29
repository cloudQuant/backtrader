"""Inlined regression test for others/0062_signal_quality_strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Uses XAUUSD as the trade asset, with GLD and IVV as auxiliary proxies for the
relative-value signal.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
PRICE_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "XAUUSD_1d.csv"
GOLD_PROXY_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "GLD_1d.csv"
EQUITY_PROXY_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "IVV_1d.csv"


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


def prepare_signal_quality_features(price_df, gold_proxy_df, equity_proxy_df, params):
    common_index = price_df.index.intersection(gold_proxy_df.index).intersection(equity_proxy_df.index).sort_values()
    price = price_df.loc[common_index].copy()
    gold_proxy = gold_proxy_df.loc[common_index].copy()
    equity_proxy = equity_proxy_df.loc[common_index].copy()

    quality_lookback = int(params.get("quality_lookback", 252))
    holding_period = int(params.get("holding_period", 21))
    momentum_lookback = int(params.get("momentum_lookback", 63))
    mean_reversion_lookback = int(params.get("mean_reversion_lookback", 20))
    ratio_lookback = int(params.get("ratio_lookback", 63))
    min_quality_score = float(params.get("min_quality_score", 0.6))
    max_target_percent = float(params.get("max_target_percent", 1.0))

    out = price[["open", "high", "low", "close", "volume", "openinterest"]].copy()
    out["future_return"] = out["close"].pct_change(holding_period).shift(-holding_period)
    out["signal_momentum"] = out["close"].pct_change(momentum_lookback)
    rolling_mean = out["close"].rolling(mean_reversion_lookback).mean()
    rolling_std = out["close"].rolling(mean_reversion_lookback).std().replace(0, np.nan)
    out["signal_mean_reversion"] = -((out["close"] - rolling_mean) / rolling_std)
    gold_equity_ratio = gold_proxy["close"] / equity_proxy["close"]
    out["signal_ratio"] = -(gold_equity_ratio / gold_equity_ratio.rolling(ratio_lookback).mean() - 1.0)

    for name in ["momentum", "mean_reversion", "ratio"]:
        signal_col = f"signal_{name}"
        rolling_ic = out[signal_col].rolling(quality_lookback).corr(out["future_return"])
        mean_ic = rolling_ic.rolling(holding_period).mean()
        ic_std = rolling_ic.rolling(holding_period).std()
        icir = mean_ic / ic_std.replace(0, np.nan) * np.sqrt(12)
        ic_stability = rolling_ic.rolling(holding_period).corr(rolling_ic.shift(1))
        quality_score = (
            0.4 * (mean_ic.fillna(0.0) / max(float(params.get("ic_threshold", 0.02)), 1e-6)).clip(lower=0.0)
            + 0.3 * (icir.fillna(0.0) / max(float(params.get("icir_threshold", 0.5)), 1e-6)).clip(lower=0.0)
            + 0.3 * (ic_stability.fillna(0.0) / max(float(params.get("ic_stability_threshold", 0.05)), 1e-6)).clip(lower=0.0)
        ).clip(upper=1.0)
        out[f"{signal_col}_ic"] = rolling_ic
        out[f"{signal_col}_mean_ic"] = mean_ic
        out[f"{signal_col}_icir"] = icir
        out[f"{signal_col}_stability"] = ic_stability
        out[f"{signal_col}_quality"] = quality_score

    quality_cols = [
        "signal_momentum_quality", "signal_mean_reversion_quality", "signal_ratio_quality",
    ]
    out["best_quality"] = out[quality_cols].max(axis=1)
    best_index = out[quality_cols].idxmax(axis=1)
    out["selected_signal"] = 0.0
    out.loc[best_index == "signal_momentum_quality", "selected_signal"] = out["signal_momentum"]
    out.loc[best_index == "signal_mean_reversion_quality", "selected_signal"] = out["signal_mean_reversion"]
    out.loc[best_index == "signal_ratio_quality", "selected_signal"] = out["signal_ratio"]
    out["target_percent"] = 0.0
    active_mask = out["best_quality"] >= min_quality_score
    scaled_signal = out["selected_signal"].clip(lower=-1.0, upper=1.0)
    out.loc[active_mask, "target_percent"] = scaled_signal.loc[active_mask] * max_target_percent
    return out[[
        "open", "high", "low", "close", "volume", "openinterest",
        "signal_momentum", "signal_mean_reversion", "signal_ratio",
        "signal_momentum_quality", "signal_mean_reversion_quality", "signal_ratio_quality",
        "best_quality", "selected_signal", "target_percent",
    ]].dropna().copy()


class SignalQualityFeed(bt.feeds.PandasData):
    lines = (
        "signal_momentum", "signal_mean_reversion", "signal_ratio",
        "signal_momentum_quality", "signal_mean_reversion_quality", "signal_ratio_quality",
        "best_quality", "selected_signal", "target_percent",
    )
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("signal_momentum", 6), ("signal_mean_reversion", 7), ("signal_ratio", 8),
        ("signal_momentum_quality", 9), ("signal_mean_reversion_quality", 10), ("signal_ratio_quality", 11),
        ("best_quality", 12), ("selected_signal", 13), ("target_percent", 14),
    )


class SignalQualityStrategy(bt.Strategy):
    params = dict(
        rebalance_interval_days=21,
        quality_lookback=252,
        holding_period=21,
        momentum_lookback=63,
        mean_reversion_lookback=20,
        ratio_lookback=63,
        ic_threshold=0.02,
        icir_threshold=0.5,
        ic_stability_threshold=0.05,
        min_quality_score=0.6,
        max_target_percent=1.0,
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

    def _current_exposure(self):
        broker_value = float(self.broker.getvalue())
        price = float(self.data.close[0])
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, "mult", 1.0) or 1.0)
        if broker_value <= 0 or price <= 0 or multiplier <= 0:
            return 0.0
        return float(self.position.size) * price * multiplier / broker_value

    def next(self):
        self.bar_num += 1
        if self.pending_order is not None:
            return
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        target_percent = float(self.data.target_percent[0])
        current_exposure = self._current_exposure()
        if abs(target_percent - current_exposure) < 0.03:
            return
        if target_percent > current_exposure:
            self.buy_count += 1
        elif target_percent < current_exposure:
            self.sell_count += 1
        self.pending_order = self.order_target_percent(target=target_percent)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_062_signal_quality_strategy() -> None:
    """Migrated regression test for others/0062_signal_quality_strategy."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(PRICE_FILE, fromdate=fromdate, todate=todate)
    gold_proxy = load_mt5_csv(GOLD_PROXY_FILE, fromdate=fromdate, todate=todate)
    equity_proxy = load_mt5_csv(EQUITY_PROXY_FILE, fromdate=fromdate, todate=todate)
    params = dict(
        quality_lookback=252, holding_period=21,
        momentum_lookback=63, mean_reversion_lookback=20, ratio_lookback=63,
        ic_threshold=0.02, icir_threshold=0.5, ic_stability_threshold=0.05,
        min_quality_score=0.6, max_target_percent=1.0,
    )
    frame = prepare_signal_quality_features(raw, gold_proxy, equity_proxy, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.adddata(SignalQualityFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.addstrategy(SignalQualityStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4445
    assert strat.buy_count == 68
    assert strat.sell_count == 61
    assert strat.win_count == 15
    assert strat.loss_count == 30
    assert strat.trade_count == 45
    assert total_trades == 45
    assert abs(final_value - 1054494.2371) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
