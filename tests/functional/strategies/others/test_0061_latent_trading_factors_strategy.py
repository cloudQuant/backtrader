"""Inlined regression test for others/0061_latent_trading_factors_strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Universe: IVV, IEF, GLD, DBC, EEM. SVD-based latent factor signals.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
DATA_DIR = _REPO / "tests" / "datas" / "mt5_1d_data"
ASSET_FILES = {
    "IVV": DATA_DIR / "IVV_1d.csv",
    "IEF": DATA_DIR / "IEF_1d.csv",
    "GLD": DATA_DIR / "GLD_1d.csv",
    "DBC": DATA_DIR / "DBC_1d.csv",
    "EEM": DATA_DIR / "EEM_1d.csv",
}


def load_mt5_csv(filepath, fromdate=None, todate=None):
    """Load MT5 CSV data and return a normalized daily OHLCV DataFrame."""
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


def _latent_scores(window_returns, n_factors):
    standardized = (window_returns - window_returns.mean()) / window_returns.std().replace(0, np.nan)
    standardized = standardized.dropna(axis=1, how="any").dropna(axis=0, how="any")
    if standardized.shape[0] < max(20, n_factors + 2) or standardized.shape[1] < n_factors:
        return {}
    matrix = standardized.to_numpy(dtype=float)
    _, _, vt = np.linalg.svd(matrix, full_matrices=False)
    loadings = vt[:n_factors]
    scores = loadings.sum(axis=0)
    return dict(zip(standardized.columns, scores))


def prepare_latent_factor_data(asset_map, params):
    """Build SVD-based latent-factor targets and per-asset signal frames."""
    aligned_index = None
    prepared = {}
    lookback = int(params.get("lookback", 252))
    n_factors = int(params.get("n_factors", 3))
    signal_threshold = float(params.get("signal_threshold", 0.5))
    max_asset_weight = float(params.get("max_asset_weight", 0.25))
    for _, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    close_df = pd.DataFrame({symbol: frame.loc[aligned_index, "close"] for symbol, frame in asset_map.items()},
                             index=aligned_index)
    returns_df = close_df.pct_change()
    signal_df = pd.DataFrame(index=aligned_index, columns=close_df.columns, dtype=float)
    for idx in range(lookback, len(returns_df)):
        window = returns_df.iloc[idx - lookback:idx]
        score_map = _latent_scores(window, n_factors)
        for symbol in close_df.columns:
            signal_df.at[aligned_index[idx], symbol] = score_map.get(symbol, np.nan)
    standardized_signal = (signal_df.sub(signal_df.mean(axis=1), axis=0)).div(signal_df.std(axis=1).replace(0, np.nan), axis=0)
    target_df = standardized_signal.clip(lower=-signal_threshold, upper=signal_threshold) / max(signal_threshold, 1e-6) * max_asset_weight
    for symbol, frame in asset_map.items():
        px = frame.loc[aligned_index].copy()
        prepared[symbol] = px[["open", "high", "low", "close", "volume", "openinterest"]].copy()
        prepared[symbol]["latent_signal"] = standardized_signal[symbol].astype(float)
        prepared[symbol]["target_percent"] = target_df[symbol].astype(float)
    score_df = pd.DataFrame({symbol: frame["latent_signal"] for symbol, frame in prepared.items()}, index=aligned_index)
    return prepared, score_df.dropna(how="all")


class LatentFactorFeed(bt.feeds.PandasData):
    """Pandas feed including latent factor scores and target percent allocation."""
    lines = ("latent_signal", "target_percent")
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("latent_signal", 6), ("target_percent", 7),
    )


class LatentTradingFactorsStrategy(bt.Strategy):
    """Multi-asset latent-factor allocator rebalancing on a fixed interval."""
    params = dict(
        rebalance_interval_days=21,
        lookback=252,
        n_factors=3,
        signal_threshold=0.5,
        max_asset_weight=0.25,
        commission_pct=0.0005,
    )

    def __init__(self):
        """Initialize order tracking and signal counters."""
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.long_signal_days = 0
        self.short_signal_days = 0
        self.neutral_signal_days = 0

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _target_size(self, data, target_pct):
        broker_value = float(self.broker.getvalue())
        price = float(data.close[0])
        if broker_value <= 0 or price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(data)
        multiplier = float(getattr(comminfo.p, "mult", 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * abs(float(target_pct)) / (price * multiplier)
        size = max(0.01, round(size, 2))
        return size if target_pct >= 0 else -size

    def next(self):
        """Rebalance each asset toward its target weight on rebalance dates."""
        self.bar_num += 1
        if self.order_refs:
            return
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        for data in self.datas:
            target_pct = float(data.target_percent[0]) if data.target_percent[0] == data.target_percent[0] else 0.0
            if target_pct > 0:
                self.long_signal_days += 1
            elif target_pct < 0:
                self.short_signal_days += 1
            else:
                self.neutral_signal_days += 1
            current_pos = float(self.getposition(data).size)
            target_size = self._target_size(data, target_pct)
            if abs(target_size - current_pos) < 0.01:
                continue
            if target_size > current_pos:
                self.buy_count += 1
            elif target_size < current_pos:
                self.sell_count += 1
            self._submit(self.order_target_size(data=data, target=target_size))

    def notify_order(self, order):
        """Clear tracked order refs when an order completes or fails."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        """Update trade counters and PnL outcome on closed trades."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_061_latent_trading_factors_strategy() -> None:
    """Migrated regression test for others/0061_latent_trading_factors_strategy."""
    fromdate = datetime.datetime(2018, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    asset_map = {sym: load_mt5_csv(p, fromdate=fromdate, todate=todate) for sym, p in ASSET_FILES.items()}
    prepared_map, score_df = prepare_latent_factor_data(asset_map, params=dict(
        lookback=252, n_factors=3, signal_threshold=0.5, max_asset_weight=0.25,
    ))
    valid_index = score_df.index
    prepared_map = {symbol: frame.loc[valid_index].copy() for symbol, frame in prepared_map.items()}

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    for sym in ASSET_FILES.keys():
        feed = LatentFactorFeed(
            dataname=prepared_map[sym][[
                "open", "high", "low", "close", "volume", "openinterest", "latent_signal", "target_percent",
            ]].copy(),
            timeframe=bt.TimeFrame.Days,
        )
        cerebro.adddata(feed, name=sym)
    cerebro.addstrategy(LatentTradingFactorsStrategy)
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

    assert strat.bar_num == 1749
    assert strat.buy_count == 209
    assert strat.sell_count == 211
    assert strat.long_signal_days == 213
    assert strat.short_signal_days == 207
    assert strat.neutral_signal_days == 0
    assert strat.win_count == 94
    assert strat.loss_count == 89
    assert strat.trade_count == 183
    assert total_trades == 183
    assert abs(final_value - 983047.9664) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
