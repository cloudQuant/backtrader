"""Inlined regression test for others/0029_sentiment_analysis.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_1d.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None):
    """Load MT5 CSV data and return a normalized OHLCV DataFrame."""
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


def prepare_sentiment_analysis_features(df, params):
    """Compute sentiment-derived indicators and breakout signals for trading."""
    sentiment_window = int(params.get("sentiment_window", 30))
    return_z_window = int(params.get("return_z_window", 20))
    volume_window = int(params.get("volume_window", 30))
    safe_haven_weight = float(params.get("safe_haven_weight", 1.0))
    speculative_weight = float(params.get("speculative_weight", 0.6))
    dollar_weight = float(params.get("dollar_weight", -0.5))
    extreme_z = float(params.get("extreme_z", 2.0))

    out = df.copy()
    out["returns"] = out["close"].pct_change()
    return_mean = out["returns"].rolling(return_z_window).mean()
    return_std = out["returns"].rolling(return_z_window).std().replace(0, np.nan)
    out["return_z"] = (out["returns"] - return_mean) / return_std

    volume_mean = out["volume"].rolling(volume_window).mean()
    volume_std = out["volume"].rolling(volume_window).std().replace(0, np.nan)
    out["volume_z"] = ((out["volume"] - volume_mean) / volume_std).fillna(0.0)

    intraday_range = (out["high"] - out["low"]) / out["close"].replace(0, np.nan)
    range_mean = intraday_range.rolling(return_z_window).mean()
    range_std = intraday_range.rolling(return_z_window).std().replace(0, np.nan)
    out["range_z"] = ((intraday_range - range_mean) / range_std).fillna(0.0)

    out["safe_haven_proxy"] = (-out["return_z"].fillna(0.0)).clip(lower=-3.0, upper=3.0)
    out["speculative_proxy"] = (out["return_z"].fillna(0.0) * out["volume_z"].fillna(0.0)).clip(lower=-3.0, upper=3.0)
    out["dollar_proxy"] = (-out["range_z"].fillna(0.0)).clip(lower=-3.0, upper=3.0)
    out["sentiment_score"] = (
        safe_haven_weight * out["safe_haven_proxy"]
        + speculative_weight * out["speculative_proxy"]
        + dollar_weight * out["dollar_proxy"]
    )

    sentiment_mean = out["sentiment_score"].rolling(sentiment_window).mean()
    sentiment_std = out["sentiment_score"].rolling(sentiment_window).std().replace(0, np.nan)
    out["sentiment_zscore"] = (out["sentiment_score"] - sentiment_mean) / sentiment_std
    out["sentiment_signal"] = 0.0
    out.loc[out["sentiment_zscore"] <= -extreme_z, "sentiment_signal"] = 1.0
    out.loc[out["sentiment_zscore"] >= extreme_z, "sentiment_signal"] = -1.0

    out = out[[
        "open", "high", "low", "close", "volume", "openinterest",
        "returns", "return_z", "volume_z", "range_z",
        "safe_haven_proxy", "speculative_proxy", "dollar_proxy",
        "sentiment_score", "sentiment_zscore", "sentiment_signal",
    ]].copy()
    return out.dropna()


class Mt5SentimentAnalysisFeed(bt.feeds.PandasData):
    """PandasData feed carrying sentiment feature columns for the strategy."""
    lines = (
        "returns", "return_z", "volume_z", "range_z",
        "safe_haven_proxy", "speculative_proxy", "dollar_proxy",
        "sentiment_score", "sentiment_zscore", "sentiment_signal",
    )
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("returns", 6), ("return_z", 7), ("volume_z", 8), ("range_z", 9),
        ("safe_haven_proxy", 10), ("speculative_proxy", 11), ("dollar_proxy", 12),
        ("sentiment_score", 13), ("sentiment_zscore", 14), ("sentiment_signal", 15),
    )


class SentimentAnalysisStrategy(bt.Strategy):
    """Contrarian sentiment strategy with time/condition-based exits and fixed position sizing."""
    params = dict(
        stop_loss=0.03,
        take_profit=0.06,
        max_holding_days=10,
        position_size=0.95,
        strategy_type="contrarian",
        sentiment_window=30,
        return_z_window=20,
        volume_window=30,
        safe_haven_weight=1.0,
        speculative_weight=0.6,
        dollar_weight=-0.5,
        extreme_z=2.0,
        commission_pct=0.0005,
    )

    def __init__(self):
        """Initialize counters, order state, and entry tracking fields."""
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.entry_bar = 0
        self.entry_price = None
        self.target_direction = 0

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, "mult", 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        direction = 1.0 if target_notional_pct >= 0 else -1.0
        size = broker_value * abs(float(target_notional_pct)) / (execution_price * multiplier)
        return direction * round(size, 2)

    def next(self):
        """Run per-bar signal processing and manage entry/exit operations."""
        self.bar_num += 1
        if self.pending_order is not None:
            return

        signal = float(self.data.sentiment_signal[0])
        close = float(self.data.close[0])
        low = float(self.data.low[0])
        high = float(self.data.high[0])

        if self.position:
            holding_days = self.bar_num - self.entry_bar
            if self.target_direction > 0:
                if low <= self.entry_price * (1.0 - float(self.p.stop_loss)):
                    self.sell_count += 1
                    self.pending_order = self.close()
                    return
                if high >= self.entry_price * (1.0 + float(self.p.take_profit)):
                    self.sell_count += 1
                    self.pending_order = self.close()
                    return
            elif self.target_direction < 0:
                if high >= self.entry_price * (1.0 + float(self.p.stop_loss)):
                    self.buy_count += 1
                    self.pending_order = self.close()
                    return
                if low <= self.entry_price * (1.0 - float(self.p.take_profit)):
                    self.buy_count += 1
                    self.pending_order = self.close()
                    return
            if holding_days >= int(self.p.max_holding_days) or (signal != 0 and signal != self.target_direction):
                if self.target_direction > 0:
                    self.sell_count += 1
                else:
                    self.buy_count += 1
                self.pending_order = self.close()
                return
            return

        if signal == 0:
            return

        self.entry_bar = self.bar_num
        self.entry_price = close
        self.target_direction = int(signal)
        target_size = self._get_position_size(target_notional_pct=float(self.p.position_size) * signal)
        if target_size > 0:
            self.buy_count += 1
        else:
            self.sell_count += 1
        self.pending_order = self.order_target_size(target=target_size)

    def notify_order(self, order):
        """Reset pending order state and clear entry context on order completion."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.target_direction = 0

    def notify_trade(self, trade):
        """Update win/loss counters when a trade is closed."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_029_sentiment_analysis() -> None:
    """Migrated regression test for others/0029_sentiment_analysis."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    params = dict(
        sentiment_window=30,
        return_z_window=20,
        volume_window=30,
        safe_haven_weight=1.0,
        speculative_weight=0.6,
        dollar_weight=-0.5,
        extreme_z=2.0,
    )
    frame = prepare_sentiment_analysis_features(raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.adddata(Mt5SentimentAnalysisFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.addstrategy(SentimentAnalysisStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4609
    assert strat.buy_count == 171
    assert strat.sell_count == 172
    assert strat.win_count == 80
    assert strat.loss_count == 91
    assert strat.trade_count == 171
    assert total_trades == 171
    assert abs(final_value - 858007.6012) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
