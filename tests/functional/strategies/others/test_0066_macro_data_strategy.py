"""Regression test for macro-proxy signal rotation strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.

Data Used:
    Daily MT5 exports for XAUUSD, IVV, and IEF are loaded from
    ``tests/datas/mt5_1d_data`` and aligned across the same trading dates from
    2008-01-01 to 2025-12-31.

Strategy Principle:
    The strategy builds a macro-style composite signal from growth, interest-rate,
    inflation, dollar, and geopolitical proxy components. It interprets strong
    positive (negative) composite values as long (short) bias.

Strategy Logic:
    ``prepare_macro_proxy_data`` computes rolling z-scoreized macro factors and
    maps signal strength to a target exposure. On a fixed rebalance interval the
    strategy uses ``order_target_percent`` to track the target and updates trade
    counters from order/trade notifications.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
TARGET_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "XAUUSD_1d.csv"
GROWTH_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "IVV_1d.csv"
RATES_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "IEF_1d.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None):
    """Load an MT5 export and return a datetime-indexed OHLCV DataFrame.

    Args:
        filepath: Path to MT5 CSV/TSV file.
        fromdate: Optional inclusive start datetime for slicing.
        todate: Optional inclusive end datetime for slicing.

    Returns:
        OHLCV DataFrame ready for a Backtrader ``PandasData`` feed.
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


def prepare_macro_proxy_data(target_df, growth_df, rates_df, params):
    """Build macro proxy features and target allocation signals.

    Args:
        target_df: Target asset frame.
        growth_df: Equity/pro-growth proxy frame.
        rates_df: Interest-rate proxy frame.
        params: Strategy parameters including signal thresholds and component weights.

    Returns:
        Feature-enhanced DataFrame including z-scored macro signal and target
        position percentage.
    """
    common_index = target_df.index.intersection(growth_df.index).intersection(rates_df.index).sort_values()
    target = target_df.loc[common_index].copy()
    growth = growth_df.loc[common_index].copy()
    rates = rates_df.loc[common_index].copy()

    signal_threshold = float(params.get("signal_threshold", 0.2))
    max_target_percent = float(params.get("max_target_percent", 1.0))
    real_rate_weight = float(params.get("real_rate_weight", 0.4))
    inflation_weight = float(params.get("inflation_weight", 0.3))
    dollar_weight = float(params.get("dollar_weight", 0.2))
    geopolitical_weight = float(params.get("geopolitical_weight", 0.1))

    macro = target[["open", "high", "low", "close", "volume", "openinterest"]].copy()
    macro["growth_trend"] = growth["close"].pct_change(63)
    macro["rates_trend"] = rates["close"].pct_change(63)
    macro["inflation_proxy"] = target["close"].pct_change(126)
    macro["dollar_proxy"] = -(growth["close"] / rates["close"]).pct_change(21)
    macro["geopolitical_proxy"] = target["high"].rolling(21).max() / target["close"].rolling(21).mean() - 1.0

    macro["macro_signal_raw"] = (
        real_rate_weight * macro["rates_trend"]
        + inflation_weight * macro["inflation_proxy"]
        + dollar_weight * macro["dollar_proxy"]
        + geopolitical_weight * macro["geopolitical_proxy"]
    )
    rolling_mean = macro["macro_signal_raw"].rolling(252).mean()
    rolling_std = macro["macro_signal_raw"].rolling(252).std()
    macro["macro_signal"] = (macro["macro_signal_raw"] - rolling_mean) / rolling_std.replace(0, pd.NA)
    macro["macro_signal"] = macro["macro_signal"].clip(lower=-3.0, upper=3.0)
    macro["signal"] = 0.0
    macro.loc[macro["macro_signal"] > signal_threshold, "signal"] = 1.0
    macro.loc[macro["macro_signal"] < -signal_threshold, "signal"] = -1.0
    strength = (macro["macro_signal"].abs() / max(signal_threshold, 1e-6)).clip(upper=2.0) / 2.0
    macro["target_percent"] = strength * max_target_percent * macro["signal"]
    return macro[[
        "open", "high", "low", "close", "volume", "openinterest",
        "growth_trend", "rates_trend", "inflation_proxy", "dollar_proxy", "geopolitical_proxy",
        "macro_signal_raw", "macro_signal", "signal", "target_percent",
    ]].dropna().copy()


class MacroSignalFeed(bt.feeds.PandasData):
    """Backtrader feed that carries macro proxy feature lines."""
    lines = ("growth_trend", "rates_trend", "inflation_proxy", "dollar_proxy", "geopolitical_proxy", "macro_signal_raw", "macro_signal", "signal", "target_percent")
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("growth_trend", 6), ("rates_trend", 7), ("inflation_proxy", 8), ("dollar_proxy", 9),
        ("geopolitical_proxy", 10), ("macro_signal_raw", 11), ("macro_signal", 12), ("signal", 13), ("target_percent", 14),
    )


class MacroDataStrategy(bt.Strategy):
    """Single-asset strategy adapting exposure to macro proxy signal.

    A periodic rebalance keeps portfolio exposure close to the computed target
    percent derived from macro regime conditions.
    """
    params = dict(
        rebalance_days=21,
        signal_threshold=0.2,
        real_rate_weight=0.4,
        inflation_weight=0.3,
        dollar_weight=0.2,
        geopolitical_weight=0.1,
        max_target_percent=1.0,
        commission_pct=0.0005,
    )

    def __init__(self):
        """Initialize counters and pending-order lock."""
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.long_signal_days = 0
        self.short_signal_days = 0
        self.neutral_signal_days = 0

    def _current_exposure(self):
        broker_value = float(self.broker.getvalue())
        price = float(self.data.close[0])
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, "mult", 1.0) or 1.0)
        if broker_value <= 0 or price <= 0 or multiplier <= 0:
            return 0.0
        return float(self.position.size) * price * multiplier / broker_value

    def next(self):
        """Update signal regime counters and rebalance at schedule intervals."""
        self.bar_num += 1
        signal_value = float(self.data.signal[0])
        if signal_value > 0.5:
            self.long_signal_days += 1
        elif signal_value < -0.5:
            self.short_signal_days += 1
        else:
            self.neutral_signal_days += 1
        if self.pending_order is not None:
            return
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_days)) != 0:
            return
        target_percent = float(self.data.target_percent[0])
        current_exposure = self._current_exposure()
        if abs(target_percent - current_exposure) < 0.03:
            return
        if target_percent > current_exposure:
            self.buy_count += 1
        elif target_percent < current_exposure:
            self.sell_count += 1
        self.pending_order = self.order_target_percent(target=target_percent)

    def notify_order(self, order):
        """Reset pending order state when order processing completes."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        """Track completed trade outcomes for regression metrics."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_066_macro_data_strategy() -> None:
    """Migrated regression test for others/0066_macro_data_strategy."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    target = load_mt5_csv(TARGET_FILE, fromdate=fromdate, todate=todate)
    growth = load_mt5_csv(GROWTH_FILE, fromdate=fromdate, todate=todate)
    rates = load_mt5_csv(RATES_FILE, fromdate=fromdate, todate=todate)
    frame = prepare_macro_proxy_data(target, growth, rates, params=dict())

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.adddata(MacroSignalFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.addstrategy(MacroDataStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4131
    assert strat.buy_count == 63
    assert strat.sell_count == 61
    assert strat.win_count == 21
    assert strat.loss_count == 22
    assert strat.trade_count == 43
    assert total_trades == 43
    assert abs(final_value - 1509950.1082) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
