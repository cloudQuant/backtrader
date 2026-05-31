"""Manual single-file regression test for ``test_0006_mixture_model_bottom_prediction``.

Runs with ``runonce=True`` only.

Data Used:
    Multi-symbol XAUUSD, IEF, and USDJPY daily exports from
    ``tests/datas/mt5_1d_data`` (``XAUUSD_1d.csv``, ``IEF_1d.csv``,
    ``USDJPY_1d.csv``). The test limits data by explicit date bounds and
    derives rolling momentum/volatility features before running one-pass backtest.

Strategy Principle:
    Builds feature vectors across own-price and proxy signals, then trains a
    Gaussian Mixture model with z-scored features to infer bottom-like market
    regimes. The selected bottom state drives a target exposure signal and hold
    timing logic.

Strategy Logic:
    ``prepare_mixture_bottom_features`` trains/updates the model on a rolling
    window, produces bottom probability and ``target_exposure`` signals, and emits
    ``signal_change`` events. ``MixtureBottomStrategy`` rebalances only when
    the signal changes, while ``notify_order`` and ``notify_trade`` maintain
    execution/trade counters.
"""
from __future__ import annotations

import datetime
import io
import warnings
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

_REPO = Path(__file__).resolve().parents[4]
PRICE_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "XAUUSD_1d.csv"
IEF_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "IEF_1d.csv"
USDJPY_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "USDJPY_1d.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None):
    """Load an MT5 daily export into a sorted datetime-indexed DataFrame.

    Args:
        filepath: Path to the data file.
        fromdate: Optional inclusive lower time bound.
        todate: Optional inclusive upper time bound.

    Returns:
        pandas.DataFrame: DataFrame with OHLCV and open interest columns.
    """
    with open(filepath, "r", encoding="utf-8", errors="ignore") as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = "\n".join(lines)
    sep = "\t" if "\t" in lines[0] else ","
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = df["<DATE>"].astype(str) + " " + df["<TIME>"].astype(str)
    parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M:%S", errors="coerce")
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M", errors="coerce")
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


