"""Inlined regression test for others/0031_end_of_month_treasury.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import backtrader as bt
import pandas as pd
from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "IEF_1d.csv"


def prepare_end_of_month_treasury_features(price_df, params):
    """Add month-end countdown and entry/exit signal features for the strategy."""
    entry_days = max(1, int(params.get("entry_days", 3)))
    out = price_df.copy()
    month_period = pd.Series(out.index.to_period("M"), index=out.index)
    reverse_rank = pd.Series(range(len(out)), index=out.index).groupby(month_period).transform(
        lambda x: x.rank(ascending=False, method="first")
    )
    out["trading_days_to_month_end"] = reverse_rank.astype(float)
    out["is_entry_window"] = (reverse_rank <= entry_days).astype(float)
    out["is_month_end"] = (reverse_rank == 1).astype(float)
    out["entry_signal"] = out["is_entry_window"]
    out["exit_signal"] = out["is_month_end"]
    return out


class EndOfMonthTreasuryFeed(bt.feeds.PandasData):
    """PandasData feed with end-of-month calendar features."""
    lines = ("trading_days_to_month_end", "is_entry_window", "is_month_end", "entry_signal", "exit_signal")
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
        ("trading_days_to_month_end", 6), ("is_entry_window", 7),
        ("is_month_end", 8), ("entry_signal", 9), ("exit_signal", 10),
    )


class EndOfMonthTreasuryStrategy(bt.Strategy):
    """Simple monthly-window strategy managing fixed risk exits and close conditions."""
    params = dict(
        position_size=0.95,
        stop_loss=0.02,
        take_profit=0.01,
        entry_days=3,
        commission_pct=0.0005,
    )

    def __init__(self):
        """Initialize trade counters and runtime state for orders and risk management."""
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None

    def next(self):
        """Advance each bar and evaluate entry/exit logic based on month-end signals."""
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
            if float(self.data.exit_signal[0]) > 0.5:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            return

        if float(self.data.entry_signal[0]) > 0.5:
            self.buy_count += 1
            self.pending_order = self.order_target_percent(target=float(self.p.position_size))
            self.entry_price = close
            self.stop_price = close * (1.0 - float(self.p.stop_loss))
            self.take_profit_price = close * (1.0 + float(self.p.take_profit))

    def notify_order(self, order):
        """Clear pending-order state and reset risk context once order lifecycle ends."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.stop_price = None
            self.take_profit_price = None

    def notify_trade(self, trade):
        """Update closed-trade counts and P&L outcome counters."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_031_end_of_month_treasury() -> None:
    """Migrated regression test for others/0031_end_of_month_treasury."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    params = dict(entry_days=3)
    frame = prepare_end_of_month_treasury_features(raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.adddata(EndOfMonthTreasuryFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="IEF")
    cerebro.addstrategy(EndOfMonthTreasuryStrategy)
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
    assert strat.buy_count == 220
    assert strat.sell_count == 220
    assert strat.win_count == 80
    assert strat.loss_count == 139
    assert strat.trade_count == 219
    assert total_trades == 219
    assert abs(final_value - 750316.9896) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
