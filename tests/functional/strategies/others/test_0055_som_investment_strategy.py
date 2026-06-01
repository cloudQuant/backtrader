"""Inlined regression test for others/0055_som_investment_strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Universe: IVV, IWM, IWD, PDP, GLD, EEM, DBMF.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd
from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_DIR = _REPO / "tests" / "datas" / "mt5_1d_data"
ASSET_FILES = {
    "ivv": DATA_DIR / "IVV_1d.csv",
    "iwm": DATA_DIR / "IWM_1d.csv",
    "iwd": DATA_DIR / "IWD_1d.csv",
    "pdp": DATA_DIR / "PDP_1d.csv",
    "gld": DATA_DIR / "GLD_1d.csv",
    "eem": DATA_DIR / "EEM_1d.csv",
    "dbmf": DATA_DIR / "DBMF_1d.csv",
}


def _train_som(features, rows, cols, iterations, learning_rate):
    x = np.asarray(features, dtype=float)
    if x.ndim != 2 or len(x) == 0:
        return np.zeros((rows, cols, 1))
    rng = np.random.default_rng(42)
    n_features = x.shape[1]
    weights = rng.normal(0, 1, size=(rows, cols, n_features))
    radius0 = max(rows, cols) / 2.0
    for t in range(max(1, int(iterations))):
        sample = x[t % len(x)]
        dists = np.sum((weights - sample) ** 2, axis=2)
        bmu = np.unravel_index(np.argmin(dists), dists.shape)
        lr = learning_rate * (1 - t / max(1, iterations))
        radius = max(0.5, radius0 * (1 - t / max(1, iterations)))
        for i in range(rows):
            for j in range(cols):
                dist = np.sqrt((i - bmu[0]) ** 2 + (j - bmu[1]) ** 2)
                if dist <= radius:
                    influence = np.exp(-(dist ** 2) / (2 * radius ** 2))
                    weights[i, j] += lr * influence * (sample - weights[i, j])
    return weights


def _map_to_cluster(weights, sample):
    dists = np.sum((weights - sample) ** 2, axis=2)
    return tuple(np.unravel_index(np.argmin(dists), dists.shape))


def prepare_som_inputs(asset_map, params):
    """Build aligned asset data and rolling feature snapshots for SOM selection.

    Args:
        asset_map: Mapping from symbol to market dataframes.
        params: Strategy parameters controlling momentum/volatility/drawdown windows.

    Returns:
        Tuple of ``(prepared_data, feature_lookup)`` where the first entry is
        aligned OHLCV data and the second maps timestamps to feature rows.
    """
    aligned_index = None
    prepared = {}
    for _, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in asset_map.items():
        prepared[symbol] = frame.loc[aligned_index][["open", "high", "low", "close", "volume", "openinterest"]].copy()
    close_df = pd.DataFrame({symbol: frame.loc[aligned_index, "close"] for symbol, frame in asset_map.items()},
                             index=aligned_index)
    momentum_period = int(params.get("momentum_period", 126))
    vol_period = int(params.get("vol_period", 20))
    drawdown_period = int(params.get("drawdown_period", 63))
    feature_snapshots = {}
    start = max(momentum_period, vol_period, drawdown_period) + 1
    for idx in range(start, len(close_df)):
        date = close_df.index[idx]
        history = close_df.iloc[: idx + 1]
        rows = []
        for symbol in close_df.columns:
            series = history[symbol].dropna()
            if len(series) <= momentum_period:
                continue
            momentum_1m = float(series.iloc[-1] / series.iloc[-21] - 1.0) if len(series) > 21 else 0.0
            momentum_3m = float(series.iloc[-1] / series.iloc[-63] - 1.0) if len(series) > 63 else momentum_1m
            momentum_6m = float(series.iloc[-1] / series.iloc[-momentum_period] - 1.0)
            returns = np.log(series / series.shift(1)).dropna()
            vol_20d = float(returns.iloc[-vol_period:].std() * np.sqrt(252)) if len(returns) >= vol_period else 0.0
            rolling_peak = series.iloc[-drawdown_period:].cummax() if len(series) >= drawdown_period else series.cummax()
            drawdown = float((series.iloc[-1] / rolling_peak.max()) - 1.0)
            rows.append({
                "symbol": symbol,
                "momentum_1m": momentum_1m,
                "momentum_3m": momentum_3m,
                "momentum_6m": momentum_6m,
                "vol_20d": vol_20d,
                "drawdown_63d": drawdown,
            })
        feature_snapshots[pd.Timestamp(date).tz_localize(None)] = pd.DataFrame(rows)
    return prepared, feature_snapshots


class SOMInvestmentStrategy(bt.Strategy):
    """Self-balancing strategy selecting top SOM clusters by momentum.

    The strategy rebuilds feature clusters periodically and holds the top-ranked
    assets from each cluster at fixed position weights.
    """
    params = dict(
        som_rows=3, som_cols=3, som_iterations=250, learning_rate=0.15,
        top_n_holdings=3, rebalance_interval_days=21,
        feature_lookup=None,
    )

    def __init__(self):
        """Initialize trade counters and order tracking state."""
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.cluster_count_total = 0
        self.rebalance_count = 0

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

    def _select_assets(self, features_df):
        feature_cols = ["momentum_1m", "momentum_3m", "momentum_6m", "vol_20d", "drawdown_63d"]
        x = features_df[feature_cols].to_numpy(dtype=float)
        means = x.mean(axis=0)
        stds = x.std(axis=0)
        stds[stds == 0] = 1.0
        x_scaled = (x - means) / stds
        weights = _train_som(x_scaled, int(self.p.som_rows), int(self.p.som_cols),
                              int(self.p.som_iterations), float(self.p.learning_rate))
        clusters = {}
        for idx, row in enumerate(features_df.itertuples(index=False)):
            cluster = _map_to_cluster(weights, x_scaled[idx])
            clusters.setdefault(cluster, []).append({"symbol": row.symbol, "momentum_6m": row.momentum_6m})
        self.cluster_count_total += len(clusters)
        selected = []
        for items in clusters.values():
            best = max(items, key=lambda item: item["momentum_6m"])
            selected.append(best)
        selected = sorted(selected, key=lambda item: item["momentum_6m"], reverse=True)
        return [item["symbol"] for item in selected[: max(1, int(self.p.top_n_holdings))]]

    def next(self):
        """Evaluate current features and rebalance holdings on schedule."""
        self.bar_num += 1
        current_dt = pd.Timestamp(bt.num2date(self.datas[0].datetime[0])).tz_localize(None)
        if self.order_refs:
            return
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        features_df = (self.p.feature_lookup or {}).get(current_dt)
        if features_df is None or features_df.empty:
            return
        selected = set(self._select_assets(features_df))
        target_weight = 1.0 / len(selected) if selected else 0.0
        self.rebalance_count += 1
        for data in self.datas:
            target_pct = target_weight if data._name in selected else 0.0
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
        """Remove completed order refs from local tracking set."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        """Count closed trades and win/loss outcomes for assertions."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_055_som_investment_strategy() -> None:
    """Migrated regression test for others/0055_som_investment_strategy."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    asset_map = {sym: load_mt5_csv(p, fromdate=fromdate, todate=todate) for sym, p in ASSET_FILES.items()}
    asset_data, feature_lookup = prepare_som_inputs(asset_map, params=dict(
        momentum_period=126, vol_period=20, drawdown_period=63,
    ))

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    for sym in ASSET_FILES.keys():
        cerebro.adddata(bt.feeds.PandasData(dataname=asset_data[sym], timeframe=bt.TimeFrame.Days), name=sym)
    cerebro.addstrategy(SOMInvestmentStrategy, feature_lookup=feature_lookup,
                       som_rows=3, som_cols=3, som_iterations=250,
                       learning_rate=0.15, top_n_holdings=3, rebalance_interval_days=21)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"rebalance={strat.rebalance_count} clusters={strat.cluster_count_total} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 1539
    assert strat.buy_count == 144
    assert strat.sell_count == 92
    assert strat.rebalance_count == 67
    assert strat.cluster_count_total == 407
    assert strat.trade_count == 0
    assert total_trades == 0
    assert abs(final_value - 1726402.5544) < 1.0
