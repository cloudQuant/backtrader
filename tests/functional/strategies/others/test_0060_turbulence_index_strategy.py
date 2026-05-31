"""Inlined regression test for the Turbulence Index regime-allocation strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Universe: IVV, IEF, GLD, DBC, EEM. Uses Mahalanobis-distance turbulence
index.

Data Used:
    MT5 daily OHLCV data for IVV, IEF, GLD, DBC, and EEM from
    ``tests/datas/mt5_1d_data`` spanning 2008-01-01 to 2025-12-31.

Strategy Principle:
    A rolling Mahalanobis turbulence measure maps each date to regime states
    (high, normal, low). Each regime has a fixed target allocation map, so the
    strategy rotates exposures at configured rebalance intervals.

Strategy Logic:
    Inputs are aligned by timestamp, turbulence is computed on return vectors, and
    each bar resolves the current regime. On rebalance bars, ``next`` targets
    position sizes to regime-specific allocations. Order and trade callbacks track
    activity and outcome counts.
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
ALLOCATION = {
    "high_turbulence": {"IVV": 0.20, "IEF": 0.30, "GLD": 0.35, "DBC": 0.05, "EEM": 0.00},
    "low_turbulence": {"IVV": 0.55, "IEF": 0.15, "GLD": 0.10, "DBC": 0.10, "EEM": 0.10},
    "normal": {"IVV": 0.35, "IEF": 0.25, "GLD": 0.20, "DBC": 0.10, "EEM": 0.10},
}


def load_mt5_csv(filepath, fromdate=None, todate=None):
    """Load a MetaTrader-5 export into an aligned OHLCV DataFrame.

    Args:
        filepath: Path to the MT5 CSV/TSV file.
        fromdate: Optional start datetime (inclusive).
        todate: Optional end datetime (inclusive).

    Returns:
        Datetime-indexed DataFrame with standard OHLCV fields.
    """
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


def prepare_turbulence_inputs(asset_map):
    """Align all asset data and return closes matrix plus return series.

    Args:
        asset_map: Mapping from symbol names to DataFrames.

    Returns:
        Tuple ``(prepared_frames, aligned_index, returns_df)`` where returns are
        percentage changes with matching index.
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
    returns_df = close_df.pct_change().dropna()
    return prepared, aligned_index, returns_df


def compute_turbulence_series(returns_df, lookback):
    """Compute rolling Mahalanobis turbulence scores.

    Args:
        returns_df: Return matrix indexed by date and columns for symbols.
        lookback: Lookback window length for covariance/mean estimation.

    Returns:
        Series of non-negative turbulence scores, indexed by computation date.
    """
    values = []
    index = []
    for i in range(lookback, len(returns_df)):
        hist = returns_df.iloc[i - lookback:i]
        current = returns_df.iloc[i]
        mu = hist.mean()
        cov = hist.cov()
        try:
            cov_inv = np.linalg.pinv(cov.to_numpy(dtype=float))
            deviation = (current - mu).to_numpy(dtype=float)
            turbulence = float(deviation.T @ cov_inv @ deviation)
        except Exception:
            turbulence = np.nan
        values.append(turbulence)
        index.append(returns_df.index[i])
    series = pd.Series(values, index=index, dtype=float)
    return series.dropna()


def build_state_lookup(turbulence_series, params):
    """Convert turbulence levels to discrete regime labels.

    Args:
        turbulence_series: Time series of turbulence scores.
        params: Dict containing ``high_percentile`` and ``low_percentile``.

    Returns:
        Mapping from normalized timestamp to one of ``high_turbulence``,
        ``low_turbulence``, or ``normal``.
    """
    high_pct = float(params.get("high_percentile", 75))
    low_pct = float(params.get("low_percentile", 25))
    lookup = {}
    for idx in range(len(turbulence_series)):
        history = turbulence_series.iloc[:idx + 1]
        current = float(history.iloc[-1])
        high_threshold = float(np.percentile(history, high_pct))
        low_threshold = float(np.percentile(history, low_pct))
        if current > high_threshold:
            state = "high_turbulence"
        elif current < low_threshold:
            state = "low_turbulence"
        else:
            state = "normal"
        lookup[pd.Timestamp(history.index[-1]).normalize()] = state
    return lookup


class TurbulenceIndexStrategy(bt.Strategy):
    """Regime-aware multi-asset strategy with scheduled target rebalancing."""
    params = dict(
        rebalance_interval_days=21,
        allocation=None,
        state_lookup=None,
    )

    def __init__(self):
        """Initialize counters and working state."""
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.high_turbulence_days = 0
        self.low_turbulence_days = 0
        self.normal_days = 0

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
        """On scheduled rebalance bars, shift positions toward regime targets."""
        self.bar_num += 1
        if self.order_refs:
            return
        current_dt = pd.Timestamp(bt.num2date(self.datas[0].datetime[0])).normalize()
        state = (self.p.state_lookup or {}).get(current_dt)
        if state is None:
            return
        if state == "high_turbulence":
            self.high_turbulence_days += 1
        elif state == "low_turbulence":
            self.low_turbulence_days += 1
        else:
            self.normal_days += 1
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        allocation = (self.p.allocation or {}).get(state, {})
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
        """Remove completed orders from the local pending set.

        Args:
            order: Order object from Backtrader.
        """
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        """Count each closed trade outcome.

        Args:
            trade: Closed trade instance.
        """
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_060_turbulence_index_strategy() -> None:
    """Migrated regression test for others/0060_turbulence_index_strategy."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    asset_map = {sym: load_mt5_csv(p, fromdate=fromdate, todate=todate) for sym, p in ASSET_FILES.items()}
    prepared_map, aligned_index, returns_df = prepare_turbulence_inputs(asset_map)
    turbulence = compute_turbulence_series(returns_df, lookback=252)
    valid_index = aligned_index.intersection(turbulence.index)
    prepared_map = {symbol: frame.loc[valid_index].copy() for symbol, frame in prepared_map.items()}
    turbulence = turbulence.loc[valid_index]
    state_lookup = build_state_lookup(turbulence, dict(high_percentile=75, low_percentile=25))

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    for sym in ASSET_FILES.keys():
        cerebro.adddata(bt.feeds.PandasData(dataname=prepared_map[sym], timeframe=bt.TimeFrame.Days), name=sym)
    cerebro.addstrategy(TurbulenceIndexStrategy, allocation=ALLOCATION, state_lookup=state_lookup,
                       rebalance_interval_days=21)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"high={strat.high_turbulence_days} low={strat.low_turbulence_days} normal={strat.normal_days} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4264
    assert strat.buy_count == 564
    assert strat.sell_count == 422
    assert strat.high_turbulence_days == 1240
    assert strat.low_turbulence_days == 913
    assert strat.normal_days == 2111
    assert strat.trade_count == 0
    assert total_trades == 0
    assert abs(final_value - 2458532.5047) < 1.0
