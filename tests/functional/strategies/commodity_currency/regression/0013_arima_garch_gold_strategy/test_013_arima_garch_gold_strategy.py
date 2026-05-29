"""Inlined regression test for commodity_currency/0013_arima_garch_gold_strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
ARIMA(p,0,q) directional + EWMA volatility (with optional GARCH from `arch`) on XAUUSD.
"""
from __future__ import annotations

import datetime
import io
import warnings
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA

try:
    from arch import arch_model
except Exception:
    arch_model = None

_REPO = Path(__file__).resolve().parents[6]
DATA_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "XAUUSD_1d.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
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


def _fit_best_arima(train_returns, max_ar_order=2, max_ma_order=2):
    best_model = None
    best_order = None
    best_aic = np.inf
    for p in range(max_ar_order + 1):
        for q in range(max_ma_order + 1):
            if p == 0 and q == 0:
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    candidate = ARIMA(train_returns, order=(p, 0, q)).fit()
                if np.isfinite(candidate.aic) and candidate.aic < best_aic:
                    best_aic = float(candidate.aic)
                    best_model = candidate
                    best_order = (p, 0, q)
            except Exception:
                continue
    return best_model, best_order, best_aic


def _forecast_volatility(train_returns, arima_residuals, ewma_vol_span=30):
    fallback_vol = float(train_returns.ewm(span=max(2, int(ewma_vol_span)), adjust=False).std().iloc[-1])
    if not np.isfinite(fallback_vol) or fallback_vol <= 0:
        fallback_vol = float(train_returns.std()) if len(train_returns) > 1 else 0.0
    if arch_model is None or len(arima_residuals) < 50:
        return max(fallback_vol, 1e-8), "ewma"
    try:
        scaled_residuals = arima_residuals.astype(float) * 100.0
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = arch_model(scaled_residuals, mean="Zero", vol="GARCH", p=1, q=1, dist="normal")
            result = model.fit(disp="off", show_warning=False)
            variance = float(result.forecast(horizon=1).variance.iloc[-1, 0])
        vol = (max(variance, 0.0) ** 0.5) / 100.0
        if np.isfinite(vol) and vol > 0:
            return vol, "garch"
    except Exception:
        pass
    return max(fallback_vol, 1e-8), "ewma"


