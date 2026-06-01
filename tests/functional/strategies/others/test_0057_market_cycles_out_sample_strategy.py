"""Inlined regression test for others/0057_market_cycles_out_sample_strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Universe: equity=IVV, bond=IEF, gold=GLD, commodity=DBC.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import backtrader as bt
from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_DIR = _REPO / "tests" / "datas" / "mt5_1d_data"
ASSET_FILES = {
    "equity": DATA_DIR / "IVV_1d.csv",
    "bond": DATA_DIR / "IEF_1d.csv",
    "gold": DATA_DIR / "GLD_1d.csv",
    "commodity": DATA_DIR / "DBC_1d.csv",
}
ALLOCATION = {
    "bull_low_falling": {"equity": 0.70, "bond": 0.20, "gold": 0.10, "commodity": 0.00},
    "bull_high_rising": {"equity": 0.50, "bond": 0.10, "gold": 0.20, "commodity": 0.20},
    "bear_low_falling": {"equity": 0.30, "bond": 0.50, "gold": 0.20, "commodity": 0.00},
    "bear_high_rising": {"equity": 0.20, "bond": 0.20, "gold": 0.30, "commodity": 0.30},
}


def prepare_asset_data(asset_map):
    """Align all asset series on a common datetime index.

    Args:
        asset_map: Mapping of symbol -> source dataframe.

    Returns:
        Dictionary of prepared OHLCV dataframes keyed by symbol.
    """
    aligned_index = None
    prepared = {}
    for _, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in asset_map.items():
        prepared[symbol] = frame.loc[aligned_index][["open", "high", "low", "close", "volume", "openinterest"]].copy()
    return prepared


class MarketCyclesOutSampleStrategy(bt.Strategy):
    """Cycle-based allocation strategy across four asset classes.

    The strategy switches allocation buckets based on equity trend, commodity
    inflation proxy, and bond rate trend signals.
    """
    params = dict(
        equity_sma=200,
        inflation_lookback=126,
        inflation_threshold=0.03,
        rate_sma=252,
        rebalance_interval_days=21,
        allocation=None,
    )

    def __init__(self):
        """Initialize runtime counters and order tracking for cycle diagnostics."""
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.bull_count = 0
        self.bear_count = 0
        self.high_inflation_count = 0
        self.low_inflation_count = 0
        self.rising_rate_count = 0
        self.falling_rate_count = 0

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

    def _sma(self, data, period):
        values = [float(data.close[-i]) for i in range(period)]
        return sum(values) / len(values)

    def _detect_cycle(self):
        required = max(int(self.p.equity_sma), int(self.p.inflation_lookback), int(self.p.rate_sma))
        if len(self.datas[0]) <= required:
            return None
        feed_map = {data._name: data for data in self.datas}
        equity = feed_map["equity"]
        bond = feed_map["bond"]
        commodity = feed_map["commodity"]
        equity_cycle = "bull" if float(equity.close[0]) > self._sma(equity, int(self.p.equity_sma)) else "bear"
        commodity_return = float(commodity.close[0] / commodity.close[-int(self.p.inflation_lookback)] - 1.0)
        inflation_cycle = "high" if commodity_return > float(self.p.inflation_threshold) else "low"
        rate_cycle = "falling" if float(bond.close[0]) > self._sma(bond, int(self.p.rate_sma)) else "rising"
        return {
            "equity": equity_cycle,
            "inflation": inflation_cycle,
            "rate": rate_cycle,
            "key": f"{equity_cycle}_{inflation_cycle}_{rate_cycle}",
        }

    def next(self):
        """Detect current cycle regime and rebalance when the interval is reached."""
        self.bar_num += 1
        if self.order_refs:
            return
        cycle = self._detect_cycle()
        if cycle is None:
            return
        if cycle["equity"] == "bull":
            self.bull_count += 1
        else:
            self.bear_count += 1
        if cycle["inflation"] == "high":
            self.high_inflation_count += 1
        else:
            self.low_inflation_count += 1
        if cycle["rate"] == "rising":
            self.rising_rate_count += 1
        else:
            self.falling_rate_count += 1
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        allocation = (self.p.allocation or {}).get(cycle["key"], {})
        for data in self.datas:
            target_pct = float(allocation.get(data._name, 0.0))
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
        """Update tracked order refs when a non-pending status is observed."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        """Aggregate trade results only when a trade has been closed."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_057_market_cycles_out_sample_strategy() -> None:
    """Migrated regression test for others/0057_market_cycles_out_sample_strategy."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    asset_map = {sym: load_mt5_csv(p, fromdate=fromdate, todate=todate) for sym, p in ASSET_FILES.items()}
    asset_data = prepare_asset_data(asset_map)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    for sym in ASSET_FILES.keys():
        cerebro.adddata(bt.feeds.PandasData(dataname=asset_data[sym], timeframe=bt.TimeFrame.Days), name=sym)
    cerebro.addstrategy(MarketCyclesOutSampleStrategy, allocation=ALLOCATION)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"bull={strat.bull_count} bear={strat.bear_count} highinf={strat.high_inflation_count} "
          f"lowinf={strat.low_inflation_count} rising={strat.rising_rate_count} "
          f"falling={strat.falling_rate_count} win={strat.win_count} loss={strat.loss_count} "
          f"trade={strat.trade_count} total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4518
    assert strat.buy_count == 328
    assert strat.sell_count == 185
    assert strat.bull_count == 3440
    assert strat.bear_count == 826
    assert strat.high_inflation_count == 1567
    assert strat.low_inflation_count == 2699
    assert strat.rising_rate_count == 2129
    assert strat.falling_rate_count == 2137
    assert strat.trade_count == 0
    assert total_trades == 0
    assert abs(final_value - 2115069.1219) < 1.0
