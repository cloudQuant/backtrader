"""Inlined regression test for others/0053_high_inflation_factor_strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Factor universe: value=IWD, momentum=PDP, quality=DBMF, size=IWM, low_vol=GLD.
Inflation proxy: DBC (added last so the strategy looks at datas[-1]).

Data Used:
    Six daily ETF feeds from ``tests/datas/mt5_1d_data`` in MetaTrader 5 export
    format, clipped to 2008-01-01 through 2025-12-31 and aligned to a common
    trading calendar: a five-factor basket (value=IWD, momentum=PDP,
    quality=DBMF, size=IWM, low_vol=GLD) plus an inflation proxy (DBC, added last
    so it is addressed as datas[-1]).

Strategy Principle:
    A factor-rotation overlay driven by the inflation regime. The DBC commodity
    proxy stands in for inflation: its year-over-year change, confirmed over a
    multi-month window, classifies the environment as high-inflation or normal.
    The strategy holds an equal-weight factor basket in normal times and tilts
    toward inflation-resilient factors (more value, quality, and low-vol; less
    momentum and size) when high inflation is confirmed, rebalancing on a fixed
    cadence rather than reacting to every bar.

Strategy Logic:
    load_mt5_csv loads each ETF, prepare_factor_inputs intersects their dates
    into a common index, and the test adds all six feeds plus the inflation proxy
    last. Each bar HighInflationFactorStrategy evaluates the confirmed inflation
    regime, selects the matching weight set, and — only on the rebalance interval
    — issues order_target_size orders to move each factor ETF toward its target
    weight. notify_order tracks pending references and notify_trade tallies
    closed trades. The test builds cerebro, forces runonce=True, and asserts the
    regime-day counters, order counts, and final portfolio value against
    migration-time values.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import backtrader as bt
from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_DIR = _REPO / "tests" / "datas" / "mt5_1d_data"
FACTOR_FILES = {
    "value": DATA_DIR / "IWD_1d.csv",
    "momentum": DATA_DIR / "PDP_1d.csv",
    "quality": DATA_DIR / "DBMF_1d.csv",
    "size": DATA_DIR / "IWM_1d.csv",
    "low_vol": DATA_DIR / "GLD_1d.csv",
}
INFLATION_FILE = DATA_DIR / "DBC_1d.csv"


def prepare_factor_inputs(asset_map):
    """Align factor dataframes and select OHLCV columns for each symbol.

    Args:
        asset_map: Mapping of symbol names to dataframes with a datetime index.

    Returns:
        A dictionary of aligned dataframes keyed by symbol.
    """
    aligned_index = None
    prepared = {}
    for _, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in asset_map.items():
        prepared[symbol] = frame.loc[aligned_index][["open", "high", "low", "close", "volume", "openinterest"]].copy()
    return prepared


class HighInflationFactorStrategy(bt.Strategy):
    """Rebalance factor-weighted portfolio by inflation regime state.

    The strategy monitors an inflation proxy and shifts exposure between a
    normal factor basket and a high-inflation variant after regime confirmation.
    """
    params = dict(
        inflation_threshold=0.0562,
        confirm_days=63,
        inflation_lookback=252,
        rebalance_interval_days=21,
        normal_weights=None,
        high_inflation_weights=None,
        commission_pct=0.0005,
    )

    def __init__(self):
        """Initialize order tracking and run-time diagnostic counters."""
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.high_inflation_days = 0
        self.normal_inflation_days = 0

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

    def _is_high_inflation(self):
        inflation = self.datas[-1]
        lookback = int(self.p.inflation_lookback)
        confirm_days = int(self.p.confirm_days)
        if len(inflation) <= max(lookback, confirm_days):
            return False
        yoy = float(inflation.close[0] / inflation.close[-lookback] - 1.0)
        recent = []
        for i in range(confirm_days):
            if len(inflation) <= lookback + i:
                return False
            recent.append(float(inflation.close[-i] / inflation.close[-lookback - i] - 1.0))
        return yoy > float(self.p.inflation_threshold) and all(value > float(self.p.inflation_threshold) for value in recent)

    def next(self):
        """Run strategy logic each bar and submit rebalance orders when due."""
        self.bar_num += 1
        if self.order_refs:
            return
        high_inflation = self._is_high_inflation()
        if high_inflation:
            weights = dict(self.p.high_inflation_weights or {})
            self.high_inflation_days += 1
        else:
            weights = dict(self.p.normal_weights or {})
            self.normal_inflation_days += 1
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        for data in self.datas[:-1]:
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
        """Release locally tracked references when an order is no longer pending."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        """Update closed-trade counters for later assertion checks in tests."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_053_high_inflation_factor_strategy() -> None:
    """Migrated regression test for others/0053_high_inflation_factor_strategy."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    asset_map = {sym: load_mt5_csv(p, fromdate=fromdate, todate=todate) for sym, p in FACTOR_FILES.items()}
    asset_map["inflation_proxy"] = load_mt5_csv(INFLATION_FILE, fromdate=fromdate, todate=todate)
    asset_data = prepare_factor_inputs(asset_map)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    for sym in list(FACTOR_FILES.keys()) + ["inflation_proxy"]:
        cerebro.adddata(bt.feeds.PandasData(dataname=asset_data[sym], timeframe=bt.TimeFrame.Days), name=sym)
    cerebro.addstrategy(
        HighInflationFactorStrategy,
        inflation_threshold=0.0562, confirm_days=63, inflation_lookback=252,
        rebalance_interval_days=21,
        normal_weights={"value": 0.20, "momentum": 0.20, "quality": 0.20, "size": 0.20, "low_vol": 0.20},
        high_inflation_weights={"value": 0.35, "quality": 0.30, "low_vol": 0.20, "momentum": 0.10, "size": 0.05},
    )
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"high_inf_days={strat.high_inflation_days} normal_days={strat.normal_inflation_days} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 1539
    assert strat.buy_count == 221
    assert strat.sell_count == 149
    assert strat.high_inflation_days == 392
    assert strat.normal_inflation_days == 1147
    assert strat.trade_count == 0
    assert total_trades == 0
    assert abs(final_value - 1551226.5837) < 1.0
