"""Inlined regression test for others/0064_country_valuation_strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Universe: country ETFs EWA, EWC, EWG, EWJ, EWQ, EWU, EWY, EWH.
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
COUNTRY_FILES = {
    "EWA": DATA_DIR / "EWA_1d.csv",
    "EWC": DATA_DIR / "EWC_1d.csv",
    "EWG": DATA_DIR / "EWG_1d.csv",
    "EWJ": DATA_DIR / "EWJ_1d.csv",
    "EWQ": DATA_DIR / "EWQ_1d.csv",
    "EWU": DATA_DIR / "EWU_1d.csv",
    "EWY": DATA_DIR / "EWY_1d.csv",
    "EWH": DATA_DIR / "EWH_1d.csv",
}


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


def prepare_country_valuation_data(price_map, params):
    aligned_index = None
    prepared = {}
    valuation_lookback = int(params.get("valuation_lookback", 252))
    momentum_lookback = int(params.get("momentum_lookback", 126))
    for _, frame in price_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in price_map.items():
        px = frame.loc[aligned_index].copy()
        price_to_mean = px["close"] / px["close"].rolling(valuation_lookback).mean()
        z_price = (price_to_mean - price_to_mean.rolling(valuation_lookback).mean()) / price_to_mean.rolling(valuation_lookback).std().replace(0, np.nan)
        momentum = px["close"].pct_change(momentum_lookback)
        valuation_score = 0.8 * z_price + 0.2 * momentum
        prepared[symbol] = px[["open", "high", "low", "close", "volume", "openinterest"]].copy()
        prepared[symbol]["valuation_score"] = valuation_score.astype(float)
    score_df = pd.DataFrame({symbol: frame["valuation_score"] for symbol, frame in prepared.items()}, index=aligned_index)
    return prepared, score_df.dropna(how="all")


class CountryValuationFeed(bt.feeds.PandasData):
    lines = ("valuation_score",)
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("valuation_score", 6),
    )


class CountryValuationStrategy(bt.Strategy):
    params = dict(
        n_long=3,
        n_short=3,
        rebalance_interval_days=63,
        max_leg_notional_pct=0.18,
    )

    def __init__(self):
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.long_books = 0
        self.short_books = 0

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
        self.bar_num += 1
        if self.order_refs:
            return
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        scores = []
        for data in self.datas:
            score = float(data.valuation_score[0]) if data.valuation_score[0] == data.valuation_score[0] else None
            if score is None:
                continue
            scores.append((data, score))
        if len(scores) < max(int(self.p.n_long), int(self.p.n_short)):
            return
        ranked = sorted(scores, key=lambda item: item[1])
        long_group = ranked[:int(self.p.n_long)]
        short_group = ranked[-int(self.p.n_short):]
        target_map = {data._name: 0.0 for data in self.datas}
        long_weight = float(self.p.max_leg_notional_pct) / max(1, int(self.p.n_long))
        short_weight = -float(self.p.max_leg_notional_pct) / max(1, int(self.p.n_short))
        for data, _ in long_group:
            target_map[data._name] = long_weight
        for data, _ in short_group:
            target_map[data._name] = short_weight
        self.long_books += 1
        self.short_books += 1
        for data in self.datas:
            target_pct = target_map[data._name]
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


def test_064_country_valuation_strategy() -> None:
    """Migrated regression test for others/0064_country_valuation_strategy."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    asset_map = {sym: load_mt5_csv(p, fromdate=fromdate, todate=todate) for sym, p in COUNTRY_FILES.items()}
    prepared_map, score_df = prepare_country_valuation_data(asset_map, params=dict(
        valuation_lookback=252, momentum_lookback=126,
    ))

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    for sym in COUNTRY_FILES.keys():
        feed = CountryValuationFeed(
            dataname=prepared_map[sym][[
                "open", "high", "low", "close", "volume", "openinterest", "valuation_score",
            ]].copy(),
            timeframe=bt.TimeFrame.Days,
        )
        cerebro.adddata(feed, name=sym)
    cerebro.addstrategy(CountryValuationStrategy, n_long=3, n_short=3,
                       rebalance_interval_days=63, max_leg_notional_pct=0.18)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"long_books={strat.long_books} short_books={strat.short_books} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4516
    assert strat.buy_count == 271
    assert strat.sell_count == 213
    assert strat.long_books == 64
    assert strat.short_books == 64
    assert strat.win_count == 98
    assert strat.loss_count == 78
    assert strat.trade_count == 176
    assert total_trades == 176
    assert abs(final_value - 797285.8307) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
