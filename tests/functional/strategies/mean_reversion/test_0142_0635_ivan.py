"""Inlined regression test for mean_reversion/0142_0635_ivan.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations
import backtrader as bt

import datetime
from pathlib import Path

from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


class Mt5PandasFeed(bt.feeds.PandasData):
    """Backtrader feed mapping MT5 positional columns to OHLCV fields."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class IvanStrategy(bt.Strategy):
    """EA 0635: CCI(100) + CCI(13) + SMMA(36) trailing stop + break-even."""
    params = dict(
        cci100_reverse_level=100.0,
        cci100_global_signal_level=100.0,
        cci13_period=13,
        ma_sl_period=36,
        min_distance_sl=50,
        trailing_step=10,
        break_even=5,
        lots=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        """Initialize indicators and counters for signal/trade state tracking."""
        self.cci100 = bt.indicators.CCI(self.data, period=100)
        self.cci13 = bt.indicators.CCI(self.data, period=self.p.cci13_period)
        self.ma_sl = bt.indicators.SmoothedMovingAverage(self.data.close, period=self.p.ma_sl_period)
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.order = None
        self.stop_price = None
        self.b_global_buy = False
        self.b_global_sell = False
        self.b_close_all = False

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _is_signal(self):
        cci100_0 = float(self.cci100[0])
        cci100_1 = float(self.cci100[-1])
        cci13_0 = float(self.cci13[0])
        rev = float(self.p.cci100_reverse_level)
        glb = float(self.p.cci100_global_signal_level)

        if (cci100_1 > rev and cci100_0 < rev) or (cci100_1 < -rev and cci100_0 > -rev):
            self.b_close_all = True
            self.b_global_buy = False
            self.b_global_sell = False

        if cci100_1 < -glb and cci100_0 > -glb:
            self.b_global_buy = True
            self.b_global_sell = False
        if cci100_1 > glb and cci100_0 < glb:
            self.b_global_sell = True
            self.b_global_buy = False

        if self.b_global_buy and cci13_0 > 0:
            return "buy"
        if self.b_global_sell and cci13_0 < 0:
            return "sell"
        return None

    def _trailing_stop(self):
        if not self.position or self.order is not None:
            return
        sl_ma = float(self.ma_sl[0])
        step = float(self.p.trailing_step) * self._point()
        min_dist = float(self.p.min_distance_sl) * self._point()
        be = float(self.p.break_even) * self._point()
        price = float(self.data.close[0])

        if self.position.size > 0:
            if sl_ma < price - min_dist:
                if self.stop_price is None or sl_ma - step > float(self.stop_price):
                    self.stop_price = self._round(sl_ma)
            if be > 0 and price > self.position.price + be:
                be_sl = self._round(self.position.price + be)
                if self.stop_price is None or be_sl > float(self.stop_price):
                    self.stop_price = be_sl
        elif self.position.size < 0:
            if sl_ma > price + min_dist:
                if self.stop_price is None or sl_ma + step < float(self.stop_price):
                    self.stop_price = self._round(sl_ma)
            if be > 0 and price < self.position.price - be:
                be_sl = self._round(self.position.price - be)
                if self.stop_price is None or be_sl < float(self.stop_price):
                    self.stop_price = be_sl

    def _check_stop(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
        else:
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return

    def next(self):
        """Advance strategy state, maintain trailing stops, and issue entry/exit orders."""
        self.bar_num += 1
        if len(self) < 102:
            return
        if self.order is not None:
            return

        self._trailing_stop()
        self._check_stop()
        if self.order is not None:
            return

        if self.b_close_all and self.position:
            self.order = self.close()
            self.b_close_all = False
            return
        self.b_close_all = False

        if self.position:
            return

        signal = self._is_signal()
        if signal == "buy":
            self.signal_count += 1
            sl_ma = float(self.ma_sl[0])
            price = float(self.data.close[0])
            min_dist = float(self.p.min_distance_sl) * self._point()
            if sl_ma < price - min_dist:
                self.stop_price = self._round(sl_ma)
            else:
                self.stop_price = self._round(price - min_dist)
            self.order = self.buy(size=self.p.lots)
        elif signal == "sell":
            self.signal_count += 1
            sl_ma = float(self.ma_sl[0])
            price = float(self.data.close[0])
            min_dist = float(self.p.min_distance_sl) * self._point()
            if sl_ma > price + min_dist:
                self.stop_price = self._round(sl_ma)
            else:
                self.stop_price = self._round(price + min_dist)
            self.order = self.sell(size=self.p.lots)

    def notify_order(self, order):
        """Track completed and rejected orders, updating counters and stop state."""
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.stop_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        """Increment trade counters after each closed trade."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_141_0142_0635_ivan() -> None:
    """Migrated regression test for mean_reversion/0142_0635_ivan."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.addstrategy(IvanStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 5931
    assert strat.buy_count == 326
    assert strat.sell_count == 842
    assert strat.win_count == 671
    assert strat.loss_count == 497
    assert strat.trade_count == 1168
    assert total_trades == 1168
    assert abs(final_value - 996792.3) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
