"""Regression test for probabilistic gold-risk regime switching.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Probit risk model on XAUUSD with IEF/GTIP/DXYN macro features.

Data Used:
    XAUUSD, IEF, GTIP, and DXYN daily MT5 exports from
    ``tests/datas/mt5_1d_data`` are loaded and aligned from 2021-01-01 to
    2025-12-31.

Strategy Principle:
    The strategy builds a rolling probit risk model on momentum/volatility/macro
    features to estimate near-term downside-risk probability. Exposure is switched
    between full target and flat depending on that probability threshold.

Strategy Logic:
    ``prepare_probit_risk_data`` generates engineered factors, trains/updates a
    probit model on rolling windows, and derives ``target_signal``/risk
    probabilities. In ``next``, the strategy compares the current target to the
    last target, submits rebalance orders when changed, and records alert/switch
    and trade lifecycle statistics.
"""
from __future__ import annotations

import datetime
import warnings
from pathlib import Path

import backtrader as bt
import numpy as np
import statsmodels.api as sm
from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_DIR = _REPO / "tests" / "datas" / "mt5_1d_data"
ASSET_FILES = {
    "XAUUSD": DATA_DIR / "XAUUSD_1d.csv",
    "IEF": DATA_DIR / "IEF_1d.csv",
    "GTIP": DATA_DIR / "GTIP_1d.csv",
    "DXYN": DATA_DIR / "DXYN_1d.csv",
}

FEATURE_COLUMNS = [
    "volatility_20d",
    "rsi_14",
    "macd_histogram",
    "real_rate_change_20d",
    "dxy_change_20d",
]


def _calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50.0)


def _calculate_macd_histogram(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd - signal_line


def _heuristic_probability(window_frame, current_row):
    score = 0.0
    if float(current_row["volatility_20d"]) > float(window_frame["volatility_20d"].quantile(0.75)):
        score += 0.25
    if float(current_row["rsi_14"]) > 65:
        score += 0.15
    if float(current_row["macd_histogram"]) < 0:
        score += 0.15
    if float(current_row["real_rate_change_20d"]) > float(window_frame["real_rate_change_20d"].quantile(0.75)):
        score += 0.25
    if float(current_row["dxy_change_20d"]) > float(window_frame["dxy_change_20d"].quantile(0.75)):
        score += 0.20
    return min(max(score, 0.0), 0.99)


def prepare_probit_risk_data(asset_frames, params):
    """Prepare aligned risk features and rolling probit model outputs.

    Args:
        asset_frames: Mapping of symbol to OHLCV frame.
        params: Model parameters (windows, thresholds, and refit cadence).

    Returns:
        A tuple of aligned raw frames and the feature frame including risk
        probability and trading target signals.
    """
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    aligned = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}
    signal_df = aligned["XAUUSD"][["open", "high", "low", "close", "volume", "openinterest"]].copy()
    gold_close = aligned["XAUUSD"]["close"]
    dxy_close = aligned["DXYN"]["close"]
    real_rate_proxy = np.log(aligned["IEF"]["close"] / aligned["GTIP"]["close"]).replace([np.inf, -np.inf], np.nan)

    signal_df["gold_return_1d"] = gold_close.pct_change()
    signal_df["volatility_20d"] = signal_df["gold_return_1d"].rolling(20, min_periods=20).std()
    signal_df["rsi_14"] = _calculate_rsi(gold_close, 14)
    signal_df["macd_histogram"] = _calculate_macd_histogram(gold_close)
    signal_df["real_rate_change_20d"] = real_rate_proxy.diff(20)
    signal_df["dxy_change_20d"] = dxy_close.pct_change(20)

    risk_horizon = int(params.get("risk_horizon", 20))
    downside_threshold = float(params.get("downside_threshold", -0.05))
    forward_return = gold_close.shift(-risk_horizon) / gold_close - 1.0
    signal_df["risk_state"] = (forward_return <= downside_threshold).astype(float)
    signal_df["risk_probability"] = np.nan
    signal_df["target_signal"] = 0.0

    model_frame = signal_df.dropna(subset=FEATURE_COLUMNS + ["risk_state"]).copy()
    train_window = int(params.get("train_window", 756))
    refit_interval = max(1, int(params.get("refit_interval", 20)))
    entry_threshold = float(params.get("entry_threshold", 0.35))
    max_risk_threshold = float(params.get("max_risk_threshold", 0.60))

    fitted_model = None
    feature_means = None
    feature_stds = None

    for i in range(train_window, len(model_frame)):
        current_idx = model_frame.index[i]
        train_slice = model_frame.iloc[i - train_window:i].copy()
        if fitted_model is None or (i - train_window) % refit_interval == 0:
            y_train = train_slice["risk_state"]
            X_train = train_slice[FEATURE_COLUMNS]
            feature_means = X_train.mean()
            feature_stds = X_train.std().replace(0, 1.0)
            X_scaled = ((X_train - feature_means) / feature_stds).replace([np.inf, -np.inf], 0.0).fillna(0.0)
            if y_train.nunique() >= 2:
                X_fit = sm.add_constant(X_scaled, has_constant="add")
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        fitted_model = sm.Probit(y_train, X_fit).fit(disp=0)
                except Exception:
                    fitted_model = None
            else:
                fitted_model = None
        current_features = model_frame.loc[current_idx, FEATURE_COLUMNS]
        if fitted_model is not None and feature_means is not None and feature_stds is not None:
            current_scaled = ((current_features - feature_means) / feature_stds).replace([np.inf, -np.inf], 0.0).fillna(0.0)
            X_now = sm.add_constant(current_scaled.to_frame().T, has_constant="add")
            try:
                probability = float(fitted_model.predict(X_now)[0])
            except Exception:
                probability = _heuristic_probability(train_slice, current_features)
        else:
            probability = _heuristic_probability(train_slice, current_features)
        model_frame.at[current_idx, "risk_probability"] = probability
        if probability >= max_risk_threshold:
            model_frame.at[current_idx, "target_signal"] = 0.0
        elif probability <= entry_threshold:
            model_frame.at[current_idx, "target_signal"] = 1.0
        else:
            model_frame.at[current_idx, "target_signal"] = 0.0

    signal_df = signal_df.loc[model_frame.index].copy()
    signal_df["risk_probability"] = model_frame["risk_probability"]
    signal_df["target_signal"] = model_frame["target_signal"]
    signal_df = signal_df.dropna(subset=["risk_probability"]).copy()
    aligned = {name: frame.loc[signal_df.index].copy() for name, frame in aligned.items()}
    return aligned, signal_df


