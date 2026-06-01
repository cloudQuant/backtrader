"""Inlined regression test for the UPI multi-asset rotation strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Universe: IVV, IEF, GLD, DBC.

Data Used:
    Daily MT5 exports for IVV, IEF, GLD, and DBC from
    ``tests/datas/mt5_1d_data``. Bars run from 2008-01-01 to 2025-12-31.

Strategy Principle:
    The strategy periodically reallocates portfolio weights using the Ulcer
    Performance Index (annualized return divided by ulcer drawdown risk), while
    capping individual allocations.

Strategy Logic:
    ``prepare_upi_inputs`` aligns closes by timestamp, ``build_weight_lookup``
    computes rebalance weights at fixed intervals using lookback statistics,
    and ``UlcerPerformanceIndexStrategy`` submits target-size orders only on
    rebalance dates. Order and trade callbacks maintain execution and result
    counters.
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
    "ief": DATA_DIR / "IEF_1d.csv",
    "gld": DATA_DIR / "GLD_1d.csv",
    "dbc": DATA_DIR / "DBC_1d.csv",
}


def prepare_upi_inputs(asset_map):
    """Align all assets to a common trading calendar and build close matrix.

    Args:
        asset_map: Mapping from symbol to per-symbol OHLCV DataFrame.

    Returns:
        A tuple ``(prepared_frames, close_df)`` where ``prepared_frames`` uses
        aligned indexes for all symbols and ``close_df`` is wide close-price
        matrix for all assets.
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
    return prepared, close_df


def calculate_ulcer_index(price_series):
    """Calculate ulcer index from a price series.

    Args:
        price_series: Price path series.

    Returns:
        Ulcer index as a float.
    """
    peak = price_series.cummax()
    drawdown = ((peak - price_series) / peak).clip(lower=0.0)
    return float(np.sqrt(np.mean(np.square(drawdown)))) if len(drawdown) else 0.0


def build_weight_lookup(close_df, params):
    """Build rebalance date -> target-weight dictionaries from UPI scores.

    Args:
        close_df: Wide DataFrame of aligned close prices.
        params: Strategy hyperparameters including risk/weight controls.

    Returns:
        Mapping from rebalance datetimes to per-asset target portfolio weights.
    """
    lookback = int(params.get("lookback_window", 126))
    ulcer_window = int(params.get("ulcer_window", 50))
    max_weight = float(params.get("max_weight", 0.4))
    min_weight = float(params.get("min_weight", 0.0))
    rebalance_step = max(1, int(params.get("rebalance_interval_days", 21)))
    risk_free = float(params.get("risk_free_rate", 0.02))
    returns_df = close_df.pct_change().dropna()
    weight_lookup = {}
    for idx in range(lookback, len(close_df), rebalance_step):
        date = pd.Timestamp(close_df.index[idx]).tz_localize(None)
        scores = {}
        for symbol in close_df.columns:
            price_window = close_df[symbol].iloc[idx - lookback:idx]
            return_window = returns_df[symbol].iloc[max(0, idx - lookback):idx].dropna()
            if len(price_window) < ulcer_window or return_window.empty:
                continue
            ulcer = calculate_ulcer_index(price_window.iloc[-ulcer_window:])
            annual_return = float(return_window.mean() * 252)
            upi = (annual_return - risk_free) / ulcer if ulcer > 0 else -1e9
            scores[symbol] = upi
        if not scores:
            continue
        score_series = pd.Series(scores).sort_values(ascending=False)
        positive = score_series.clip(lower=0.0)
        if positive.sum() <= 0:
            raw_weights = pd.Series(1.0 / len(score_series), index=score_series.index)
        else:
            raw_weights = positive / positive.sum()
        capped = raw_weights.clip(lower=min_weight, upper=max_weight)
        if capped.sum() <= 0:
            capped = pd.Series(1.0 / len(score_series), index=score_series.index)
        weights = capped / capped.sum()
        weight_lookup[date] = weights.to_dict()
    return weight_lookup


class UlcerPerformanceIndexStrategy(bt.Strategy):
    """Multi-asset UPI rotation strategy with interval rebalancing."""
    params = dict(
        weight_lookup=None,
        rebalance_interval_days=21,
    )

    def __init__(self):
        """Initialize counters and active order references."""
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
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

    def next(self):
        """Run rebalance logic on scheduled bars and submit size targets."""
        self.bar_num += 1
        current_dt = pd.Timestamp(bt.num2date(self.datas[0].datetime[0])).tz_localize(None)
        if self.order_refs:
            return
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        weights = (self.p.weight_lookup or {}).get(current_dt)
        if not weights:
            return
        self.rebalance_count += 1
        for data in self.datas:
            target_pct = float(weights.get(data._name, 0.0))
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
        """Drop completed/pending order refs from the tracking set.

        Args:
            order: The order state update.
        """
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        """Count closed trades by profit sign.

        Args:
            trade: Closed trade instance from Backtrader.
        """
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_050_ulcer_performance_index_strategy() -> None:
    """Migrated regression test for others/0050_ulcer_performance_index_strategy."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    asset_map = {sym: load_mt5_csv(p, fromdate=fromdate, todate=todate) for sym, p in ASSET_FILES.items()}
    asset_data, close_df = prepare_upi_inputs(asset_map)
    weight_lookup = build_weight_lookup(close_df, params=dict(
        ulcer_window=50, lookback_window=126, risk_free_rate=0.02,
        max_weight=0.4, min_weight=0.0, rebalance_interval_days=21,
    ))

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    for sym in ASSET_FILES.keys():
        cerebro.adddata(bt.feeds.PandasData(dataname=asset_data[sym], timeframe=bt.TimeFrame.Days), name=sym)
    cerebro.addstrategy(UlcerPerformanceIndexStrategy, weight_lookup=weight_lookup, rebalance_interval_days=21)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"rebalance={strat.rebalance_count} win={strat.win_count} loss={strat.loss_count} "
          f"trade={strat.trade_count} total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4518
    assert strat.buy_count == 393
    assert strat.sell_count == 184
    assert strat.rebalance_count == 210
    assert strat.trade_count == 0
    assert total_trades == 0
    assert abs(final_value - 2583927.4063) < 1.0
