"""Inlined regression test for mean_reversion/0247_0714_cashmachine_5min.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations
import backtrader as bt

import datetime
from pathlib import Path

from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M5.csv"


class Mt5PandasFeed(bt.feeds.PandasData):
    """Custom PandasData feed for MT5-exported CSV data."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )

class CashMachine5MinStrategy(bt.Strategy):
    """CashMachine 5-minute strategy: uses DeMarker and Stochastic for entry signals with hidden SL/TP."""

    params = dict(
        hidden_take_profit=60.0, hidden_stop_loss=30.0,
        lots=0.2,
        target_tp1=20.0, target_tp2=35.0, target_tp3=50.0,
        demarker_period=14,
        stochastic_kperiod=5, stochastic_dperiod=3, stochastic_slowing=3,
        point=0.0001, digits_adjust=1, price_digits=5,
    )

    def __init__(self):
        """Initialize the strategy: create DeMarker/Stochastic indicators and set up state tracking counters."""
        self.demarker = bt.indicators.DeMarkerIndicator(self.data, period=self.p.demarker_period)
        self.stochastic = bt.indicators.Stochastic(
            self.data,
            period=self.p.stochastic_kperiod,
            period_dfast=self.p.stochastic_dperiod,
            period_dslow=self.p.stochastic_slowing,
        )
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
        self.take_profit_price = None

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _buy_signal(self):
        return float(self.demarker[0]) > 0.7 and float(self.stochastic.percK[0]) > float(self.stochastic.percD[0])

    def _sell_signal(self):
        return float(self.demarker[0]) < 0.3 and float(self.stochastic.percK[0]) < float(self.stochastic.percD[0])

    def _set_hidden_risk(self, side, price):
        unit = self._unit()
        if side == "buy":
            self.stop_price = round(price - float(self.p.hidden_stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price + float(self.p.hidden_take_profit) * unit, int(self.p.price_digits))
        else:
            self.stop_price = round(price + float(self.p.hidden_stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price - float(self.p.hidden_take_profit) * unit, int(self.p.price_digits))

    def _trail_hidden_levels(self):
        if not self.position:
            return
        unit = self._unit()
        entry = float(self.position.price)
        close = float(self.data.close[0])
        if self.position.size > 0:
            if close >= entry + float(self.p.target_tp3) * unit:
                self.stop_price = max(self.stop_price or -1e18, round(close - (float(self.p.target_tp3) - 13.0) * unit, int(self.p.price_digits)))
            elif close >= entry + float(self.p.target_tp2) * unit:
                self.stop_price = max(self.stop_price or -1e18, round(close - (float(self.p.target_tp2) - 13.0) * unit, int(self.p.price_digits)))
            elif close >= entry + float(self.p.target_tp1) * unit:
                self.stop_price = max(self.stop_price or -1e18, round(close - (float(self.p.target_tp1) - 13.0) * unit, int(self.p.price_digits)))
        else:
            if close <= entry - float(self.p.target_tp3) * unit:
                candidate = round(close + (float(self.p.target_tp3) - 13.0) * unit, int(self.p.price_digits))
                self.stop_price = candidate if self.stop_price is None else min(self.stop_price, candidate)
            elif close <= entry - float(self.p.target_tp2) * unit:
                candidate = round(close + (float(self.p.target_tp2) - 13.0) * unit, int(self.p.price_digits))
                self.stop_price = candidate if self.stop_price is None else min(self.stop_price, candidate)
            elif close <= entry - float(self.p.target_tp1) * unit:
                candidate = round(close + (float(self.p.target_tp1) - 13.0) * unit, int(self.p.price_digits))
                self.stop_price = candidate if self.stop_price is None else min(self.stop_price, candidate)

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        self._trail_hidden_levels()
        if self.position.size > 0:
            if low <= float(self.stop_price):
                self.order = self.close()
                return True
            if high >= float(self.take_profit_price):
                self.order = self.close()
                return True
        else:
            if high >= float(self.stop_price):
                self.order = self.close()
                return True
            if low <= float(self.take_profit_price):
                self.order = self.close()
                return True
        return False

    def next(self):
        """Main loop: check entry signals, manage existing positions with hidden SL/TP."""
        self.bar_num += 1
        if len(self) < 100:
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        if self._buy_signal():
            self.signal_count += 1
            price = float(self.data.close[0])
            self._set_hidden_risk("buy", price)
            self.order = self.buy(size=self.p.lots)
            return
        if self._sell_signal():
            self.signal_count += 1
            price = float(self.data.close[0])
            self._set_hidden_risk("sell", price)
            self.order = self.sell(size=self.p.lots)

    def notify_order(self, order):
        """Order status callback: track completed/rejected orders and clear risk levels on position close."""
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
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        """Trade callback: count win/loss results on closed trades."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_246_0247_0714_cashmachine_5min() -> None:
    """Migrated regression test for mean_reversion/0247_0714_cashmachine_5min."""
    fromdate = datetime.datetime(2026, 2, 1, 0, 0)
    todate = datetime.datetime(2026, 3, 10, 23, 59)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=5)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=5))
    cerebro.addstrategy(CashMachine5MinStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 7333
    assert strat.buy_count == 358
    assert strat.sell_count == 430
    assert strat.win_count == 364
    assert strat.loss_count == 424
    assert strat.trade_count == 788
    assert total_trades == 788
    assert abs(final_value - 997548.4) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
