"""Inlined regression test for machine_learning/0001_candlestick_kmeans_classification_gold.

Self-contained single-file test (manually authored). Runs with runonce=True only.
KMeans clustering of XAUUSD candlestick features for next-day directional bias.

Data Used:
    Loads XAUUSD daily MT5 data from ``tests/datas/mt5_1d_data/XAUUSD_1d.csv``
    and evaluates the period from 2022-01-01 to 2025-12-31.
    The pipeline creates candlestick ratio features and cluster signals, then runs a
    single-day open/close strategy feed on daily bars.

Strategy Principle:
    The strategy runs periodic KMeans refits on normalized candlestick features
    (high-open, low-open, close-open) and identifies an "active" cluster with
    above-benchmark next-bar return.
    A long entry is triggered when the current candle's predicted cluster matches
    the selected cluster; exits are forced before EOD to ensure one-day holds.

Strategy Logic:
    Feature preparation computes ATR-normalized candlestick statistics and rolling
    cluster assignments/edge values.
    The strategy submits a market buy when an entry signal is present and
    closes any intraday position on the same trading day.
    Analyzer assertions validate deterministic order counts and final value.
"""
from __future__ import annotations

import datetime
import io
import warnings
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "XAUUSD_1d.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    """Load an MT5 CSV file and normalize it to an indexed OHLCV frame.

    Args:
        filepath: Path to the source CSV export.
        fromdate: Optional start datetime to filter rows.
        todate: Optional end datetime to filter rows.
        bar_shift_minutes: Optional minute offset applied to datetime index.

    Returns:
        A pandas DataFrame indexed by datetime with OHLC and volume fields.
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
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=int(bar_shift_minutes))
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def _calculate_atr(df, period=14):
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(int(period), min_periods=int(period)).mean()


def prepare_candlestick_cluster_features(df, params):
    """Prepare candlestick features and rolling KMeans-derived trade signals.

    Args:
        df: Input dataframe with OHLCV columns and datetime index.
        params: Parameter dictionary controlling ATR, training window, and clustering.

    Returns:
        DataFrame containing engineered features and entry signal columns.
    """
    out = df.copy()
    atr_period = int(params.get("atr_period", 14))
    train_window = int(params.get("train_window", 756))
    refit_interval = max(1, int(params.get("refit_interval", 20)))
    n_clusters = int(params.get("n_clusters", 4))
    min_cluster_size = max(5, int(params.get("min_cluster_size", 20)))

    out["atr"] = _calculate_atr(out, period=atr_period)
    out["ho"] = out["high"] - out["open"]
    out["lo"] = out["low"] - out["open"]
    out["co"] = out["close"] - out["open"]
    out["ho_norm"] = out["ho"] / out["atr"]
    out["lo_norm"] = out["lo"] / out["atr"]
    out["co_norm"] = out["co"] / out["atr"]
    out["next_intraday_return"] = out["close"].shift(-1) / out["open"].shift(-1) - 1.0

    clusters = np.full(len(out), np.nan, dtype=float)
    selected_clusters = np.full(len(out), np.nan, dtype=float)
    cluster_edge = np.full(len(out), np.nan, dtype=float)
    raw_signal = np.zeros(len(out), dtype=float)

    fitted_model = None
    active_cluster = None
    active_edge = None

    feature_cols = ["ho_norm", "lo_norm", "co_norm"]
    base = out.dropna(subset=feature_cols + ["next_intraday_return"]).copy()
    valid_positions = {idx: pos for pos, idx in enumerate(out.index)}

    for idx in range(train_window, len(base)):
        current_dt = base.index[idx]
        if fitted_model is None or (idx - train_window) % refit_interval == 0:
            train = base.iloc[idx - train_window:idx].copy()
            train_x = train[feature_cols].to_numpy(dtype=float)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fitted_model = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
                train_labels = fitted_model.fit_predict(train_x)
            train = train.assign(cluster=train_labels)
            cluster_stats = train.groupby("cluster")["next_intraday_return"].agg(["mean", "count"]).sort_values("mean", ascending=False)
            benchmark = float(train["next_intraday_return"].mean())
            eligible = cluster_stats[cluster_stats["count"] >= min_cluster_size]
            if not eligible.empty and float(eligible.iloc[0]["mean"]) > benchmark:
                active_cluster = float(eligible.index[0])
                active_edge = float(eligible.iloc[0]["mean"] - benchmark)
            else:
                active_cluster = None
                active_edge = 0.0
        feature_vector = base.iloc[[idx]][feature_cols].to_numpy(dtype=float)
        pred_cluster = float(fitted_model.predict(feature_vector)[0]) if fitted_model is not None else np.nan
        pos = valid_positions[current_dt]
        clusters[pos] = pred_cluster
        selected_clusters[pos] = active_cluster if active_cluster is not None else np.nan
        cluster_edge[pos] = active_edge if active_edge is not None else 0.0
        raw_signal[pos] = 1.0 if active_cluster is not None and pred_cluster == active_cluster else 0.0

    out["cluster"] = clusters
    out["selected_cluster"] = selected_clusters
    out["cluster_edge"] = cluster_edge
    out["raw_signal"] = raw_signal
    out["entry_signal"] = out["raw_signal"].shift(1).fillna(0.0)
    out = out[["open", "high", "low", "close", "volume", "openinterest", "atr",
               "ho_norm", "lo_norm", "co_norm",
               "cluster", "selected_cluster", "cluster_edge", "raw_signal", "entry_signal"]].copy()
    return out.dropna(subset=["atr", "cluster"])


