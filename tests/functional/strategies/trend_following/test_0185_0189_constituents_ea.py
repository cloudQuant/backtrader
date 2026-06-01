"""Inlined regression test for trend_following/0185_0189_constituents_ea.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import backtrader as bt
from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


class Mt5PandasFeed(bt.feeds.PandasData):
    """Pandas feed mapping standard OHLCV columns by positional indices."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class ConstituentsEaStrategy(bt.Strategy):
    """Constituents EA-inspired intraday breakout strategy with timed sessions."""
    params = dict(
        stop_loss_points=0,
        take_profit_points=0,
        lot_or_risk="lot",
        volume_or_risk=1.0,
        start_hour=10,
        search_depth=3,
        order_type="limit",
        point=0.01,
        margin_per_lot=250.0,
        lot_step=0.01,
        lot_min=0.01,
        lot_max=100.0,
    )

    def __init__(self):
        """Initialize strategy state for pending orders, position state, and counters."""
        self.buy_entry_order = None
        self.sell_entry_order = None
        self.close_order = None
        self.entry_side = None
        self.current_stop = None
        self.current_take_profit = None
        self.position_day = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def next(self):
        """Advance one bar, cancel stale entry orders, and evaluate new opens."""
        self.bar_num += 1
        self._cancel_expired_day_orders()

    def _normalize_lot(self, lot):
        step = self.p.lot_step
        lot = step * round(lot / step)
        lot = max(self.p.lot_min, min(self.p.lot_max, lot))
        return round(lot, 2)

    def trade_size(self):
        """Compute position size based on fixed lot or risk-based sizing."""
        if str(self.p.lot_or_risk).lower() == "lot":
            return self._normalize_lot(self.p.volume_or_risk)
        margin = self.p.margin_per_lot
        if margin <= 0:
            return 0.0
        cash = self.broker.getcash()
        lot = cash * (self.p.volume_or_risk / 100.0) / margin
        if lot <= 0:
            return 0.0
        return self._normalize_lot(lot)

    def _session_end(self):
        dt = bt.num2date(self.data.datetime[0])
        return dt.replace(hour=23, minute=59, second=59, microsecond=0)

    def _cancel_expired_day_orders(self):
        if not self._has_pending_entries():
            return
        dt = bt.num2date(self.data.datetime[0])
        if self.position_day is None:
            return
        if dt.date() != self.position_day:
            self._cancel_all_entries("day_expired")

    def _cancel_all_entries(self, reason):
        if self.buy_entry_order is not None:
            self.cancel(self.buy_entry_order)
        if self.sell_entry_order is not None:
            self.cancel(self.sell_entry_order)

    def _has_pending_entries(self):
        return self.buy_entry_order is not None or self.sell_entry_order is not None

    def _close_if_exit_hit(self):
        if not self.position:
            return False
        if self.close_order is not None:
            return False
        low = float(self.data.low[-1])
        high = float(self.data.high[-1])
        if self.position.size > 0:
            if self.current_stop is not None and low <= self.current_stop:
                self.close_order = self.close()
                return True
            if self.current_take_profit is not None and high >= self.current_take_profit:
                self.close_order = self.close()
                return True
        else:
            if self.current_stop is not None and high >= self.current_stop:
                self.close_order = self.close()
                return True
            if self.current_take_profit is not None and low <= self.current_take_profit:
                self.close_order = self.close()
                return True
        return False

    def _search_extremes(self):
        highs = []
        lows = []
        for idx in range(1, self.p.search_depth + 1):
            highs.append(float(self.data.high[-idx]))
            lows.append(float(self.data.low[-idx]))
        return max(highs), min(lows)

    def _place_limit_orders(self, size, price_max, price_low):
        buy_price = price_low
        sell_price = price_max
        buy_stop = buy_price - self.p.stop_loss_points * self.p.point if self.p.stop_loss_points else None
        buy_take = buy_price + self.p.take_profit_points * self.p.point if self.p.take_profit_points else None
        sell_stop = sell_price + self.p.stop_loss_points * self.p.point if self.p.stop_loss_points else None
        sell_take = sell_price - self.p.take_profit_points * self.p.point if self.p.take_profit_points else None
        self.buy_entry_order = self.buy(size=size, exectype=bt.Order.Limit, price=buy_price, valid=self._session_end())
        self.sell_entry_order = self.sell(size=size, exectype=bt.Order.Limit, price=sell_price, valid=self._session_end())
        self.buy_entry_order.ea_stop = buy_stop
        self.buy_entry_order.ea_take = buy_take
        self.sell_entry_order.ea_stop = sell_stop
        self.sell_entry_order.ea_take = sell_take

    def _place_stop_orders(self, size, price_max, price_low):
        buy_price = price_max
        sell_price = price_low
        buy_stop = buy_price - self.p.stop_loss_points * self.p.point if self.p.stop_loss_points else None
        buy_take = buy_price + self.p.take_profit_points * self.p.point if self.p.take_profit_points else None
        sell_stop = sell_price + self.p.stop_loss_points * self.p.point if self.p.stop_loss_points else None
        sell_take = sell_price - self.p.take_profit_points * self.p.point if self.p.take_profit_points else None
        self.buy_entry_order = self.buy(size=size, exectype=bt.Order.Stop, price=buy_price, valid=self._session_end())
        self.sell_entry_order = self.sell(size=size, exectype=bt.Order.Stop, price=sell_price, valid=self._session_end())
        self.buy_entry_order.ea_stop = buy_stop
        self.buy_entry_order.ea_take = buy_take
        self.sell_entry_order.ea_stop = sell_stop
        self.sell_entry_order.ea_take = sell_take

    def next_open(self):
        """Evaluate breakout setup and submit paired entry orders on session open."""
        if len(self.data) <= self.p.search_depth:
            return
        if self.position:
            self._close_if_exit_hit()
            return
        if self._has_pending_entries():
            return

        dt = bt.num2date(self.data.datetime[0])
        if dt.hour != self.p.start_hour:
            return

        size = self.trade_size()
        if size == 0.0:
            return

        price_max, price_low = self._search_extremes()
        self.position_day = dt.date()
        if str(self.p.order_type).lower() == "limit":
            self._place_limit_orders(size, price_max, price_low)
        else:
            self._place_stop_orders(size, price_max, price_low)

    def notify_order(self, order):
        """Handle completed/cancelled orders and track stop/take-profit + active side."""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order is self.buy_entry_order:
                self.entry_side = "long"
                self.buy_count += 1
                self.current_stop = getattr(order, "ea_stop", None)
                self.current_take_profit = getattr(order, "ea_take", None)
                if self.sell_entry_order is not None:
                    self.cancel(self.sell_entry_order)
                self.sell_entry_order = None
                self.buy_entry_order = None
            elif order is self.sell_entry_order:
                self.entry_side = "short"
                self.sell_count += 1
                self.current_stop = getattr(order, "ea_stop", None)
                self.current_take_profit = getattr(order, "ea_take", None)
                if self.buy_entry_order is not None:
                    self.cancel(self.buy_entry_order)
                self.buy_entry_order = None
                self.sell_entry_order = None
            elif order is self.close_order:
                if self.position.size == 0:
                    self.close_order = None
                    self.current_stop = None
                    self.current_take_profit = None
                    self.entry_side = None
                    self.position_day = None
            else:
                # Order completed but doesn't match any tracked - count by side
                if order.isbuy():
                    if self.position.size > 0 and self.entry_side != "long":
                        self.buy_count += 1
                        self.entry_side = "long"
                        self.current_stop = getattr(order, "ea_stop", None)
                        self.current_take_profit = getattr(order, "ea_take", None)
                elif order.issell():
                    if self.position.size < 0 and self.entry_side != "short":
                        self.sell_count += 1
                        self.entry_side = "short"
                        self.current_stop = getattr(order, "ea_stop", None)
                        self.current_take_profit = getattr(order, "ea_take", None)
                if self.position.size == 0:
                    self.entry_side = None
                    self.position_day = None

        if order.status in [order.Canceled, order.Margin, order.Rejected, order.Expired]:
            if order is self.buy_entry_order:
                self.buy_entry_order = None
            elif order is self.sell_entry_order:
                self.sell_entry_order = None
            elif order is self.close_order:
                self.close_order = None

    def notify_trade(self, trade):
        """Accrue trade counters when a trade is closed."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm > 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_184_0185_0189_constituents_ea() -> None:
    """Migrated regression test for trend_following/0185_0189_constituents_ea."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)

    cerebro = bt.Cerebro(stdstats=True, cheat_on_open=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.addstrategy(ConstituentsEaStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 6129
    assert strat.buy_count == 0
    assert strat.sell_count == 1
    assert strat.win_count == 1
    assert strat.loss_count == 0
    assert strat.trade_count == 1
    assert total_trades == 1
    assert abs(final_value - 1001056.0) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
