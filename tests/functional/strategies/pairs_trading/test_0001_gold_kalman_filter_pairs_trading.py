"""Inlined regression test for pairs_trading/0001_gold_kalman_filter_pairs_trading.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Kalman filter dynamic hedge ratio on XAUUSD/XAGUSD H1 data.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
GOLD_FILE = _REPO / "tests" / "datas" / "XAUUSD_H1.csv"
SILVER_FILE = _REPO / "tests" / "datas" / "XAGUSD_H1.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    """Load MT5 gold/silver CSV data into OHLCV DataFrame.

    Args:
        filepath: Path to MT5 export file.
        fromdate: Optional inclusive start datetime.
        todate: Optional inclusive end datetime.
        bar_shift_minutes: Optional close-time shift applied to parsed timestamps.

    Returns:
        Datetime-indexed DataFrame with open/high/low/close/volume/openinterest.
    """
    with open(filepath, "r", encoding="utf-8", errors="ignore") as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = "\n".join(lines)
    sep = "\t" if "\t" in lines[0] else ","
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    if "time" in df.columns:
        parsed = pd.to_datetime(df["time"], errors="coerce", utc=True).dt.tz_convert(None)
        if bar_shift_minutes:
            parsed = parsed + pd.to_timedelta(int(bar_shift_minutes), unit="m")
        df["datetime"] = parsed
        if "volume" not in df.columns:
            df["volume"] = df["tick_volume"] if "tick_volume" in df.columns else 0
        df["openinterest"] = 0
        df = df[["datetime", "open", "high", "low", "close", "volume", "openinterest"]]
        df = df.dropna(subset=["datetime"]).set_index("datetime").sort_index()
        if fromdate is not None:
            df = df[df.index >= fromdate]
        if todate is not None:
            df = df[df.index <= todate]
        return df
    dt_text = df["<DATE>"].astype(str) + " " + df["<TIME>"].astype(str)
    parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M", errors="coerce")
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M:%S", errors="coerce")
    if bar_shift_minutes:
        parsed = parsed + pd.to_timedelta(int(bar_shift_minutes), unit="m")
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


def prepare_pairs_data(gold_df, silver_df):
    """Align gold and silver frames on a common trading index.

    Args:
        gold_df: Gold OHLCV DataFrame.
        silver_df: Silver OHLCV DataFrame.

    Returns:
        Tuple of aligned (gold, silver) DataFrames with same index.
    """
    common_index = gold_df.index.intersection(silver_df.index).sort_values()
    return gold_df.loc[common_index].copy(), silver_df.loc[common_index].copy()


class KalmanFilterHedgeRatio:
    """Adaptive Kalman filter for estimating dynamic hedge ratio beta."""
    def __init__(self, process_noise, observation_noise, initial_beta, initial_P):
        """Initialize filter noise covariance, state, and variance."""
        self.Q = float(process_noise)
        self.R = float(observation_noise)
        self.beta = float(initial_beta)
        self.P = float(initial_P)

    def update(self, price_a, price_b):
        """Update beta/spread estimate for a pair observation.

        Args:
            price_a: Price series for base leg.
            price_b: Price series for hedge leg.

        Returns:
            Tuple ``(beta, spread)`` after one Kalman update.
        """
        beta_pred = self.beta
        P_pred = self.P + self.Q
        denominator = P_pred * price_b * price_b + self.R
        K = 0.0 if denominator == 0 else (P_pred * price_b) / denominator
        innovation = price_a - beta_pred * price_b
        self.beta = beta_pred + K * innovation
        self.P = (1.0 - K * price_b) * P_pred
        spread = price_a - self.beta * price_b
        return self.beta, spread


class GoldKalmanFilterPairsStrategy(bt.Strategy):
    """Pairs strategy using a Kalman filter to dynamically estimate hedge ratio."""
    params = dict(
        process_noise=0.0005,
        observation_noise=1.0,
        initial_beta=78.0,
        initial_P=1.0,
        zscore_window=192,
        entry_threshold=2.0,
        exit_threshold=0.35,
        stop_loss_threshold=3.25,
        max_capital_pct=0.05,
        leverage=1.0,
        stability_window=96,
        beta_stability_threshold=0.03,
    )

    def __init__(self):
        """Initialize pair handles, filter state, counters, and trade trackers."""
        self.gold = self.getdatabyname("XAUUSD")
        self.silver = self.getdatabyname("XAGUSD")
        self.kf = KalmanFilterHedgeRatio(
            process_noise=self.p.process_noise,
            observation_noise=self.p.observation_noise,
            initial_beta=self.p.initial_beta,
            initial_P=self.p.initial_P,
        )
        self.beta_history = []
        self.spread_history = []
        self.zscore_history = []
        self.current_beta = self.p.initial_beta
        self.current_spread = 0.0
        self.current_zscore = 0.0
        self.position_state = 0
        self.pending_order_refs = set()
        self.entry_gold_price = None
        self.entry_silver_price = None
        self.entry_gold_size = 0
        self.entry_silver_size = 0
        self.bar_num = 0
        self.long_entries = 0
        self.short_entries = 0
        self.exit_count = 0
        self.stop_losses = 0
        self.total_trades = 0
        self.won_trades = 0
        self.lost_trades = 0
        self.spread_pnls = []

    def _beta_stability(self):
        if len(self.beta_history) < self.p.stability_window:
            return None
        recent = np.array(self.beta_history[-self.p.stability_window:])
        mean_abs = abs(recent.mean())
        if mean_abs == 0:
            return None
        return float(recent.std() / mean_abs)

    def _calc_sizes(self, price_a, price_b):
        beta_abs = max(abs(self.current_beta), 0.01)
        equity = float(self.broker.getvalue())
        gross_budget = equity * float(self.p.max_capital_pct) * float(self.p.leverage)
        gross_per_unit = price_a + beta_abs * price_b
        if gross_per_unit <= 0:
            return 0, 0
        size_a = int(gross_budget / gross_per_unit)
        size_b = int(round(size_a * beta_abs))
        return max(size_a, 0), max(size_b, 0)

    def _estimate_pair_pnl(self, price_a, price_b):
        if self.entry_gold_price is None or self.entry_silver_price is None:
            return 0.0
        if self.position_state > 0:
            gold_pnl = (price_a - self.entry_gold_price) * self.entry_gold_size
            silver_pnl = (self.entry_silver_price - price_b) * self.entry_silver_size
        elif self.position_state < 0:
            gold_pnl = (self.entry_gold_price - price_a) * self.entry_gold_size
            silver_pnl = (price_b - self.entry_silver_price) * self.entry_silver_size
        else:
            return 0.0
        return float(gold_pnl + silver_pnl)

    def _submit_pair_orders(self, direction, price_a, price_b):
        size_a, size_b = self._calc_sizes(price_a, price_b)
        if size_a <= 0 or size_b <= 0:
            return
        orders = []
        if direction > 0:
            orders.append(self.buy(data=self.gold, size=size_a))
            orders.append(self.sell(data=self.silver, size=size_b))
            self.long_entries += 1
        else:
            orders.append(self.sell(data=self.gold, size=size_a))
            orders.append(self.buy(data=self.silver, size=size_b))
            self.short_entries += 1
        for order in orders:
            if order is not None:
                self.pending_order_refs.add(order.ref)
        self.position_state = direction
        self.entry_gold_price = float(price_a)
        self.entry_silver_price = float(price_b)
        self.entry_gold_size = int(size_a)
        self.entry_silver_size = int(size_b)

    def _close_pair(self, price_a, price_b, is_stop=False):
        pnl = self._estimate_pair_pnl(price_a, price_b)
        self.spread_pnls.append(pnl)
        self.total_trades += 1
        if pnl >= 0:
            self.won_trades += 1
        else:
            self.lost_trades += 1
        if is_stop:
            self.stop_losses += 1
        self.exit_count += 1
        for order in (self.close(data=self.gold), self.close(data=self.silver)):
            if order is not None:
                self.pending_order_refs.add(order.ref)
        self.position_state = 0
        self.entry_gold_price = None
        self.entry_silver_price = None
        self.entry_gold_size = 0
        self.entry_silver_size = 0

    def next(self):
        """Update spread estimate, evaluate z-score conditions, and manage entries/exits."""
        self.bar_num += 1
        if self.pending_order_refs:
            return
        price_a = float(self.gold.close[0])
        price_b = float(self.silver.close[0])
        if price_a <= 0 or price_b <= 0:
            return
        self.current_beta, self.current_spread = self.kf.update(price_a, price_b)
        self.beta_history.append(self.current_beta)
        self.spread_history.append(self.current_spread)
        if len(self.spread_history) < self.p.zscore_window:
            self.current_zscore = 0.0
            self.zscore_history.append(self.current_zscore)
            return
        recent_spread = np.array(self.spread_history[-self.p.zscore_window:])
        spread_std = float(recent_spread.std())
        self.current_zscore = 0.0 if spread_std == 0 else float((self.current_spread - recent_spread.mean()) / spread_std)
        self.zscore_history.append(self.current_zscore)
        beta_stability = self._beta_stability()
        is_stable = beta_stability is not None and beta_stability <= float(self.p.beta_stability_threshold)
        if self.position_state == 0:
            if self.current_zscore <= -float(self.p.entry_threshold) and is_stable:
                self._submit_pair_orders(1, price_a, price_b)
            elif self.current_zscore >= float(self.p.entry_threshold) and is_stable:
                self._submit_pair_orders(-1, price_a, price_b)
            return
        if self.position_state > 0:
            if abs(self.current_zscore) <= float(self.p.exit_threshold):
                self._close_pair(price_a, price_b, is_stop=False)
            elif self.current_zscore <= -float(self.p.stop_loss_threshold):
                self._close_pair(price_a, price_b, is_stop=True)
            return
        if abs(self.current_zscore) <= float(self.p.exit_threshold):
            self._close_pair(price_a, price_b, is_stop=False)
        elif self.current_zscore >= float(self.p.stop_loss_threshold):
            self._close_pair(price_a, price_b, is_stop=True)

    def notify_order(self, order):
        """Drop order refs from the pending set after finalization."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order_refs.discard(order.ref)