def _compute_rsi(prices, window):
    delta = prices.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.rolling(window).mean()
    avg_loss = loss.rolling(window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def _label_bottom_state(model, scaler, train_slice, feature_columns):
    train_scaled = scaler.transform(train_slice[feature_columns].values.astype(float))
    hidden_states = model.predict(train_scaled)
    score_by_state = {}
    for state in range(model.n_components):
        mask = hidden_states == state
        if not np.any(mask):
            score_by_state[state] = 999.0
            continue
        subset = train_scaled[mask]
        log_ret_mean = float(np.mean(subset[:, feature_columns.index("log_return")]))
        drawdown_mean = float(np.mean(subset[:, feature_columns.index("drawdown_63")]))
        momentum_mean = float(np.mean(subset[:, feature_columns.index("momentum_21")]))
        rsi_mean = float(np.mean(subset[:, feature_columns.index("rsi_14")]))
        score_by_state[state] = log_ret_mean + drawdown_mean + 0.75 * momentum_mean + 0.50 * rsi_mean
    return int(min(score_by_state, key=score_by_state.get))


def prepare_mixture_bottom_features(price_df, proxy_frames, params):
    """Create rolling features and bottom-regime exposure targets.

    Args:
        price_df: Main XAUUSD DataFrame indexed by datetime.
        proxy_frames: Dict with aligned proxy market frames (IEF and USDJPY).
        params: Parameter map controlling feature windows and model settings.

    Returns:
        pandas.DataFrame: Feature frame with signal columns used by the strategy.
    """
    common_index = price_df.index
    for frame in proxy_frames.values():
        common_index = common_index.intersection(frame.index)
    common_index = common_index.sort_values()

    gold = price_df.loc[common_index].copy()
    ief = proxy_frames["IEF"].loc[common_index].copy()
    usdjpy = proxy_frames["USDJPY"].loc[common_index].copy()

    out = gold.copy()
    vol_window = int(params.get("volatility_window", 20))
    dd_window = int(params.get("drawdown_window", 63))
    mom_window = int(params.get("momentum_window", 21))
    long_mom_window = int(params.get("long_momentum_window", 252))
    rsi_window = int(params.get("rsi_window", 14))
    train_window = int(params.get("train_window", 252))
    retrain_interval = int(params.get("retrain_interval", 21))
    n_components = int(params.get("n_components", 2))
    max_iter = int(params.get("max_iter", 200))
    probability_threshold = float(params.get("probability_threshold", 0.60))
    exit_probability_threshold = float(params.get("exit_probability_threshold", 0.45))
    hold_days = int(params.get("hold_days", 5))
    cooldown_days = int(params.get("cooldown_days", 5))
    target_percent = float(params.get("target_percent", 0.95))
    drawdown_threshold = float(params.get("drawdown_threshold", -0.05))
    rsi_threshold = float(params.get("rsi_threshold", 45.0))

    out["log_return"] = np.log(out["close"] / out["close"].shift(1))
    out["volatility_20"] = out["log_return"].rolling(vol_window).std() * np.sqrt(252.0)
    out["drawdown_63"] = out["close"] / out["close"].rolling(dd_window).max() - 1.0
    out["momentum_21"] = out["close"].pct_change(mom_window)
    out["momentum_252"] = out["close"].pct_change(long_mom_window)
    out["rsi_14"] = _compute_rsi(out["close"], rsi_window)
    out["ief_momentum_21"] = ief["close"].pct_change(mom_window)
    out["jpy_strength_21"] = -(usdjpy["close"].pct_change(mom_window))

    feature_columns = [
        "log_return", "volatility_20", "drawdown_63", "momentum_21",
        "momentum_252", "rsi_14", "ief_momentum_21", "jpy_strength_21",
    ]
    feature_frame = out[feature_columns].copy()

    predicted_state = [np.nan] * len(out)
    bottom_probability = [np.nan] * len(out)
    target_exposure = [0.0] * len(out)
    retrain_point = [0.0] * len(out)
    bottom_signal = [0.0] * len(out)
    hold_counter_series = [0.0] * len(out)

    last_model = None
    last_scaler = None
    last_bottom_state = None
    last_train_idx = None

    position = 0.0
    hold_counter = 0
    cooldown = 0

    for idx in range(len(out)):
        start = idx - train_window
        if start < 0:
            continue
        train_slice = feature_frame.iloc[start:idx].dropna()
        current_row = feature_frame.iloc[idx:idx + 1].dropna()
        if len(train_slice) < train_window or current_row.empty:
            continue

        should_retrain = last_model is None or last_train_idx is None or (idx - last_train_idx) >= retrain_interval
        if should_retrain:
            scaler = StandardScaler()
            train_scaled = scaler.fit_transform(train_slice[feature_columns].values.astype(float))
            model = GaussianMixture(
                n_components=n_components,
                max_iter=max_iter,
                init_params="random",
                covariance_type="full",
                random_state=42,
            )
            try:
                model.fit(train_scaled)
                last_model = model
                last_scaler = scaler
                last_bottom_state = _label_bottom_state(model, scaler, train_slice, feature_columns)
                last_train_idx = idx
                retrain_point[idx] = 1.0
            except Exception:
                continue

        if last_model is None or last_scaler is None or last_bottom_state is None:
            continue

        try:
            current_scaled = last_scaler.transform(current_row[feature_columns].values.astype(float))
            current_state = int(last_model.predict(current_scaled)[0])
            current_proba = last_model.predict_proba(current_scaled)[0]
        except Exception:
            continue

        current_bottom_probability = float(current_proba[last_bottom_state])
        current_drawdown = float(current_row["drawdown_63"].iloc[0])
        current_rsi = float(current_row["rsi_14"].iloc[0])
        current_state_is_bottom = 1.0 if current_state == last_bottom_state else 0.0
        qualifies = (
            current_state_is_bottom > 0.5
            and current_bottom_probability >= probability_threshold
            and current_drawdown <= drawdown_threshold
            and current_rsi <= rsi_threshold
        )

        if cooldown > 0:
            cooldown -= 1

        if position <= 0.0:
            if qualifies and cooldown <= 0:
                position = target_percent
                hold_counter = hold_days
                bottom_signal[idx] = 1.0
        else:
            hold_counter -= 1
            if hold_counter <= 0 or current_bottom_probability < exit_probability_threshold:
                position = 0.0
                hold_counter = 0
                cooldown = cooldown_days

        predicted_state[idx] = current_state
        bottom_probability[idx] = current_bottom_probability
        target_exposure[idx] = position
        hold_counter_series[idx] = hold_counter

    out["predicted_state"] = pd.Series(predicted_state, index=out.index, dtype="float64")
    out["bottom_probability"] = pd.Series(bottom_probability, index=out.index, dtype="float64")
    out["target_exposure"] = pd.Series(target_exposure, index=out.index, dtype="float64")
    out["retrain_point"] = pd.Series(retrain_point, index=out.index, dtype="float64")
    out["bottom_signal"] = pd.Series(bottom_signal, index=out.index, dtype="float64")
    out["hold_counter"] = pd.Series(hold_counter_series, index=out.index, dtype="float64")
    out["signal_change"] = out["target_exposure"].ne(out["target_exposure"].shift(1)).astype(float)

    columns = [
        "open", "high", "low", "close", "volume", "openinterest",
        "predicted_state", "bottom_probability", "target_exposure",
        "retrain_point", "bottom_signal", "hold_counter", "signal_change",
    ]
    return out[columns].copy().dropna()


class MixtureBottomFeed(bt.feeds.PandasData):
    """PandasData extension that exposes mixture model bottom-detection fields."""
    lines = (
        "predicted_state", "bottom_probability", "target_exposure",
        "retrain_point", "bottom_signal", "hold_counter", "signal_change",
    )
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("predicted_state", 6), ("bottom_probability", 7), ("target_exposure", 8),
        ("retrain_point", 9), ("bottom_signal", 10), ("hold_counter", 11), ("signal_change", 12),
    )


