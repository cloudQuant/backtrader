"""Inlined regression test for trend_following/0002_gold_hmm_trend_following.

Self-contained single-file test (manually authored). Runs with runonce=True only.

Data Used:
    A single MT5 daily CSV feed, ``XAUUSD_1d.csv`` (gold), resolved as
    ``DATA_FILE`` under the repo's ``tests/datas`` directory. The regression run
    uses the 2024-01-01 to 2025-12-31 window (daily timeframe, no resampling).
    The daily series is enriched with HMM regime features and per-bar target
    weights before being fed to the strategy.

Strategy Principle:
    A regime-switching trend follower driven by a Gaussian Hidden Markov Model.
    On a rolling window the HMM is fit to standardized log-return and volatility
    features, and its hidden states are labelled BULL, BEAR or NEUTRAL by mean
    return. The strategy assumes regimes persist, so it goes long in confident,
    persistent BULL states and short in BEAR states, sizing exposure by a
    volatility target scaled by state confidence. Risk is managed with a stop
    loss, a break-even arm after a profit threshold, regime-reversal exits and
    partial scale-outs in neutral regimes.

Strategy Logic:
    1. ``load_mt5_csv`` loads the gold data and ``prepare_hmm_features`` walks the
       series, periodically retraining the HMM (helpers ``_standardize`` and
       ``_label_states``) to emit regime labels, confidence, persistence and a
       dynamic target percent.
    2. ``Mt5HMMTrendFeed`` exposes those features as extra data lines;
       ``GoldHMMTrendFollowingStrategy.__init__`` resets the many trade/exit
       counters and entry-tracking state.
    3. ``next`` opens longs/shorts on confident bull/bear signals, applies
       stop-loss, break-even, reversal and partial-exit logic when in a
       position; ``notify_order`` tracks entry price and clears pending orders;
       ``notify_trade`` tallies win/loss counts.
    4. ``test_001_0002_gold_hmm_trend_following`` loads the data, runs the
       backtest with fixed parameters under ``runonce=True`` and asserts the
       captured metrics match the recorded expectations.
"""
from __future__ import annotations

import datetime
import warnings
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd
import pytest
from backtrader.utils.load_data import load_mt5_csv

# Optional ML dependency: skip the whole module when hmmlearn is absent
# (e.g. minimal CI images) instead of failing at import/collection time.
pytest.importorskip("hmmlearn")

from hmmlearn.hmm import GaussianHMM

warnings.filterwarnings("ignore")

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_1d.csv"


def _standardize(train_values, predict_values):
    mean = np.nanmean(train_values, axis=0)
    std = np.nanstd(train_values, axis=0)
    std = np.where(std == 0, 1.0, std)
    return (train_values - mean) / std, (predict_values - mean) / std


def _label_states(model, features_std):
    hidden_states = model.predict(features_std)
    labels = {}
    state_stats = {}
    for state in range(model.n_components):
        mask = hidden_states == state
        if not np.any(mask):
            state_stats[state] = {"ret_mean": -999.0, "vol_mean": 999.0}
            continue
        subset = features_std[mask]
        state_stats[state] = {
            "ret_mean": float(np.mean(subset[:, 0])),
            "vol_mean": float(np.mean(subset[:, 1])),
        }
    bull_state = max(state_stats, key=lambda s: state_stats[s]["ret_mean"])
    bear_state = min(state_stats, key=lambda s: state_stats[s]["ret_mean"])
    for state in state_stats:
        if state == bull_state:
            labels[state] = "BULL"
        elif state == bear_state:
            labels[state] = "BEAR"
        else:
            labels[state] = "NEUTRAL"
    return labels