class ComminfoFuturesPercent(bt.CommInfoBase):
    """Commission model with absolute percentage fee per turnover."""
    params = (
        ("commission", 0.0001),
        ("margin", 0.1),
        ("mult", 1.0),
        ("stocklike", False),
        ("percabs", True),
    )

    def _getcommission(self, size, price, pseudoexec):
        """Compute absolute percentage commission for the given notional size."""
        return abs(size) * price * self.p.commission


def test_001_gold_kalman_filter_pairs_trading() -> None:
    """Migrated regression test for pairs_trading/0001_gold_kalman_filter_pairs_trading."""
    fromdate = datetime.datetime(2025, 7, 1, 0, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 23, 59, 59)
    gold_raw = load_mt5_csv(GOLD_FILE, fromdate=fromdate, todate=todate)
    silver_raw = load_mt5_csv(SILVER_FILE, fromdate=fromdate, todate=todate)
    gold, silver = prepare_pairs_data(gold_raw, silver_raw)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.addcommissioninfo(ComminfoFuturesPercent())
    cerebro.adddata(bt.feeds.PandasData(dataname=gold[["open", "high", "low", "close", "volume", "openinterest"]],
                                          timeframe=bt.TimeFrame.Minutes, compression=60), name="XAUUSD")
    cerebro.adddata(bt.feeds.PandasData(dataname=silver[["open", "high", "low", "close", "volume", "openinterest"]],
                                          timeframe=bt.TimeFrame.Minutes, compression=60), name="XAGUSD")
    cerebro.addstrategy(GoldKalmanFilterPairsStrategy)

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())

    print(f"CAPTURED: bar={strat.bar_num} long_entries={strat.long_entries} short_entries={strat.short_entries} "
          f"exit={strat.exit_count} stop={strat.stop_losses} trades={strat.total_trades} "
          f"won={strat.won_trades} lost={strat.lost_trades} fv={final_value:.4f}")

    assert strat.bar_num == 2986
    assert strat.long_entries == 49
    assert strat.short_entries == 54
    assert strat.exit_count == 103
    assert strat.stop_losses == 9
    assert strat.total_trades == 103
    assert strat.won_trades == 61
    assert strat.lost_trades == 42
    assert abs(final_value - 997507.0220) < 1.0
