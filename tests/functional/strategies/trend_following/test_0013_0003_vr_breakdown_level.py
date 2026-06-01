"""Inlined regression test for trend_following/0013_0003_vr_breakdown_level.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import backtrader as bt
from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M5.csv"


class Mt5PandasFeed(bt.feeds.PandasData):
    """PandasData feed mapping matching MT5 exported column ordering."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class VRBreakdownLevelStrategy(bt.Strategy):
    """Volume-reversal breakdown strategy with stop/take-profit bracket handling."""
    params = dict(
        iLots=0.01, iTakeProfit=400, iStopLoss=200,
        iMagicNumber=227, iSlippage=30,
        point=0.01, price_digits=2,
        volume_step=0.01, volume_min=0.01, volume_max=100.0,
    )

    def __init__(self):
        """Initialize lot sizing, level state, and counters for lifecycle tracking."""
        self.lt = 0.0
        self.level_up = 0.0
        self.level_dw = 0.0
        self.buy_stop = None
        self.sell_stop = None
        self.stop_order = None
        self.tp_order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._prepare_lot()

    def _round_price(self, value):
        return round(value, self.p.price_digits)

    def _prepare_lot(self):
        step = self.p.volume_step
        if step > 0:
            self.lt = step * int(self.p.iLots / step)
        if self.lt < self.p.volume_min:
            self.lt = 0.0
        if self.lt > self.p.volume_max:
            self.lt = self.p.volume_max

    def _cancel_entry_orders(self):
        for order in (self.buy_stop, self.sell_stop):
            if order is not None and order.alive():
                self.cancel(order)
        self.buy_stop = None
        self.sell_stop = None

    def _cancel_exit_orders(self):
        for order in (self.stop_order, self.tp_order):
            if order is not None and order.alive():
                self.cancel(order)
        self.stop_order = None
        self.tp_order = None

    def _submit_exit_orders(self):
        if not self.position:
            return
        size = abs(self.position.size)
        open_price = float(self.position.price)
        if self.position.size > 0:
            sl = self._round_price(open_price - self.p.iStopLoss * self.p.point) if self.p.iStopLoss > 0 else None
            tp = self._round_price(open_price + self.p.iTakeProfit * self.p.point) if self.p.iTakeProfit > 0 else None
            if sl is not None:
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=sl)
            if tp is not None:
                self.tp_order = self.sell(size=size, exectype=bt.Order.Limit, price=tp, oco=self.stop_order)
        else:
            sl = self._round_price(open_price + self.p.iStopLoss * self.p.point) if self.p.iStopLoss > 0 else None
            tp = self._round_price(open_price - self.p.iTakeProfit * self.p.point) if self.p.iTakeProfit > 0 else None
            if sl is not None:
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=sl)
            if tp is not None:
                self.tp_order = self.buy(size=size, exectype=bt.Order.Limit, price=tp, oco=self.stop_order)

    def next(self):
        """Place directional stop entries when no position is active and levels are ready."""
        self.bar_num += 1
        if len(self.data) < 2 or self.lt <= 0:
            return
        if self.position:
            return
        self.level_up = float(self.data.high[-1])
        self.level_dw = float(self.data.low[-1])
        self._cancel_entry_orders()
        if self.level_up > 0:
            self.buy_stop = self.buy(size=self.lt, exectype=bt.Order.Stop, price=self.level_up)
        if self.level_dw > 0:
            self.sell_stop = self.sell(size=self.lt, exectype=bt.Order.Stop, price=self.level_dw, oco=self.buy_stop)

    def notify_order(self, order):
        """Update open/close order references and submit exit legs when entries complete."""
        if order.status in (order.Submitted, order.Accepted):
            return
        if order is self.buy_stop:
            if order.status == order.Completed:
                self.buy_count += 1
                self.level_up = 0.0
                if self.sell_stop is not None and self.sell_stop.alive():
                    self.cancel(self.sell_stop)
                self.sell_stop = None
                self.buy_stop = None
                self._submit_exit_orders()
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.buy_stop = None
            return
        if order is self.sell_stop:
            if order.status == order.Completed:
                self.sell_count += 1
                self.level_dw = 0.0
                if self.buy_stop is not None and self.buy_stop.alive():
                    self.cancel(self.buy_stop)
                self.buy_stop = None
                self.sell_stop = None
                self._submit_exit_orders()
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.sell_stop = None
            return
        if order is self.stop_order:
            if order.status == order.Completed:
                self.stop_order = None
                self.tp_order = None
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.stop_order = None
            return
        if order is self.tp_order:
            if order.status == order.Completed:
                self.tp_order = None
                self.stop_order = None
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.tp_order = None

    def notify_trade(self, trade):
        """Track trade outcomes and clear exit orders after position closure."""
        if trade.isopen:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._cancel_exit_orders()


def test_012_0013_0003_vr_breakdown_level() -> None:
    """Migrated regression test for trend_following/0013_0003_vr_breakdown_level."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 5)
    todate = datetime.datetime(2026, 3, 17, 16, 5)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=5)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=5))
    cerebro.addstrategy(VRBreakdownLevelStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 19784
    assert strat.buy_count == 1
    assert strat.sell_count == 0
    assert strat.win_count == 0
    assert strat.loss_count == 0
    assert strat.trade_count == 0
    assert total_trades == 0  # 1 trade still open
    assert abs(final_value - 1000798.35) < 1.0
    # Strategy opens 1 trade that stays open through end of backtest
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
