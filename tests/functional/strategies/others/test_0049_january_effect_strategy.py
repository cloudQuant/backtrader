"""Inlined regression test for others/0049_january_effect_strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Universe: IWM, IVV, IWD.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import backtrader as bt
import pandas as pd
from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_DIR = _REPO / "tests" / "datas" / "mt5_1d_data"
ASSET_FILES = {
    "iwm": DATA_DIR / "IWM_1d.csv",
    "ivv": DATA_DIR / "IVV_1d.csv",
    "iwd": DATA_DIR / "IWD_1d.csv",
}


def prepare_january_inputs(asset_map):
    """Align assets by calendar and build January-effect winner lookup."""
    aligned_index = None
    prepared = {}
    for _, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in asset_map.items():
        prepared[symbol] = frame.loc[aligned_index][["open", "high", "low", "close", "volume", "openinterest"]].copy()
    close_df = pd.DataFrame({symbol: frame.loc[aligned_index, "close"] for symbol, frame in asset_map.items()},
                             index=aligned_index)
    signal_lookup = {}
    years = sorted(set(aligned_index.year))
    for year in years[:-1]:
        year_mask = close_df.index.year == year
        next_year_mask = close_df.index.year == (year + 1)
        next_year_jan_mask = next_year_mask & (close_df.index.month == 1)
        next_year_feb_mask = next_year_mask & (close_df.index.month == 2)
        if year_mask.sum() == 0 or next_year_jan_mask.sum() == 0 or next_year_feb_mask.sum() == 0:
            continue
        year_returns = (close_df.loc[year_mask].iloc[-1] / close_df.loc[year_mask].iloc[0] - 1.0).sort_values(ascending=True)
        selected = year_returns.index[:1].tolist()
        jan_dates = close_df.index[next_year_jan_mask]
        feb_first = close_df.index[next_year_feb_mask][0]
        for dt in jan_dates:
            signal_lookup[pd.Timestamp(dt).tz_localize(None)] = selected
        signal_lookup[pd.Timestamp(feb_first).tz_localize(None)] = []
    return prepared, signal_lookup


class JanuaryEffectStrategy(bt.Strategy):
    """Rotate exposure into the weakest-performing asset entering Jan/Feb."""
    params = dict(signal_lookup=None)

    def __init__(self):
        """Initialize order tracking, counters, and calendar state."""
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.active_january_days = 0

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
        """Check signal day allocations and rebalance each data feed accordingly."""
        self.bar_num += 1
        current_dt = pd.Timestamp(bt.num2date(self.datas[0].datetime[0])).tz_localize(None)
        if self.order_refs:
            return
        selected = (self.p.signal_lookup or {}).get(current_dt)
        if selected is None:
            return
        if selected:
            self.active_january_days += 1
        target_weight = 1.0 / len(selected) if selected else 0.0
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
        """Drop completed order refs from the tracking set."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        """Track closed trade outcomes and outcome counters."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_049_january_effect_strategy() -> None:
    """Migrated regression test for others/0049_january_effect_strategy."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    asset_map = {sym: load_mt5_csv(p, fromdate=fromdate, todate=todate) for sym, p in ASSET_FILES.items()}
    asset_data, signal_lookup = prepare_january_inputs(asset_map)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    for sym in ASSET_FILES.keys():
        cerebro.adddata(bt.feeds.PandasData(dataname=asset_data[sym], timeframe=bt.TimeFrame.Days), name=sym)
    cerebro.addstrategy(JanuaryEffectStrategy, signal_lookup=signal_lookup)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"active_jan_days={strat.active_january_days} total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4518
    assert strat.buy_count == 346
    assert strat.sell_count == 0
    assert strat.active_january_days == 343
    assert strat.trade_count == 0
    assert total_trades == 0
    assert abs(final_value - 1000009.5410) < 1.0