def prepare_hmm_features(df, params):
    """Compute HMM regime features and dynamic target weights per bar.

    Builds log-return and rolling-volatility features, then walks the series
    periodically retraining a Gaussian HMM, labelling its states BULL/BEAR/
    NEUTRAL, and recording the predicted state, confidence, persistence,
    consistency and a confidence- and volatility-scaled target percent, plus
    bull/bear/neutral signal flags.

    Args:
        df: Daily OHLCV DataFrame for gold.
        params: Strategy parameter dictionary controlling the training window,
            retrain interval, state count and sizing thresholds.

    Returns:
        pandas.DataFrame: OHLCV plus the regime/signal/target columns, with
        warm-up and NaN rows dropped.
    """
    out = df.copy()
    train_window = int(params.get("train_window", 252))
    retrain_interval = int(params.get("retrain_interval", 21))
    vol_window = int(params.get("vol_window", 20))
    n_states = int(params.get("n_states", 3))
    n_iter = int(params.get("n_iter", 300))
    covariance_type = str(params.get("covariance_type", "full"))
    random_state = int(params.get("random_state", 42))
    state_persistence_min = float(params.get("state_persistence_min", 0.7))
    consistency_days = int(params.get("consistency_days", 3))
    target_volatility = max(float(params.get("target_volatility", 0.15)), 1e-6)
    base_target_percent = float(params.get("base_target_percent", 0.03))
    max_target_percent = float(params.get("max_target_percent", 0.10))

    out["log_return"] = np.log(out["close"] / out["close"].shift(1))
    out["volatility_20"] = out["log_return"].rolling(vol_window).std() * np.sqrt(252.0)
    feature_frame = out[["log_return", "volatility_20"]].copy()

    predicted_state = [np.nan] * len(out)
    regime_label = [""] * len(out)
    regime_score = [np.nan] * len(out)
    state_confidence = [np.nan] * len(out)
    persistence_prob = [np.nan] * len(out)
    state_consistent = [0.0] * len(out)
    target_percent = [0.0] * len(out)
    retrain_points = [0.0] * len(out)

    last_model = None
    last_labels = None
    last_train_idx = None

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
            train_values = train_slice.values.astype(float)
            predict_values = np.vstack([train_values, current_row.values.astype(float)])
            train_std, predict_std = _standardize(train_values, predict_values)
            model = GaussianHMM(
                n_components=n_states,
                covariance_type=covariance_type,
                n_iter=n_iter,
                random_state=random_state,
            )
            try:
                model.fit(train_std)
                labels = _label_states(model, train_std)
                last_model = model
                last_labels = labels
                last_train_idx = idx
                retrain_points[idx] = 1.0
            except Exception:
                continue

        if last_model is None or last_labels is None:
            continue

        train_values = train_slice.values.astype(float)
        predict_values = np.vstack([train_values, current_row.values.astype(float)])
        train_std, predict_std = _standardize(train_values, predict_values)
        try:
            state_seq = last_model.predict(predict_std)
            proba = last_model.predict_proba(predict_std)
        except Exception:
            continue
        current_state = int(state_seq[-1])
        current_label = last_labels.get(current_state, "NEUTRAL")
        current_confidence = float(proba[-1, current_state])
        persistence = float(last_model.transmat_[current_state, current_state])
        last_k_states = state_seq[-consistency_days:] if len(state_seq) >= consistency_days else state_seq
        consistent = float(len(last_k_states) == consistency_days and np.all(last_k_states == current_state))
        vol_factor = min(target_volatility / max(float(current_row["volatility_20"].iloc[0]), 1e-6),
                         max_target_percent / max(base_target_percent, 1e-6))
        dynamic_target = min(max_target_percent, base_target_percent * current_confidence * vol_factor)
        if current_confidence < state_persistence_min or persistence < state_persistence_min or consistent < 0.5:
            dynamic_target = 0.0

        predicted_state[idx] = current_state
        regime_label[idx] = current_label
        regime_score[idx] = 1.0 if current_label == "BULL" else (-1.0 if current_label == "BEAR" else 0.0)
        state_confidence[idx] = current_confidence
        persistence_prob[idx] = persistence
        state_consistent[idx] = consistent
        target_percent[idx] = dynamic_target

    out["predicted_state"] = pd.Series(predicted_state, index=out.index, dtype="float64")
    out["regime_score"] = pd.Series(regime_score, index=out.index, dtype="float64")
    out["state_confidence"] = pd.Series(state_confidence, index=out.index, dtype="float64")
    out["persistence_prob"] = pd.Series(persistence_prob, index=out.index, dtype="float64")
    out["state_consistent"] = pd.Series(state_consistent, index=out.index, dtype="float64")
    out["target_percent"] = pd.Series(target_percent, index=out.index, dtype="float64")
    out["retrain_point"] = pd.Series(retrain_points, index=out.index, dtype="float64")
    out["bull_signal"] = ((pd.Series(regime_label, index=out.index) == "BULL") & (out["target_percent"] > 0)).astype(float)
    out["bear_signal"] = ((pd.Series(regime_label, index=out.index) == "BEAR") & (out["target_percent"] > 0)).astype(float)
    out["neutral_signal"] = (pd.Series(regime_label, index=out.index) == "NEUTRAL").astype(float)

    columns = [
        "open", "high", "low", "close", "volume", "openinterest",
        "predicted_state", "regime_score", "state_confidence", "persistence_prob",
        "state_consistent", "target_percent", "retrain_point", "bull_signal", "bear_signal", "neutral_signal",
    ]
    return out[columns].copy().dropna()


class Mt5HMMTrendFeed(bt.feeds.PandasData):
    """Custom PandasData feed carrying HMM regime features and trading signals."""
    lines = (
        "predicted_state", "regime_score", "state_confidence", "persistence_prob",
        "state_consistent", "target_percent", "retrain_point", "bull_signal", "bear_signal", "neutral_signal",
    )
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
        ("predicted_state", 6), ("regime_score", 7), ("state_confidence", 8), ("persistence_prob", 9),
        ("state_consistent", 10), ("target_percent", 11), ("retrain_point", 12),
        ("bull_signal", 13), ("bear_signal", 14), ("neutral_signal", 15),
    )