class ProbitRiskSignalFeed(bt.feeds.PandasData):
    """Feed carrying engineered probit risk model factor lines."""
    lines = ("gold_return_1d", "volatility_20d", "rsi_14", "macd_histogram",
             "real_rate_change_20d", "dxy_change_20d", "risk_state", "risk_probability", "target_signal")
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("gold_return_1d", 6), ("volatility_20d", 7), ("rsi_14", 8), ("macd_histogram", 9),
        ("real_rate_change_20d", 10), ("dxy_change_20d", 11), ("risk_state", 12),
        ("risk_probability", 13), ("target_signal", 14),
    )


class ProbitRiskModelingGoldStrategy(bt.Strategy):
    """Probit risk-model strategy that toggles gold exposure by risk regime."""
    params = dict(
        target_percent=0.95,
    )

    def __init__(self):
        """Initialize signal/trade state for regime-driven switching."""
        self.signal = self.datas[0]
        self.gold = self.getdatabyname("XAUUSD")
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.risk_alert_count = 0
        self.switch_count = 0
        self.last_target_signal = 0.0

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _target_size(self, target_signal):
        broker_value = float(self.broker.getvalue())
        price = float(self.gold.close[0])
        if broker_value <= 0 or price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.gold)
        multiplier = float(getattr(comminfo.p, "mult", 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        raw_size = broker_value * float(self.p.target_percent) * float(target_signal) / (price * multiplier)
        return round(raw_size, 2)

    def next(self):
        """Rotate between target and flat when regime signal changes."""
        self.bar_num += 1
        if self.order_refs:
            return
        risk_probability = float(self.signal.risk_probability[0])
        if risk_probability >= 0.60:
            self.risk_alert_count += 1
        target_signal = float(self.signal.target_signal[0])
        if abs(target_signal - self.last_target_signal) < 1e-9:
            return
        current_size = float(self.getposition(self.gold).size)
        target_size = self._target_size(target_signal)
        order = self.order_target_size(data=self.gold, target=target_size)
        self._submit(order)
        if order is not None:
            if target_size > current_size:
                self.buy_count += 1
            elif target_size < current_size:
                self.sell_count += 1
            if self.last_target_signal != 0.0 and target_signal != self.last_target_signal:
                self.switch_count += 1
        self.last_target_signal = target_signal

    def notify_order(self, order):
        """Track active order refs and clear resolved orders."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        """Count wins/losses for each closed trade."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_001_probit_risk_modeling_gold() -> None:
    """Migrated regression test for risk_management/0001_probit_risk_modeling_gold."""
    fromdate = datetime.datetime(2021, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    asset_frames = {sym: load_mt5_csv(p, fromdate=fromdate, todate=todate) for sym, p in ASSET_FILES.items()}
    params = dict(
        train_window=756, refit_interval=20, risk_horizon=20,
        downside_threshold=-0.05, entry_threshold=0.35, max_risk_threshold=0.60,
    )
    aligned, signal_df = prepare_probit_risk_data(asset_frames, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    # XAUUSD as the trade symbol gets percent commission with margin/mult; auxiliary feeds are flat.
    gold_comm = bt.CommInfoBase(commission=0.0002, margin=0.01, mult=100.0,
                                  commtype=bt.CommInfoBase.COMM_PERC, percabs=True, stocklike=False)
    # Add signal feed first as datas[0]; XAUUSD is added separately so the strategy can target it.
    feed_signal = ProbitRiskSignalFeed(dataname=signal_df, timeframe=bt.TimeFrame.Days)
    cerebro.adddata(feed_signal, name="SIGNAL")
    feed_xauusd = bt.feeds.PandasData(
        dataname=aligned["XAUUSD"][["open", "high", "low", "close", "volume", "openinterest"]],
        timeframe=bt.TimeFrame.Days,
    )
    cerebro.adddata(feed_xauusd, name="XAUUSD")
    cerebro.broker.addcommissioninfo(gold_comm, name="XAUUSD")
    cerebro.addstrategy(ProbitRiskModelingGoldStrategy, target_percent=0.95)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"risk_alert={strat.risk_alert_count} switch={strat.switch_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 167
    assert strat.buy_count == 2
    assert strat.sell_count == 1
    assert strat.risk_alert_count == 0
    assert strat.switch_count == 1
    assert strat.win_count == 1
    assert strat.loss_count == 0
    assert strat.trade_count == 1
    assert total_trades == 1
    assert abs(final_value - 1284928.3905) < 1.0