class MixtureBottomStrategy(bt.Strategy):
    """Signal-change driven rebalancing strategy for bottom-detection regime.

    Opens/reduces exposure according to ``target_exposure`` and tracks trade
    lifecycle outcomes.
    """
    params = dict()

    def __init__(self):
        """Initialize execution and telemetry state."""
        self.bar_num = 0
        self.pending_order = None
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.retrain_count = 0
        self.signal_change_count = 0
        self.bottom_signal_count = 0

    def next(self):
        """Issue rebalances when the strategy signal toggles.

        The strategy only sends a target-size order when ``signal_change`` is
        asserted and no order is currently pending.
        """
        self.bar_num += 1
        if float(self.data.retrain_point[0]) > 0.5:
            self.retrain_count += 1
        if float(self.data.bottom_signal[0]) > 0.5:
            self.bottom_signal_count += 1
        if self.pending_order is not None:
            return
        if float(self.data.signal_change[0]) <= 0.5:
            return
        self.signal_change_count += 1
        self.pending_order = self.order_target_percent(target=float(self.data.target_exposure[0]))

    def notify_order(self, order):
        """Clear the pending order reference after an order leaves active state.

        Args:
            order: The order whose status changed.
        """
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        """Count closed-trade outcomes for win/loss statistics.

        Args:
            trade: The trade object reported by Backtrader.
        """
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_006_mixture_model_bottom_prediction() -> None:
    """Migrated regression test for others/0006_mixture_model_bottom_prediction."""
    fromdate = datetime.datetime(2018, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(PRICE_FILE, fromdate=fromdate, todate=todate)
    proxy = {
        "IEF": load_mt5_csv(IEF_FILE, fromdate=fromdate, todate=todate),
        "USDJPY": load_mt5_csv(USDJPY_FILE, fromdate=fromdate, todate=todate),
    }
    params = dict(
        n_components=2, train_window=252, retrain_interval=21, max_iter=200,
        probability_threshold=0.60, exit_probability_threshold=0.45,
        hold_days=5, cooldown_days=5, target_percent=0.95,
        volatility_window=20, drawdown_window=63, momentum_window=21,
        long_momentum_window=252, rsi_window=14,
        drawdown_threshold=-0.05, rsi_threshold=45,
    )
    frame = prepare_mixture_bottom_features(raw, proxy, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0002)
    cerebro.adddata(MixtureBottomFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.addstrategy(MixtureBottomStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} signal_changes={strat.signal_change_count} "
          f"bottom_signals={strat.bottom_signal_count} retrain={strat.retrain_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 1498
    assert strat.signal_change_count == 66
    assert strat.bottom_signal_count == 33
    assert strat.retrain_count == 72
    assert strat.win_count == 18
    assert strat.loss_count == 15
    assert strat.trade_count == 33
    assert total_trades == 33
    assert abs(final_value - 1040064.7400) < 1.0