class GoldHMMTrendFollowingStrategy(bt.Strategy):
    """Regime-switching trend strategy backed by HMM state confidence signals."""
    params = dict(
        stop_loss_pct=0.03,
        take_profit_pct=0.08,
        train_window=252,
        retrain_interval=21,
        vol_window=20,
        n_states=3,
        n_iter=300,
        covariance_type="full",
        random_state=42,
        state_persistence_min=0.7,
        consistency_days=3,
        target_volatility=0.15,
        base_target_percent=0.03,
        max_target_percent=0.1,
    )

    def __init__(self):
        """Initialize counters, state, and runtime order tracking."""
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.short_count = 0
        self.cover_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.partial_exit_count = 0
        self.stop_exit_count = 0
        self.reverse_exit_count = 0
        self.retrain_count = 0
        self.pending_order = None
        self.entry_price = None
        self.break_even_armed = False

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        if target_notional_pct <= 0:
            return 0.0
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, "mult", 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * float(target_notional_pct) / (execution_price * multiplier)
        return max(0.01, round(size, 2))

    def next(self):
        """Check signals each bar and manage entries, exits, and partial exits."""
        self.bar_num += 1
        if float(self.data.retrain_point[0]) > 0.5:
            self.retrain_count += 1

        if self.pending_order is not None:
            return

        close_price = float(self.data.close[0])
        bull_signal = float(self.data.bull_signal[0]) > 0.5
        bear_signal = float(self.data.bear_signal[0]) > 0.5
        neutral_signal = float(self.data.neutral_signal[0]) > 0.5
        target_percent = float(self.data.target_percent[0])

        if self.position:
            pnl_pct = (close_price / self.entry_price - 1.0) if self.entry_price else 0.0
            if self.position.size < 0:
                pnl_pct = -pnl_pct
            if not self.break_even_armed and pnl_pct >= float(self.p.take_profit_pct):
                self.break_even_armed = True
            stop_limit = 0.0 if self.break_even_armed else -float(self.p.stop_loss_pct)
            if pnl_pct <= stop_limit:
                if self.position.size > 0:
                    self.sell_count += 1
                else:
                    self.cover_count += 1
                self.stop_exit_count += 1
                self.pending_order = self.close()
                return
            if self.position.size > 0 and bear_signal:
                self.sell_count += 1
                self.reverse_exit_count += 1
                self.pending_order = self.close()
                return
            if self.position.size < 0 and bull_signal:
                self.cover_count += 1
                self.reverse_exit_count += 1
                self.pending_order = self.close()
                return
            if neutral_signal or target_percent <= 0:
                half_target = abs(self.position.size) * 0.5
                if half_target >= 0.01:
                    self.partial_exit_count += 1
                    if self.position.size > 0:
                        self.sell_count += 1
                        self.pending_order = self.sell(size=round(half_target, 2))
                    else:
                        self.cover_count += 1
                        self.pending_order = self.buy(size=round(half_target, 2))
                return
            return

        size = self._get_position_size(target_notional_pct=target_percent)
        if size <= 0:
            return
        if bull_signal:
            self.buy_count += 1
            self.pending_order = self.buy(size=size)
            return
        if bear_signal:
            self.short_count += 1
            self.pending_order = self.sell(size=size)

    def notify_order(self, order):
        """Process order completion to track entry price and clear pending orders.

        Args:
            order: Backtrader order instance.
        """
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if self.position:
                self.entry_price = float(order.executed.price)
                self.break_even_armed = False
            else:
                self.entry_price = None
                self.break_even_armed = False
        self.pending_order = None

    def notify_trade(self, trade):
        """Track closed trade outcomes and win/loss counters.

        Args:
            trade: Backtrader trade instance.
        """
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_001_0002_gold_hmm_trend_following() -> None:
    """Migrated regression test for trend_following/0002_gold_hmm_trend_following."""
    fromdate = datetime.datetime(2024, 1, 1, 0, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    params = dict(
        train_window=252,
        retrain_interval=21,
        vol_window=20,
        n_states=3,
        n_iter=300,
        covariance_type="full",
        random_state=42,
        state_persistence_min=0.7,
        consistency_days=3,
        target_volatility=0.15,
        base_target_percent=0.03,
        max_target_percent=0.10,
        stop_loss_pct=0.03,
        take_profit_pct=0.08,
    )
    frame = prepare_hmm_features(raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000.0)
    cerebro.broker.setcommission(commission=0.0002, margin=0.01, mult=100.0)
    cerebro.adddata(Mt5HMMTrendFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.addstrategy(GoldHMMTrendFollowingStrategy, **{k: v for k, v in params.items() if k in ("stop_loss_pct", "take_profit_pct")})
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 245
    assert strat.buy_count == 1
    assert strat.sell_count == 5
    assert strat.win_count == 3
    assert strat.loss_count == 3
    assert strat.trade_count == 6
    assert total_trades == 6
    assert abs(final_value - 1001059.99) < 1.0
    assert (strat.buy_count + strat.sell_count + strat.short_count) > 0, "must have non-zero activity"