class Mt5CandlestickClusterFeed(bt.feeds.PandasData):
    """Pandas feed that exposes KMeans feature columns to Backtrader."""

    lines = ("atr", "ho_norm", "lo_norm", "co_norm", "cluster", "selected_cluster", "cluster_edge",
             "raw_signal", "entry_signal")
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("atr", 6), ("ho_norm", 7), ("lo_norm", 8), ("co_norm", 9), ("cluster", 10),
        ("selected_cluster", 11), ("cluster_edge", 12), ("raw_signal", 13), ("entry_signal", 14),
    )


class CandlestickKMeansGoldStrategy(bt.Strategy):
    """Daily-long trading strategy using precomputed KMeans entry flags."""

    params = dict(
        target_percent=0.95,
    )

    def __init__(self):
        """Initialize order/session counters used by assertions."""
        self.pending_order = None
        self.entry_session_date = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.trade_signal_count = 0

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        if target_notional_pct <= 0:
            return 0.0
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.open[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, "mult", 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * float(target_notional_pct) * 0.995 / (execution_price * multiplier)
        return max(0.01, round(size, 2))

    def next_open(self):
        """Place a long entry when today's signal is active and no order is pending."""
        if self.pending_order is not None or self.position:
            return
        if float(self.data.entry_signal[0]) <= 0.5:
            return
        size = self._get_position_size(target_notional_pct=float(self.p.target_percent), price=float(self.data.open[0]))
        if size <= 0:
            return
        self.trade_signal_count += 1
        self.buy_count += 1
        self.entry_session_date = bt.num2date(self.data.datetime[0]).date()
        self.pending_order = self.buy(size=size)

    def next(self):
        """Advance bar counter and close position at session end of entry day."""
        self.bar_num += 1
        current_dt = bt.num2date(self.data.datetime[0])
        if self.pending_order is not None:
            return
        if self.position and self.entry_session_date == current_dt.date():
            self.sell_count += 1
            self.pending_order = self.close()

    def notify_order(self, order):
        """Reset pending order state and session date on order lifecycle changes."""
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status in (order.Canceled, order.Margin, order.Rejected) and not self.position:
            self.entry_session_date = None
        if order.status == order.Completed and not self.position:
            self.entry_session_date = None
        self.pending_order = None

    def notify_trade(self, trade):
        """Increment win/loss counters for completed trades."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_001_candlestick_kmeans_classification_gold() -> None:
    """Migrated regression test for machine_learning/0001_candlestick_kmeans_classification_gold."""
    fromdate = datetime.datetime(2022, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    params = dict(
        train_window=756, refit_interval=20, n_clusters=4,
        atr_period=14, min_cluster_size=20,
    )
    frame = prepare_candlestick_cluster_features(raw, params)

    cerebro = bt.Cerebro(stdstats=False, cheat_on_open=True)
    cerebro.broker.set_coc(True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0002, margin=0.01, mult=100.0,
                                  commtype=bt.CommInfoBase.COMM_PERC, percabs=True, stocklike=False)
    cerebro.adddata(Mt5CandlestickClusterFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.addstrategy(CandlestickKMeansGoldStrategy, target_percent=0.95)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"trade_signal={strat.trade_signal_count} win={strat.win_count} loss={strat.loss_count} "
          f"trade={strat.trade_count} total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 262
    assert strat.buy_count == 70
    assert strat.sell_count == 70
    assert strat.trade_signal_count == 70
    assert strat.win_count == 0
    assert strat.loss_count == 70
    assert strat.trade_count == 70
    assert total_trades == 70
    assert abs(final_value - 999734.7629) < 1.0
