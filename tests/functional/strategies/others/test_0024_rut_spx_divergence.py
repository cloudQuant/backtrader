"""Manual single-file regression test for ``test_0024_rut_spx_divergence``.

Runs with ``runonce=True`` only.

Data Used:
    IWM daily bars from ``tests/datas/mt5_1d_data/IWM_1d.csv`` as execution
    data, with IVV daily bars from ``tests/datas/mt5_1d_data/IVV_1d.csv`` as the
    divergence reference signal.

Strategy Principle:
    When the Russell (IWM) prints consecutive down closes while the S&P proxy
    (IVV) sets near-term new highs, this strategy treats it as a divergence and
    opens a risk-defined long position.

Strategy Logic:
    ``prepare_rut_spx_divergence_features`` calculates consecutive down-streak and
    IVV new-high flags. ``RutSpxDivergenceStrategy`` applies a single-position
    long-only workflow with stop-loss, take-profit, and holding-period exits.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import backtrader as bt
import pandas as pd
from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
TRADE_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "IWM_1d.csv"
SIGNAL_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "IVV_1d.csv"


def prepare_rut_spx_divergence_features(trade_df, signal_df, params):
    """Build divergence features from trade and reference ETFs.

    Args:
        trade_df: Execution ETF DataFrame (IWM) indexed by datetime.
        signal_df: Reference ETF DataFrame (IVV) indexed by datetime.
        params: Strategy parameters for down-day count and new-high windows.

    Returns:
        pandas.DataFrame: Feature-enriched DataFrame including entry signals.
    """
    rut_down_days = int(params.get("rut_down_days", 3))
    spx_new_high_period = int(params.get("spx_new_high_period", 3))
    aligned_index = trade_df.index.intersection(signal_df.index).sort_values()
    trade_df = trade_df.loc[aligned_index][["open", "high", "low", "close", "volume", "openinterest"]].copy()
    signal_close = signal_df.loc[aligned_index, "close"].astype(float)
    trade_close = trade_df["close"].astype(float)

    out = trade_df.copy()
    out["trade_down"] = (trade_close < trade_close.shift(1)).astype(float)
    consecutive_down = pd.Series(0, index=aligned_index, dtype=float)
    streak = 0
    for dt in aligned_index:
        if out.at[dt, "trade_down"] > 0.5:
            streak += 1
        else:
            streak = 0
        consecutive_down.at[dt] = float(streak)
    out["consecutive_down"] = consecutive_down
    out["signal_new_high"] = (signal_close >= signal_close.rolling(spx_new_high_period).max()).astype(float)
    out["entry_signal"] = ((out["consecutive_down"] >= rut_down_days) & (out["signal_new_high"] > 0.5)).astype(float)
    return out.dropna()


class RutSpxDivergenceFeed(bt.feeds.PandasData):
    """PandasData extension exposing divergence streak and entry flags."""
    lines = ("trade_down", "consecutive_down", "signal_new_high", "entry_signal",)
    params = (
        ("datetime", None),
        ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("trade_down", 6), ("consecutive_down", 7), ("signal_new_high", 8), ("entry_signal", 9),
    )


class RutSpxDivergenceStrategy(bt.Strategy):
    """Long-only divergence strategy with fixed risk and holding controls."""
    params = dict(
        holding_days=4,
        position_size=0.95,
        stop_loss=0.03,
        take_profit=0.05,
        rut_down_days=3,
        spx_new_high_period=3,
        commission_pct=0.0005,
    )

    def __init__(self):
        """Initialize trade counters and active-trade risk state."""
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.signal_days = 0
        self.pending_order = None
        self.entry_bar = 0
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None

    def next(self):
        """Handle exits and entries based on divergence entry signals."""
        self.bar_num += 1
        if self.pending_order is not None:
            return

        close = float(self.data.close[0])
        low = float(self.data.low[0])
        high = float(self.data.high[0])

        if self.position:
            if self.stop_price is not None and low <= self.stop_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.bar_num - self.entry_bar >= int(self.p.holding_days):
                self.sell_count += 1
                self.pending_order = self.close()
                return
            return

        if float(self.data.entry_signal[0]) > 0.5:
            self.signal_days += 1
            self.buy_count += 1
            self.entry_bar = self.bar_num
            self.entry_price = close
            self.stop_price = close * (1.0 - float(self.p.stop_loss))
            self.take_profit_price = close * (1.0 + float(self.p.take_profit))
            self.pending_order = self.order_target_percent(target=float(self.p.position_size))

    def notify_order(self, order):
        """Clear pending marker and reset position context when flat.

        Args:
            order: Order object transitioning out of active status.
        """
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.stop_price = None
            self.take_profit_price = None

    def notify_trade(self, trade):
        """Update closed-trade counters for win/loss reporting."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_024_rut_spx_divergence() -> None:
    """Migrated regression test for others/0024_rut_spx_divergence."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    trade = load_mt5_csv(TRADE_FILE, fromdate=fromdate, todate=todate)
    signal = load_mt5_csv(SIGNAL_FILE, fromdate=fromdate, todate=todate)
    frame = prepare_rut_spx_divergence_features(trade, signal, params=dict())

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.adddata(RutSpxDivergenceFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="IWM")
    cerebro.addstrategy(RutSpxDivergenceStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4519
    assert strat.buy_count == 22
    assert strat.sell_count == 22
    assert strat.win_count == 14
    assert strat.loss_count == 8
    assert strat.trade_count == 22
    assert total_trades == 22
    assert abs(final_value - 1085700.5488) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
