"""Regression test for geopolitical-defense signal strategy on commodities.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Target: XAUUSD. Defense proxy: ITA. Gold proxy: GLD.

Data Used:
    Daily OHLCV inputs are loaded from MT5 exports for XAUUSD (target),
    ITA (defense proxy), and GLD (safe-haven proxy) in
    ``tests/datas/mt5_1d_data``, covering 2008-01-01 to 2025-12-31.

Strategy Principle:
    The strategy combines defense momentum, gold momentum, and safe-haven breakout
    signals into a geopolitical factor. Positive factor values raise long exposure,
    negative values raise short exposure, and zero values flatten exposure.

Strategy Logic:
    ``prepare_military_proxy_features`` builds derived features and a bounded
    target weight signal. On periodic rebalance intervals, the strategy scales
    position exposure to that target via ``order_target_percent``. Order and trade
    notifications maintain a pending-order lock and update trading outcome counters.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
DATA_DIR = _REPO / "tests" / "datas" / "mt5_1d_data"
TARGET_FILE = DATA_DIR / "XAUUSD_1d.csv"
DEFENSE_FILE = DATA_DIR / "ITA_1d.csv"
GOLD_PROXY_FILE = DATA_DIR / "GLD_1d.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None):
    """Load an MT5 CSV/TSV export and return a backtrader-ready DataFrame.

    Args:
        filepath: Path to MT5 data file.
        fromdate: Optional inclusive start datetime.
        todate: Optional inclusive end datetime.

    Returns:
        Datetime-indexed OHLCV DataFrame.
    """
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


def prepare_military_proxy_features(target_df, defense_df, gold_proxy_df, params):
    """Construct geopolitical signal features used for trading decisions.

    Args:
        target_df: Target asset OHLCV frame.
        defense_df: Defense proxy asset OHLCV frame.
        gold_proxy_df: Gold proxy OHLCV frame.
        params: Strategy parameters controlling rolling windows and scaling.

    Returns:
        A feature-augmented DataFrame containing composite signal and target
        allocation columns.
    """
    common_index = target_df.index.intersection(defense_df.index).intersection(gold_proxy_df.index).sort_values()
    target = target_df.loc[common_index].copy()
    defense = defense_df.loc[common_index].copy()
    gold_proxy = gold_proxy_df.loc[common_index].copy()

    annual_lookback = int(params.get("annual_lookback_days", 252))
    defense_weight = float(params.get("defense_weight", 0.4))
    gold_proxy_weight = float(params.get("gold_proxy_weight", 0.3))
    safe_haven_weight = float(params.get("safe_haven_weight", 0.3))
    signal_threshold = float(params.get("signal_threshold", 0.25))
    max_target_percent = float(params.get("max_target_percent", 1.0))

    out = target[["open", "high", "low", "close", "volume", "openinterest"]].copy()
    out["defense_momentum"] = defense["close"].pct_change(annual_lookback)
    out["gold_proxy_momentum"] = gold_proxy["close"].pct_change(126)
    out["safe_haven_breakout"] = target["close"] / target["close"].rolling(63).max().shift(1) - 1.0
    out["realized_vol"] = target["close"].pct_change().rolling(21).std()
    out["geopolitical_signal_raw"] = (
        defense_weight * out["defense_momentum"]
        + gold_proxy_weight * out["gold_proxy_momentum"]
        + safe_haven_weight * out["safe_haven_breakout"]
    )
    rolling_mean = out["geopolitical_signal_raw"].rolling(annual_lookback).mean()
    rolling_std = out["geopolitical_signal_raw"].rolling(annual_lookback).std()
    out["geopolitical_signal"] = (out["geopolitical_signal_raw"] - rolling_mean) / rolling_std.replace(0, pd.NA)
    out["geopolitical_signal"] = out["geopolitical_signal"].clip(lower=-3.0, upper=3.0)
    out["signal"] = 0.0
    out.loc[out["geopolitical_signal"] > signal_threshold, "signal"] = 1.0
    out.loc[out["geopolitical_signal"] < -signal_threshold, "signal"] = -1.0
    signal_strength = (out["geopolitical_signal"].abs() / max(signal_threshold, 1e-6)).clip(upper=2.0) / 2.0
    out["target_percent"] = signal_strength * max_target_percent * out["signal"]
    return out[[
        "open", "high", "low", "close", "volume", "openinterest",
        "defense_momentum", "gold_proxy_momentum", "safe_haven_breakout", "realized_vol",
        "geopolitical_signal_raw", "geopolitical_signal", "signal", "target_percent",
    ]].dropna().copy()


class MilitaryProxyFeed(bt.feeds.PandasData):
    """Feed exposing military proxy signal components and target exposure."""
    lines = ("defense_momentum", "gold_proxy_momentum", "safe_haven_breakout", "realized_vol",
             "geopolitical_signal_raw", "geopolitical_signal", "signal", "target_percent")
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("defense_momentum", 6), ("gold_proxy_momentum", 7), ("safe_haven_breakout", 8), ("realized_vol", 9),
        ("geopolitical_signal_raw", 10), ("geopolitical_signal", 11), ("signal", 12), ("target_percent", 13),
    )


class MilitaryExpenditureStrategy(bt.Strategy):
    """Factor-based directional strategy reacting to geopolitical proxy signal.

    It rebalances exposure at fixed intervals based on the sign and strength of the
    composite target signal.
    """
    params = dict(
        rebalance_interval_days=21,
    )

    def __init__(self):
        """Initialize state counters and pending-order lock."""
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.long_signal_days = 0
        self.short_signal_days = 0
        self.neutral_signal_days = 0

    def _current_exposure(self):
        broker_value = float(self.broker.getvalue())
        price = float(self.data.close[0])
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, "mult", 1.0) or 1.0)
        if broker_value <= 0 or price <= 0 or multiplier <= 0:
            return 0.0
        return float(self.position.size) * price * multiplier / broker_value

    def next(self):
        """Track signal regime and rebalance exposure on schedule."""
        self.bar_num += 1
        signal_value = float(self.data.signal[0])
        if signal_value > 0.5:
            self.long_signal_days += 1
        elif signal_value < -0.5:
            self.short_signal_days += 1
        else:
            self.neutral_signal_days += 1
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
        """Clear the pending-order lock when a non-active status is received."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        """Count completed trades and classify outcomes."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_065_military_expenditure_strategy() -> None:
    """Migrated regression test for others/0065_military_expenditure_strategy."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    target = load_mt5_csv(TARGET_FILE, fromdate=fromdate, todate=todate)
    defense = load_mt5_csv(DEFENSE_FILE, fromdate=fromdate, todate=todate)
    gold_proxy = load_mt5_csv(GOLD_PROXY_FILE, fromdate=fromdate, todate=todate)
    frame = prepare_military_proxy_features(target, defense, gold_proxy, params=dict(
        annual_lookback_days=252, defense_weight=0.4, gold_proxy_weight=0.3,
        safe_haven_weight=0.3, signal_threshold=0.25, max_target_percent=1.0,
    ))

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.adddata(MilitaryProxyFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.addstrategy(MilitaryExpenditureStrategy, rebalance_interval_days=21)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"long={strat.long_signal_days} short={strat.short_signal_days} "
          f"neutral={strat.neutral_signal_days} win={strat.win_count} loss={strat.loss_count} "
          f"trade={strat.trade_count} total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4002
    assert strat.buy_count == 68
    assert strat.sell_count == 50
    assert strat.long_signal_days == 1843
    assert strat.short_signal_days == 1630
    assert strat.neutral_signal_days == 529
    assert strat.win_count == 11
    assert strat.loss_count == 18
    assert strat.trade_count == 29
    assert total_trades == 29
    assert abs(final_value - 686832.1947) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
