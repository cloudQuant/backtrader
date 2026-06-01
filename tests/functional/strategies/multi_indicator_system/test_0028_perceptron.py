"""Inlined regression test for multi_indicator_system/0028_perceptron.

Self-contained single-file test (manually authored). Runs with runonce=True only.

Data Used:
    - Symbol: XAUUSD
    - Source data: tests/datas/XAUUSD_M15.csv
    - Timeframe: M15 bars with 15-minute shift in test.
    - Backtest period: 2025-12-03 01:15:00 to 2026-03-10 09:00:00

Strategy Principle:
    This strategy evaluates five indicator conditions and combines them through
    a lightweight perceptron-style scoring function to determine long/short bias.
    Position management uses fixed stop-loss and take-profit levels.

Strategy Logic:
    1) Load MT5 M15 bars and apply the test date window.
    2) Compute indicator deltas for MA cross, RSI, CCI, momentum and bt.indicators.AO.
    3) Feed signals into a weighted perceptron and generate directional entry orders.
    4) Enforce exit levels each bar and clear order/trade state on callbacks.
    5) Assert migration metrics in the regression test.
"""
from __future__ import annotations
import backtrader as bt

import datetime
from pathlib import Path

import backtrader.feeds as btfeeds
from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


class Mt5PandasFeed(btfeeds.PandasData):
    """Pandas data feed mapping OHLCV fields for Backtrader."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class PerceptronStrategy(bt.Strategy):
    """Multi-indicator perceptron strategy with bounded position sizing and exits."""
    params = dict(
        lots=0.1, stop_loss=100, take_profit=40, point=0.01,
        sin_max=5.0, sin_min=0.0, sin_plus=0.03, sin_minus=0.03,
        ma1=5, ma2=9, rsi_period=14, cci_period=14,
        ma_a=5, iao_period=20,
    )

    def __init__(self):
        """Initialize indicators, weights, and state fields."""
        self.base = self.datas[0]
        self.ma_fast = bt.indicators.SMA(self.base.close, period=self.p.ma1)
        self.ma_slow = bt.indicators.SMA(self.base.close, period=self.p.ma2)
        self.rsi = bt.indicators.RSI(self.base.close, period=self.p.rsi_period)
        self.cci = bt.indicators.CCI(self.base, period=self.p.cci_period)
        self.ao = bt.indicators.AO(self.base)

        # Initialize all weights to 1.0
        for attr in ("nns1ind2", "nns1ind3", "nns1ind4", "nns1ind5",
                     "nns2ind1", "nns2ind3", "nns2ind4", "nns2ind5",
                     "nns3ind1", "nns3ind2", "nns3ind4", "nns3ind5",
                     "nns4ind1", "nns4ind2", "nns4ind3", "nns4ind5",
                     "nns5ind1", "nns5ind2", "nns5ind3", "nns5ind4",
                     "nns1", "nns2", "nns3", "nns4", "nns5"):
            setattr(self, attr, 1.0)

        self.last_trade_type = 0
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_order = None
        self.entry_price = None
        self.stop_price = None
        self.take_price = None
        self._position_was_open = False

    def _ind1(self):
        if self.ma_fast[-2] < self.ma_slow[-1] and self.ma_fast[-1] > self.ma_slow[-1]:
            return 1
        if self.ma_fast[-2] > self.ma_slow[-1] and self.ma_fast[-1] < self.ma_slow[-1]:
            return -1
        return 0

    def _ind2(self):
        if self.rsi[-2] < 30 and self.rsi[-1] > 30:
            return 1
        if self.rsi[-2] > 70 and self.rsi[-1] < 70:
            return -1
        return 0

    def _ind3(self):
        if self.cci[-2] < -100 and self.cci[-1] > -100:
            return 1
        if self.cci[-2] > 100 and self.cci[-1] < 100:
            return -1
        return 0

    def _ind4(self):
        if self.ma_fast[-1] > self.ma_fast[-2]:
            return 1
        if self.ma_fast[-1] < self.ma_fast[-2]:
            return -1
        return 0

    def _ind5(self):
        if self.ao[-1] > self.ao[-2]:
            return 1
        if self.ao[-1] < self.ao[-2]:
            return -1
        return 0

    def _brain(self, ind1_v, ind2_v, ind3_v, ind4_v, ind5_v):
        nn1 = (ind2_v * self.nns1ind2) + (ind3_v * self.nns1ind3) + (ind4_v * self.nns1ind4) + (ind5_v * self.nns1ind5)
        nn2 = (ind1_v * self.nns2ind1) + (ind3_v * self.nns2ind3) + (ind4_v * self.nns2ind4) + (ind5_v * self.nns2ind5)
        nn3 = (ind1_v * self.nns3ind1) + (ind2_v * self.nns3ind2) + (ind4_v * self.nns3ind4) + (ind5_v * self.nns3ind5)
        nn4 = (ind1_v * self.nns4ind1) + (ind2_v * self.nns4ind2) + (ind3_v * self.nns4ind3) + (ind5_v * self.nns4ind5)
        nn5 = (ind1_v * self.nns5ind1) + (ind2_v * self.nns5ind2) + (ind3_v * self.nns5ind3) + (ind4_v * self.nns5ind4)
        return (nn1 * self.nns1) + (nn2 * self.nns2) + (nn3 * self.nns3) + (nn4 * self.nns4) + (nn5 * self.nns5)

    def _set_levels(self, is_long, price):
        stop_distance = float(self.p.stop_loss) * float(self.p.point)
        take_distance = float(self.p.take_profit) * float(self.p.point)
        if is_long:
            self.stop_price = price - stop_distance
            self.take_price = price + take_distance
        else:
            self.stop_price = price + stop_distance
            self.take_price = price - take_distance

    def _check_exit_levels(self):
        if not self.position or self.entry_price is None:
            return False
        close_price = float(self.base.close[0])
        if self.position.size > 0:
            if self.stop_price is not None and close_price <= self.stop_price:
                self.close()
                return True
            if self.take_price is not None and close_price >= self.take_price:
                self.close()
                return True
        if self.position.size < 0:
            if self.stop_price is not None and close_price >= self.stop_price:
                self.close()
                return True
            if self.take_price is not None and close_price <= self.take_price:
                self.close()
                return True
        return False

    def next(self):
        """Run risk checks, compute brain score, and submit entry orders."""
        self.bar_num += 1
        if len(self.base) < max(self.p.ma2 + 3, self.p.rsi_period + 3, self.p.cci_period + 3, 36):
            return
        if self.entry_order is not None:
            return
        if self._check_exit_levels():
            return
        if self.position:
            return
        ind1_v = self._ind1()
        ind2_v = self._ind2()
        ind3_v = self._ind3()
        ind4_v = self._ind4()
        ind5_v = self._ind5()
        brain = self._brain(ind1_v, ind2_v, ind3_v, ind4_v, ind5_v)
        close_price = float(self.base.close[0])
        size = abs(float(self.p.lots))
        if size <= 0:
            return
        if brain > 0 and self.last_trade_type != 2:
            self.signal_count += 1
            self._set_levels(True, close_price)
            self.entry_order = self.buy(size=size)
            self.last_trade_type = 2
            return
        if brain < 0 and self.last_trade_type != 1:
            self.signal_count += 1
            self._set_levels(False, close_price)
            self.entry_order = self.sell(size=size)
            self.last_trade_type = 1

    def notify_order(self, order):
        """Record fill outcomes and reset active entry tracking."""
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.position:
                self.entry_price = float(order.executed.price)
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.entry_price = None
                self.stop_price = None
                self.take_price = None
        if self.entry_order is not None and order.ref == self.entry_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        """Track closed trade outcomes and reset open-position marker."""
        if trade.isopen and not self._position_was_open:
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False


def test_027_0028_perceptron() -> None:
    """Migrated regression test for multi_indicator_system/0028_perceptron."""
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
    cerebro.addstrategy(PerceptronStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 6096
    assert strat.buy_count == 457
    assert strat.sell_count == 457
    assert strat.win_count == 474
    assert strat.loss_count == 440
    assert strat.trade_count == 914
    assert total_trades == 914
    assert abs(final_value - 999869.6) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