def prepare_arima_garch_features(df, params):
    out = df.copy()
    out["log_return"] = np.log(out["close"] / out["close"].shift(1))
    train_window = int(params.get("train_window", 750))
    max_ar_order = int(params.get("max_ar_order", 2))
    max_ma_order = int(params.get("max_ma_order", 2))
    refit_interval = max(1, int(params.get("refit_interval", 5)))
    forecast_threshold = float(params.get("forecast_threshold", 0.0))
    vol_filter_multiplier = float(params.get("vol_filter_multiplier", 0.25))
    ewma_vol_span = int(params.get("ewma_vol_span", 30))
    target_percent = float(params.get("target_percent", 0.95))

    forecast_returns = np.full(len(out), np.nan, dtype=float)
    forecast_vols = np.full(len(out), np.nan, dtype=float)
    thresholds = np.full(len(out), np.nan, dtype=float)
    signals = np.zeros(len(out), dtype=float)
    ar_orders = np.full(len(out), np.nan, dtype=float)
    ma_orders = np.full(len(out), np.nan, dtype=float)

    fitted_model = None
    fitted_order = None

    for idx in range(train_window, len(out)):
        train_returns = out["log_return"].iloc[idx - train_window:idx].dropna().astype(float)
        if len(train_returns) < max(50, train_window // 2):
            continue
        if fitted_model is None or (idx - train_window) % refit_interval == 0:
            fitted_model, fitted_order, _ = _fit_best_arima(train_returns, max_ar_order, max_ma_order)
        pred_return = 0.0
        residuals = train_returns
        if fitted_model is not None:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    forecast = fitted_model.forecast(steps=1)
                pred_return = float(forecast.iloc[0])
                residuals = pd.Series(np.asarray(fitted_model.resid, dtype=float))
            except Exception:
                pred_return = 0.0
                residuals = train_returns
        pred_vol, _ = _forecast_volatility(train_returns, residuals, ewma_vol_span=ewma_vol_span)
        threshold = max(abs(forecast_threshold), vol_filter_multiplier * pred_vol)
        signal = 1.0 if pred_return > threshold else (-1.0 if pred_return < -threshold else 0.0)

        forecast_returns[idx] = pred_return
        forecast_vols[idx] = pred_vol
        thresholds[idx] = threshold
        signals[idx] = signal
        if fitted_order is not None:
            ar_orders[idx] = float(fitted_order[0])
            ma_orders[idx] = float(fitted_order[2])

    out["forecast_return"] = forecast_returns
    out["forecast_vol"] = forecast_vols
    out["signal_threshold"] = thresholds
    out["signal"] = signals
    out["target_pct"] = out["signal"] * target_percent
    out["ar_order"] = ar_orders
    out["ma_order"] = ma_orders
    out = out[[
        "open", "high", "low", "close", "volume", "openinterest",
        "log_return", "forecast_return", "forecast_vol", "signal_threshold",
        "signal", "target_pct", "ar_order", "ma_order",
    ]].copy()
    return out.dropna(subset=["forecast_return", "forecast_vol", "signal_threshold"])


class Mt5ArimaGarchFeed(bt.feeds.PandasData):
    lines = ("log_return", "forecast_return", "forecast_vol", "signal_threshold", "signal",
             "target_pct", "ar_order", "ma_order")
    params = (
        ("datetime", None),
        ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("log_return", 6), ("forecast_return", 7), ("forecast_vol", 8), ("signal_threshold", 9),
        ("signal", 10), ("target_pct", 11), ("ar_order", 12), ("ma_order", 13),
    )


class ArimaGarchGoldStrategy(bt.Strategy):
    params = dict(
        target_percent=0.95,
    )

    def __init__(self):
        self.bar_num = 0
        self.rebalance_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.long_signal_count = 0
        self.short_signal_count = 0
        self.flat_signal_count = 0
        self.switch_count = 0
        self.pending_order = None
        self.last_target_pct = None

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        if abs(target_notional_pct) <= 0:
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
        return round(size, 2)

    def _current_position_pct(self):
        broker_value = float(self.broker.getvalue())
        if broker_value <= 0:
            return 0.0
        price = float(self.data.close[0])
        if price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, "mult", 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        return float(self.position.size) * price * multiplier / broker_value

    def next(self):
        self.bar_num += 1
        target_pct = float(self.data.target_pct[0])
        signal = int(round(float(self.data.signal[0])))
        if signal > 0:
            self.long_signal_count += 1
        elif signal < 0:
            self.short_signal_count += 1
        else:
            self.flat_signal_count += 1
        if self.pending_order is not None:
            return
        if self.last_target_pct is not None and abs(target_pct - self.last_target_pct) > 1e-9:
            self.switch_count += 1
        self.last_target_pct = target_pct
        current_pct = self._current_position_pct()
        if abs(current_pct - target_pct) < 0.02:
            return
        self.rebalance_count += 1
        target_size = self._get_position_size(target_notional_pct=target_pct)
        self.pending_order = self.order_target_size(target=target_size)
        if target_pct > current_pct:
            self.buy_count += 1
        elif target_pct < current_pct:
            self.sell_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_013_arima_garch_gold_strategy() -> None:
    """Migrated regression test for commodity_currency/0013_arima_garch_gold_strategy."""
    fromdate = datetime.datetime(2023, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    sample_stride = 10
    raw = raw.iloc[::sample_stride].copy()
    params = dict(
        train_window=max(50, 750 // sample_stride),
        max_ar_order=2, max_ma_order=2,
        refit_interval=max(1, 5 // sample_stride),
        forecast_threshold=0.0, vol_filter_multiplier=0.0,
        ewma_vol_span=30, target_percent=0.95,
    )
    frame = prepare_arima_garch_features(raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0002, margin=0.01, mult=100.0,
                                  commtype=bt.CommInfoBase.COMM_PERC, percabs=True, stocklike=False)
    cerebro.adddata(Mt5ArimaGarchFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.addstrategy(ArimaGarchGoldStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} rebalance={strat.rebalance_count} buy={strat.buy_count} "
          f"sell={strat.sell_count} long={strat.long_signal_count} short={strat.short_signal_count} "
          f"flat={strat.flat_signal_count} switch={strat.switch_count} win={strat.win_count} "
          f"loss={strat.loss_count} trade={strat.trade_count} total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 3
    assert strat.rebalance_count == 2
    assert strat.buy_count == 1
    assert strat.sell_count == 1
    assert strat.long_signal_count == 3
    assert strat.short_signal_count == 0
    assert strat.flat_signal_count == 0
    assert strat.trade_count == 0
    assert total_trades == 0
    assert abs(final_value - 1070127.0240) < 1.0
