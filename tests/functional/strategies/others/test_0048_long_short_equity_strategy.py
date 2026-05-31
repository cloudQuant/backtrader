"""Inlined regression test for others/0048_long_short_equity_strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Universe: IVV, IWM, IWD, GLD, IEF.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
DATA_DIR = _REPO / "tests" / "datas" / "mt5_1d_data"
ASSET_FILES = {
    "ivv": DATA_DIR / "IVV_1d.csv",
    "iwm": DATA_DIR / "IWM_1d.csv",
    "iwd": DATA_DIR / "IWD_1d.csv",
    "gld": DATA_DIR / "GLD_1d.csv",
    "ief": DATA_DIR / "IEF_1d.csv",
}


def load_mt5_csv(filepath, fromdate=None, todate=None):
    """Load MT5 CSV data and return a cleaned OHLCV DataFrame."""
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


def prepare_long_short_inputs(asset_map):
    """Align multiple assets on a common date index and return aligned frame map/close matrix."""
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


def build_weight_lookup(close_df, params):
    """Build periodic rebalance target weights from momentum and inverse-volatility score."""
    momentum_lookback = int(params.get("momentum_lookback", 252))
    volatility_lookback = int(params.get("volatility_lookback", 60))
    n_long = int(params.get("n_long", 2))
    n_short = int(params.get("n_short", 2))
    long_weight = float(params.get("long_weight", 1.0))
    short_weight = float(params.get("short_weight", 1.0))
    rebalance_step = max(1, int(params.get("rebalance_interval_days", 21)))
    returns = close_df.pct_change()
    weight_lookup = {}
    start = max(momentum_lookback, volatility_lookback) + 1
    for idx in range(start, len(close_df), rebalance_step):
        date = pd.Timestamp(close_df.index[idx]).tz_localize(None)
        momentum = (close_df.iloc[idx] / close_df.iloc[idx - momentum_lookback] - 1.0).rank(pct=True)
        low_vol = (-returns.iloc[idx - volatility_lookback:idx].std()).rank(pct=True)
        score = 0.6 * momentum + 0.4 * low_vol
        long_assets = score.sort_values(ascending=False).head(n_long).index.tolist()
        short_assets = score.sort_values(ascending=True).head(n_short).index.tolist()
        weights = {}
        for symbol in long_assets:
            weights[symbol] = long_weight / max(1, len(long_assets))
        for symbol in short_assets:
            weights[symbol] = -short_weight / max(1, len(short_assets))
        weight_lookup[date] = weights
    return weight_lookup


class LongShortEquityStrategy(bt.Strategy):
    """Long/short equity allocator with periodic rebalance based on precomputed weights."""
    params = dict(weight_lookup=None)

    def __init__(self):
        """Initialize order tracking and execution counters."""
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
        """Rebalance holdings toward target weights on scheduled rebalance dates."""
        self.bar_num += 1
        current_dt = pd.Timestamp(bt.num2date(self.datas[0].datetime[0])).tz_localize(None)
        if self.order_refs:
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
        """Remove completed order refs to allow next rebalance cycle."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        """Count trade closes and separate win/loss outcomes."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_048_long_short_equity_strategy() -> None:
    """Migrated regression test for others/0048_long_short_equity_strategy."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    asset_map = {sym: load_mt5_csv(p, fromdate=fromdate, todate=todate) for sym, p in ASSET_FILES.items()}
    asset_data, close_df = prepare_long_short_inputs(asset_map)
    weight_lookup = build_weight_lookup(close_df, params=dict(
        momentum_lookback=252, volatility_lookback=60,
        n_long=2, n_short=2, long_weight=1.0, short_weight=1.0,
        rebalance_interval_days=21,
    ))

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    for sym in ASSET_FILES.keys():
        cerebro.adddata(bt.feeds.PandasData(dataname=asset_data[sym], timeframe=bt.TimeFrame.Days), name=sym)
    cerebro.addstrategy(LongShortEquityStrategy, weight_lookup=weight_lookup)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"rebalance={strat.rebalance_count} win={strat.win_count} loss={strat.loss_count} "
          f"trade={strat.trade_count} total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4516
    assert strat.buy_count == 440
    assert strat.sell_count == 477
    assert strat.rebalance_count == 203
    assert strat.win_count == 63
    assert strat.loss_count == 79
    assert strat.trade_count == 142
    assert total_trades == 142
    assert abs(final_value - 663860.3293) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
