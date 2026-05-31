"""Inlined regression test for machine_learning/0005_random_forest_financial_ratios_strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
RandomForest classifier on synthetic financial ratios for IVV/IWM/IWD/PDP/DBMF.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

_REPO = Path(__file__).resolve().parents[4]
DATA_DIR = _REPO / "tests" / "datas" / "mt5_1d_data"
ASSET_FILES = {
    "ivv": DATA_DIR / "IVV_1d.csv",
    "iwm": DATA_DIR / "IWM_1d.csv",
    "iwd": DATA_DIR / "IWD_1d.csv",
    "pdp": DATA_DIR / "PDP_1d.csv",
    "dbmf": DATA_DIR / "DBMF_1d.csv",
}


def load_mt5_csv(filepath, fromdate=None, todate=None):
    """Load MT5-style market CSV and return sorted OHLCV DataFrame."""
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


def prepare_ml_inputs(asset_map, params):
    """Align asset frames and build rolling feature-label samples."""
    aligned_index = None
    prepared = {}
    for _, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in asset_map.items():
        prepared[symbol] = frame.loc[aligned_index][["open", "high", "low", "close", "volume", "openinterest"]].copy()
    close_df = pd.DataFrame({symbol: frame.loc[aligned_index, "close"] for symbol, frame in asset_map.items()},
                             index=aligned_index)
    features = []
    labels = []
    dates = []
    short_w = int(params.get("feature_window_short", 21))
    mid_w = int(params.get("feature_window_mid", 63))
    long_w = int(params.get("feature_window_long", 126))
    vol_w = int(params.get("vol_window", 20))
    horizon = int(params.get("prediction_horizon", 21))
    benchmark = close_df["ivv"]
    for idx in range(long_w, len(close_df) - horizon):
        date = pd.Timestamp(close_df.index[idx]).tz_localize(None)
        sample_rows = []
        sample_labels = {}
        for symbol in close_df.columns:
            series = close_df[symbol].iloc[: idx + 1].dropna()
            if len(series) <= long_w:
                continue
            daily_ret = series.pct_change().dropna()
            sample_rows.append({
                "date": date,
                "symbol": symbol,
                "debt_to_equity": float(daily_ret.iloc[-short_w:].std() * np.sqrt(252)),
                "roe": float(series.iloc[-1] / series.iloc[-mid_w] - 1.0),
                "gross_margin": float(series.iloc[-1] / series.iloc[-short_w] - 1.0),
                "ev_ebitda": float((series.iloc[-long_w:].mean() / series.iloc[-1]) if series.iloc[-1] != 0 else 0.0),
                "dividend_yield": float((series.iloc[-1] / series.iloc[-1 - horizon] - 1.0) if len(series) > horizon else 0.0),
                "roic": float(series.iloc[-1] / series.iloc[-long_w] - 1.0),
                "debt_to_assets": float(abs(daily_ret.iloc[-vol_w:].mean() / (daily_ret.iloc[-vol_w:].std() + 1e-8))),
                "book_to_price": float(1.0 / max(series.iloc[-1], 1e-8)),
                "accruals": float(daily_ret.iloc[-5:].mean() - daily_ret.iloc[-20:].mean()),
            })
            future_return = float(close_df[symbol].iloc[idx + horizon] / close_df[symbol].iloc[idx] - 1.0)
            benchmark_return = float(benchmark.iloc[idx + horizon] / benchmark.iloc[idx] - 1.0)
            sample_labels[symbol] = int(future_return > benchmark_return)
        if sample_rows:
            feature_df = pd.DataFrame(sample_rows)
            label_ser = pd.Series(sample_labels)
            features.append(feature_df)
            labels.append(label_ser)
            dates.append(date)
    return prepared, features, labels, dates


def build_prediction_lookup(features_list, labels_list, dates, params):
    """Train retrained RandomForest models and generate per-date predictions."""
    train_window = int(params.get("train_window", 252))
    rebalance_step = max(1, int(params.get("rebalance_interval_days", 21)))
    random_state = int(params.get("random_state", 42))
    prediction_lookup = {}
    feature_cols = ["debt_to_equity", "roe", "gross_margin", "ev_ebitda", "dividend_yield",
                     "roic", "debt_to_assets", "book_to_price", "accruals"]
    for idx in range(rebalance_step, len(dates), rebalance_step):
        history_features = []
        history_labels = []
        start = max(0, idx - train_window)
        for j in range(start, idx):
            feature_df = features_list[j].copy()
            label_ser = labels_list[j].copy()
            merged = feature_df.set_index("symbol").join(label_ser.rename("label"), how="inner")
            history_features.append(merged[feature_cols])
            history_labels.append(merged["label"])
        if not history_features:
            continue
        x_train = pd.concat(history_features, axis=0)
        y_train = pd.concat(history_labels, axis=0)
        if y_train.nunique() < 2:
            continue
        scaler = StandardScaler()
        x_scaled = scaler.fit_transform(x_train)
        model = RandomForestClassifier(
            n_estimators=int(params.get("n_estimators", 100)),
            max_depth=int(params.get("max_depth", 4)),
            random_state=random_state,
        )
        model.fit(x_scaled, y_train)
        current_features = features_list[idx].copy().set_index("symbol")
        x_current = scaler.transform(current_features[feature_cols])
        probabilities = model.predict_proba(x_current)[:, 1]
        prediction_lookup[dates[idx]] = pd.DataFrame({
            "symbol": current_features.index.tolist(),
            "probability": probabilities,
        }).sort_values("probability", ascending=False).reset_index(drop=True)
    return prediction_lookup


class RandomForestFinancialRatiosStrategy(bt.Strategy):
    """Portfolio rotation strategy based on RandomForest probability ranking."""
    params = dict(
        top_n=2,
        threshold=0.55,
        rebalance_interval_days=21,
        prediction_lookup=None,
    )

    def __init__(self):
        """Initialize counters and order tracking."""
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
        """Rebalance holdings at configured intervals according to predictions."""
        self.bar_num += 1
        current_dt = pd.Timestamp(bt.num2date(self.datas[0].datetime[0])).tz_localize(None)
        if self.order_refs:
            return
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        prediction = (self.p.prediction_lookup or {}).get(current_dt)
        if prediction is None or prediction.empty:
            return
        selected = prediction[prediction["probability"] >= float(self.p.threshold)].head(max(1, int(self.p.top_n)))["symbol"].tolist()
        if not selected:
            selected = prediction.head(max(1, int(self.p.top_n)))["symbol"].tolist()
        selected = set(selected)
        target_weight = 1.0 / len(selected) if selected else 0.0
        self.rebalance_count += 1
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
        """Track order lifecycle and clear pending references on completion."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        """Update trade result counters when a trade closes."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_005_random_forest_financial_ratios_strategy() -> None:
    """Migrated regression test for machine_learning/0005_random_forest_financial_ratios_strategy."""
    fromdate = datetime.datetime(2025, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    asset_map = {sym: load_mt5_csv(p, fromdate=fromdate, todate=todate) for sym, p in ASSET_FILES.items()}
    params = dict(
        feature_window_short=21, feature_window_mid=63, feature_window_long=126,
        vol_window=20, train_window=252, prediction_horizon=21,
        n_estimators=40, max_depth=4, top_n=2, threshold=0.55,
        rebalance_interval_days=21, random_state=42,
    )
    asset_data, features_list, labels_list, dates = prepare_ml_inputs(asset_map, params)
    prediction_lookup = build_prediction_lookup(features_list, labels_list, dates, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    for sym in ASSET_FILES.keys():
        cerebro.adddata(bt.feeds.PandasData(dataname=asset_data[sym], timeframe=bt.TimeFrame.Days), name=sym)
    cerebro.addstrategy(RandomForestFinancialRatiosStrategy,
                       prediction_lookup=prediction_lookup,
                       top_n=2, threshold=0.55, rebalance_interval_days=21)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"rebalance={strat.rebalance_count} win={strat.win_count} loss={strat.loss_count} "
          f"trade={strat.trade_count} total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 241
    assert strat.buy_count == 10
    assert strat.sell_count == 1
    assert strat.rebalance_count == 4
    assert strat.trade_count == 0
    assert total_trades == 0
    assert abs(final_value - 1027595.0395) < 1.0
