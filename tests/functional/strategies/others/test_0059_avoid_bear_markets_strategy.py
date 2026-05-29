"""Inlined regression test for others/0059_avoid_bear_markets_strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
EQUITY_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "IVV_1d.csv"
BOND_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "IEF_1d.csv"
GOLD_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "GLD_1d.csv"


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


def prepare_asset_data(asset_map):
    aligned_index = None
    prepared = {}
    for _, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in asset_map.items():
        prepared[symbol] = frame.loc[aligned_index][["open", "high", "low", "close", "volume", "openinterest"]].copy()
    return prepared


class AvoidBearMarketsStrategy(bt.Strategy):
    params = dict(
        sma_period=200,
        momentum_period=252,
        macro_lookback=126,
        invest_threshold=0.5,
        weights=None,
        rebalance_interval_days=21,
        allocation=None,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.invest_days = 0
        self.exit_days = 0

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

    def _combined_signal(self):
        equity = self.datas[0]
        bond = self.datas[1]
        gold = self.datas[2]
        sma_period = int(self.p.sma_period)
        momentum_period = int(self.p.momentum_period)
        macro_lookback = int(self.p.macro_lookback)
        if len(equity) <= max(sma_period, momentum_period, macro_lookback):
            return None
        sma_values = [float(equity.close[-i]) for i in range(sma_period)]
        sma = sum(sma_values) / len(sma_values)
        sma_signal = 1.0 if float(equity.close[0]) > sma else 0.0
        momentum_signal = 1.0 if float(equity.close[0] / equity.close[-momentum_period] - 1.0) > 0 else 0.0
        price_signal = 0.5 * (sma_signal + momentum_signal)
        equity_rel_bond = float(equity.close[0] / equity.close[-macro_lookback] - 1.0) - float(bond.close[0] / bond.close[-macro_lookback] - 1.0)
        equity_rel_gold = float(equity.close[0] / equity.close[-macro_lookback] - 1.0) - float(gold.close[0] / gold.close[-macro_lookback] - 1.0)
        macro_signal = 1.0 if (equity_rel_bond > 0 and equity_rel_gold > 0) else 0.0
        yield_curve_signal = 1.0 if equity_rel_bond > 0 else 0.0
        weights = self.p.weights or {}
        combined = (
            float(weights.get("price", 0.4)) * price_signal
            + float(weights.get("macro", 0.3)) * macro_signal
            + float(weights.get("yield_curve", 0.3)) * yield_curve_signal
        )
        return combined

    def next(self):
        self.bar_num += 1
        if self.order_refs:
            return
        combined_signal = self._combined_signal()
        if combined_signal is None:
            return
        regime = "invest" if combined_signal > float(self.p.invest_threshold) else "exit"
        if regime == "invest":
            self.invest_days += 1
        else:
            self.exit_days += 1
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        allocation = (self.p.allocation or {}).get(regime, {})
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
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_059_avoid_bear_markets_strategy() -> None:
    """Migrated regression test for others/0059_avoid_bear_markets_strategy."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = {
        "IVV": load_mt5_csv(EQUITY_FILE, fromdate=fromdate, todate=todate),
        "IEF": load_mt5_csv(BOND_FILE, fromdate=fromdate, todate=todate),
        "GLD": load_mt5_csv(GOLD_FILE, fromdate=fromdate, todate=todate),
    }
    asset_data = prepare_asset_data(raw)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    for sym in ("IVV", "IEF", "GLD"):  # order matters for combined_signal()
        cerebro.adddata(bt.feeds.PandasData(dataname=asset_data[sym], timeframe=bt.TimeFrame.Days), name=sym)
    cerebro.addstrategy(
        AvoidBearMarketsStrategy,
        weights={"price": 0.4, "macro": 0.3, "yield_curve": 0.3},
        allocation={
            "invest": {"IVV": 0.75, "IEF": 0.15, "GLD": 0.10},
            "exit": {"IVV": 0.05, "IEF": 0.60, "GLD": 0.35},
        },
    )
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
    assert strat.buy_count == 405
    assert strat.sell_count == 207
    assert strat.trade_count == 0
    assert total_trades == 0
    assert abs(final_value - 1827735.3188) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
