"""Inlined regression test for others/0063_treasury_return_predictability_strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import backtrader as bt
import pandas as pd
from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
TREASURY_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "IEF_1d.csv"
EQUITY_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "IVV_1d.csv"
GOLD_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "GLD_1d.csv"


def prepare_asset_data(asset_map):
    """Align and trim all frames onto a common trading calendar."""
    aligned_index = None
    prepared = {}
    for _, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in asset_map.items():
        prepared[symbol] = frame.loc[aligned_index][["open", "high", "low", "close", "volume", "openinterest"]].copy()
    return prepared


class TreasuryReturnPredictabilityStrategy(bt.Strategy):
    """Treasury yield-predictability strategy that rotates bond/equity/gold weights."""
    params = dict(
        lookback_days=252,
        high_yield_bond_weight=0.60,
        low_yield_bond_weight=0.30,
        neutral_bond_weight=0.45,
        equity_residual_share=0.70,
        gold_residual_share=0.30,
        rebalance_interval_days=21,
        commission_pct=0.0005,
    )

    def __init__(self):
        """Initialize regime counters and order/trade tracking state."""
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.rebalance_count = 0
        self.high_yield_regime_days = 0
        self.low_yield_regime_days = 0
        self.neutral_regime_days = 0

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

    def _yield_percentile_proxy(self):
        treasury = self.datas[0]
        lookback = int(self.p.lookback_days)
        if len(treasury) <= lookback:
            return None
        history = [float(treasury.close[-idx]) for idx in range(lookback, -1, -1)]
        series = pd.Series(history)
        current_price = float(treasury.close[0])
        current_yield_proxy = -current_price / series.mean() + 1.0
        historical_proxy = -(series / series.rolling(21).mean()) + 1.0
        historical_proxy = historical_proxy.dropna()
        if historical_proxy.empty:
            return None
        percentile = float((historical_proxy < current_yield_proxy).mean()) * 100.0
        return percentile

    def next(self):
        """Compute yield regime, determine target weights, and rebalance on schedule."""
        self.bar_num += 1
        if self.order_refs:
            return
        percentile = self._yield_percentile_proxy()
        if percentile is None:
            return
        if percentile > 55.0:
            bond_weight = float(self.p.high_yield_bond_weight)
            self.high_yield_regime_days += 1
        elif percentile < 45.0:
            bond_weight = float(self.p.low_yield_bond_weight)
            self.low_yield_regime_days += 1
        else:
            bond_weight = float(self.p.neutral_bond_weight)
            self.neutral_regime_days += 1
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        residual = max(0.0, 1.0 - bond_weight)
        target_map = {
            self.datas[0]._name: bond_weight,
            self.datas[1]._name: residual * float(self.p.equity_residual_share),
            self.datas[2]._name: residual * float(self.p.gold_residual_share),
        }
        self.rebalance_count += 1
        for data in self.datas:
            target_pct = target_map.get(data._name, 0.0)
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
        """Clear tracked order IDs when they leave submitted/accepted states."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        """Increment trade and win/loss counters for closed trade events."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_063_treasury_return_predictability_strategy() -> None:
    """Migrated regression test for others/0063_treasury_return_predictability_strategy."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = {
        "IEF": load_mt5_csv(TREASURY_FILE, fromdate=fromdate, todate=todate),
        "IVV": load_mt5_csv(EQUITY_FILE, fromdate=fromdate, todate=todate),
        "GLD": load_mt5_csv(GOLD_FILE, fromdate=fromdate, todate=todate),
    }
    asset_data = prepare_asset_data(raw)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    for sym in ("IEF", "IVV", "GLD"):
        cerebro.adddata(bt.feeds.PandasData(dataname=asset_data[sym], timeframe=bt.TimeFrame.Days), name=sym)
    cerebro.addstrategy(TreasuryReturnPredictabilityStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4518
    assert strat.buy_count == 396
    assert strat.sell_count == 215
    assert strat.trade_count == 0
    assert total_trades == 0
    assert abs(final_value - 2937291.2630) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
