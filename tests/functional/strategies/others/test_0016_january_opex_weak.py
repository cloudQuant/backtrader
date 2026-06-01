"""Inlined regression test for the January OpEx Weak Gold strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.

Data Used:
    XAUUSD daily OHLCV data from ``tests/datas/XAUUSD_1d.csv``.

Strategy Principle:
    The strategy targets an early-January seasonal pattern around option-expiry
    week. It records a January entry on the first trading day, a corresponding
    exit at or before the January third Friday, and optionally scales targets when
    the prior December is negative.

Strategy Logic:
    ``prepare_january_opex_gold_features`` marks ``entry_signal`` and
    ``exit_signal`` dates and stores target allocation percentages. The strategy
    opens long positions on entry signals, applies fixed percentage stop-loss and
    take-profit exits plus time exits on exit signals, and then records
    trade outcomes through callbacks for metric validation.
"""
from __future__ import annotations

import calendar
import datetime
from pathlib import Path

import backtrader as bt
import pandas as pd
from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_1d.csv"


def get_third_friday(year, month):
    """Return the third Friday for a given year and month.

    Args:
        year: Gregorian year integer.
        month: Month number 1-12.

    Returns:
        A pandas ``Timestamp`` for the third Friday date.
    """
    cal = calendar.Calendar()
    fridays = [day for day, weekday in cal.itermonthdays2(year, month) if day != 0 and weekday == 4]
    return pd.Timestamp(year=year, month=month, day=fridays[2])


def prepare_january_opex_gold_features(price_df, params):
    """Generate January OpEx calendar features and signal rows.

    Args:
        price_df: Daily OHLCV DataFrame indexed by datetime.
        params: Strategy parameters controlling target sizing and December filter.

    Returns:
        DataFrame containing signal flags, target percentages, and metadata columns.
    """
    out = price_df.copy()
    require_negative_december = bool(params.get("require_negative_december", False))
    base_target_pct = float(params.get("base_target_pct", 0.20))
    negative_december_multiplier = float(params.get("negative_december_multiplier", 1.2))
    out["entry_signal"] = 0.0
    out["exit_signal"] = 0.0
    out["target_pct"] = 0.0
    out["negative_december"] = 0.0
    out["signal_year"] = 0.0
    index = pd.DatetimeIndex(out.index)
    for year in sorted(index.year.unique()):
        january_data = out[(out.index.year == int(year)) & (out.index.month == 1)]
        if len(january_data) == 0:
            continue
        first_trading_day = january_data.index[0]
        third_friday = get_third_friday(int(year), 1)
        op_ex_candidates = january_data.index[january_data.index <= third_friday]
        if len(op_ex_candidates) == 0:
            continue
        exit_day = op_ex_candidates[-1]
        prev_december = out[(out.index.year == int(year) - 1) & (out.index.month == 12)]
        december_negative = False
        if len(prev_december) >= 2:
            december_negative = float(prev_december["close"].iloc[-1] / prev_december["close"].iloc[0] - 1.0) < 0.0
        if require_negative_december and not december_negative:
            continue
        target_pct = base_target_pct * (negative_december_multiplier if december_negative else 1.0)
        out.loc[first_trading_day, "entry_signal"] = 1.0
        out.loc[first_trading_day, "target_pct"] = target_pct
        out.loc[first_trading_day, "negative_december"] = 1.0 if december_negative else 0.0
        out.loc[first_trading_day, "signal_year"] = float(year)
        out.loc[exit_day, "exit_signal"] = 1.0
        out.loc[exit_day, "signal_year"] = float(year)
    out = out[[
        "open", "high", "low", "close", "volume", "openinterest",
        "entry_signal", "exit_signal", "target_pct", "negative_december", "signal_year",
    ]].copy()
    return out.dropna()


class Mt5JanuaryOpExGoldFeed(bt.feeds.PandasData):
    """PandasData feed exposing January OpEx entry/exit signal lines."""
    lines = ("entry_signal", "exit_signal", "target_pct", "negative_december", "signal_year")
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
        ("entry_signal", 6), ("exit_signal", 7), ("target_pct", 8),
        ("negative_december", 9), ("signal_year", 10),
    )


class JanuaryOpExGoldStrategy(bt.Strategy):
    """Long-only seasonal-opportunity strategy driven by January OpEx signals."""
    params = dict(
        stop_loss_pct=0.03,
        take_profit_pct=0.05,
        require_negative_december=False,
        base_target_pct=0.2,
        negative_december_multiplier=1.2,
    )

    def __init__(self):
        """Initialize strategy counters and execution state."""
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.pending_exit_reason = None
        self.entry_price = None

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
        """Advance trading logic, apply risk exits, and open entries."""
        self.bar_num += 1
        if self.pending_order is not None:
            return
        close_price = float(self.data.close[0])
        if self.position:
            exit_reason = None
            if self.entry_price is not None and close_price <= self.entry_price * (1.0 - float(self.p.stop_loss_pct)):
                exit_reason = "stop_loss"
            elif self.entry_price is not None and close_price >= self.entry_price * (1.0 + float(self.p.take_profit_pct)):
                exit_reason = "take_profit"
            elif float(self.data.exit_signal[0]) > 0.5:
                exit_reason = "time_exit"
            if exit_reason is not None:
                self.sell_count += 1
                self.pending_exit_reason = exit_reason
                self.pending_order = self.close()
            return
        if float(self.data.entry_signal[0]) > 0.5:
            target_pct = float(self.data.target_pct[0])
            size = self._get_position_size(target_notional_pct=target_pct)
            if size > 0:
                self.buy_count += 1
                self.pending_order = self.buy(size=size)

    def notify_order(self, order):
        """Handle order lifecycle and clear pending state on completion or terminal status.

        Args:
            order: The order object whose status changed.
        """
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.entry_price = float(order.executed.price or self.data.close[0])
            elif order.issell():
                self.pending_exit_reason = None
                self.entry_price = None
        if order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected):
            if order.status != order.Completed:
                self.pending_exit_reason = None
            self.pending_order = None

    def notify_trade(self, trade):
        """Record closed-trade statistics by PnL sign.

        Args:
            trade: Closed trade object provided by Backtrader.
        """
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_016_january_opex_weak() -> None:
    """Migrated regression test for others/0016_january_opex_weak."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    params = dict(
        require_negative_december=False,
        base_target_pct=0.20,
        negative_december_multiplier=1.2,
    )
    frame = prepare_january_opex_gold_features(raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0002, margin=0.01, mult=100.0,
                                  commtype=bt.CommInfoBase.COMM_PERC, percabs=True, stocklike=False)
    cerebro.adddata(Mt5JanuaryOpExGoldFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.addstrategy(JanuaryOpExGoldStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4638
    assert strat.buy_count == 18
    assert strat.sell_count == 18
    assert strat.win_count == 13
    assert strat.loss_count == 5
    assert strat.trade_count == 18
    assert total_trades == 18
    assert abs(final_value - 1054639.6375) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
