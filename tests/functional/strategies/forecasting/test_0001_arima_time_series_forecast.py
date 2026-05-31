"""Inlined regression test for the ARIMA time-series forecast gold strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
ARIMA(1,0,1) directional forecast on XAUUSD daily returns.

Data Used:
    XAUUSD (gold) daily ``D1`` bars loaded from
    ``tests/datas/XAUUSD_1d.csv`` through the MetaTrader-5 style CSV reader.
    The backtest window runs from 2022-01-01 to 2025-12-31. Daily returns are
    computed offline, an ARIMA model produces a one-step return forecast per
    bar, and the derived signal and target-position columns are exposed to the
    engine through a single :class:`Mt5ArimaFeed` data source on the daily
    timeframe.

Strategy Principle:
    Uses an ARIMA(1,0,1) model fitted on a rolling window of daily returns to
    forecast the next day's return. A forecast above the threshold is read as a
    bullish signal warranting a long allocation, otherwise the strategy stays
    flat. The market assumption is that short-term autocorrelation in gold
    returns is exploitable by a linear time-series model, and the model is
    refit periodically to adapt to changing dynamics.

Strategy Logic:
    Feature preparation refits the ARIMA model every ``refit_interval`` bars
    after an initial ``train_window``, storing the forecast, a binary signal
    and a target percentage. ``__init__`` initialises bar, rebalance and signal
    counters. ``next`` reads the target percentage, counts long vs flat
    signals and target switches, and rebalances toward the target notional with
    ``order_target_size`` when current exposure drifts beyond a tolerance.
    ``notify_order`` clears the pending order and ``notify_trade`` tallies
    closed-trade wins and losses. The test asserts bar, signal, trade and
    final-value counts against the captured baseline.
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

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_1d.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    """Load a MetaTrader-5 style CSV export into an OHLCV DataFrame.

    Args:
        filepath: Path to the MT5 CSV/TSV export to read.
        fromdate: Optional inclusive lower bound used to trim the index.
        todate: Optional inclusive upper bound used to trim the index.
        bar_shift_minutes: Minutes to shift the datetime index forward.

    Returns:
        A datetime-indexed DataFrame with open, high, low, close, volume and
        openinterest columns sorted in ascending time order.
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
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_arima_features(df, params):
    """Compute rolling ARIMA return forecasts and derive trading signals.

    Args:
        df: Daily OHLCV DataFrame indexed by datetime.
        params: Mapping providing ``train_window``, ``ar_order``,
            ``diff_order``, ``ma_order``, ``refit_interval``,
            ``forecast_threshold`` and ``target_percent`` values.

    Returns:
        The input frame extended with ``return_1d``, ``forecast_return``,
        ``signal`` and ``target_pct`` columns used by the data feed.
    """
    out = df.copy()
    returns = out["close"].pct_change().fillna(0.0)
    train_window = int(params.get("train_window", 252))
    ar_order = int(params.get("ar_order", 1))
    diff_order = int(params.get("diff_order", 0))
    ma_order = int(params.get("ma_order", 1))
    refit_interval = max(1, int(params.get("refit_interval", 20)))
    forecast_threshold = float(params.get("forecast_threshold", 0.0))
    target_percent = float(params.get("target_percent", 0.95))
    forecasts = np.full(len(out), np.nan, dtype=float)
    selected_order = (ar_order, diff_order, ma_order)
    fitted_model = None
    for idx in range(train_window, len(out)):
        if fitted_model is None or (idx - train_window) % refit_interval == 0:
            train_series = returns.iloc[idx - train_window:idx].reset_index(drop=True)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    fitted_model = ARIMA(train_series, order=selected_order).fit()
            except Exception:
                fitted_model = None
        forecast_value = 0.0
        if fitted_model is not None:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    forecast = fitted_model.forecast(steps=1)
                    forecast_value = float(forecast.iloc[0])
            except Exception:
                forecast_value = 0.0
        forecasts[idx] = forecast_value
    out["return_1d"] = returns.to_numpy()
    out["forecast_return"] = forecasts
    out["signal"] = np.where(np.nan_to_num(out["forecast_return"], nan=0.0) > forecast_threshold, 1.0, 0.0)
    out["target_pct"] = out["signal"] * target_percent
    out = out[["open", "high", "low", "close", "volume", "openinterest",
               "return_1d", "forecast_return", "signal", "target_pct"]].copy()
    return out


class Mt5ArimaFeed(bt.feeds.PandasData):
    """PandasData feed exposing ARIMA forecast columns to the strategy.

    Extends the standard OHLCV lines with ``return_1d``, ``forecast_return``,
    ``signal`` and ``target_pct`` so the strategy can read the precomputed
    forecast outputs directly from the data feed.
    """

    lines = ("return_1d", "forecast_return", "signal", "target_pct",)
    params = (
        ("datetime", None),
        ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("return_1d", 6), ("forecast_return", 7), ("signal", 8), ("target_pct", 9),
    )


class ArimaForecastStrategy(bt.Strategy):
    """ARIMA-based directional strategy with target-position rebalance and trade tracking."""
    params = dict()

    def __init__(self):
        """Initialize counters, target-tracking fields, and order state."""
        self.bar_num = 0
        self.rebalance_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.long_signal_count = 0
        self.flat_signal_count = 0
        self.switch_count = 0
        self.pending_order = None
        self.last_target_pct = None

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
        """Run daily rebalance logic from target_pct and signal columns."""
        self.bar_num += 1
        target_pct = float(self.data.target_pct[0])
        signal = int(round(float(self.data.signal[0])))
        if signal == 1:
            self.long_signal_count += 1
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
        """Clear pending order reference after terminal order status."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        """Update win/loss counts for closed trades."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_001_arima_time_series_forecast() -> None:
    """Migrated regression test for forecasting/0001_arima_time_series_forecast."""
    fromdate = datetime.datetime(2022, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    params = dict(
        train_window=252, ar_order=1, diff_order=0, ma_order=1,
        refit_interval=20, forecast_threshold=0.0, target_percent=0.95,
    )
    frame = prepare_arima_features(raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0002, margin=0.01, mult=100.0,
                                  commtype=bt.CommInfoBase.COMM_PERC, percabs=True, stocklike=False)
    cerebro.adddata(Mt5ArimaFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.addstrategy(ArimaForecastStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} rebalance={strat.rebalance_count} buy={strat.buy_count} "
          f"sell={strat.sell_count} long={strat.long_signal_count} flat={strat.flat_signal_count} "
          f"switch={strat.switch_count} win={strat.win_count} loss={strat.loss_count} "
          f"trade={strat.trade_count} total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 1032
    assert strat.rebalance_count == 6
    assert strat.buy_count == 3
    assert strat.sell_count == 3
    assert strat.long_signal_count == 740
    assert strat.flat_signal_count == 292
    assert strat.switch_count == 5
    assert strat.win_count == 2
    assert strat.loss_count == 0
    assert strat.trade_count == 2
    assert total_trades == 2
    assert abs(final_value - 2151710.0312) < 1.0
