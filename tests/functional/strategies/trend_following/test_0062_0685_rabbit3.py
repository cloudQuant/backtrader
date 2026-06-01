"""Inlined regression test for trend_following/0062_0685_rabbit3.

Self-contained single-file test (manually authored). Runs with runonce=True
only and validates the migrated strategy output directly against regression
assertions.

Data Used:
- XAUUSD M15 bars from ``tests/datas/XAUUSD_M15.csv`` shifted by 15 minutes.
- Backtest window: 2025-12-03 01:15:00 to 2026-03-10 09:00:00.

Strategy Principle:
Rabbit3 combines CCI and Williams %R momentum filters with a two-MA regime.
It opens and closes layered positions with per-layer stop-loss/take-profit
levels, and scales lot size upward after profitable exits while respecting a
maximum layer constraint.

Strategy Logic:
- Build CCI, fast/slow EMAs, and WPR indicators on M15.
- Track open layers with their entry, stop, and take-profit prices.
- Manage close candidates when risk levels are reached, or open new layers when
  WPR and CCI alignment criteria are satisfied.
- Update counters on completed/rejected orders and closed trades for test checks.
"""
from __future__ import annotations
import backtrader as bt

import datetime
from pathlib import Path

from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


class Mt5PandasFeed(bt.feeds.PandasData):
    """Backtrader PandasData feed mapping MT5-exported OHLCV columns."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class Rabbit3Strategy(bt.Strategy):
    """Multi-layer trend-following strategy using CCI, EMAs, and WPR."""
    params = dict(
        cci_level_sell=80,
        cci_level_buy=-80,
        ma_period_cci=15,
        calc_period_wpr=62,
        ma_period_fast=17,
        ma_period_slow=30,
        highest_count=24,
        max_positions=2,
        profit_level=4.0,
        inp_lot=0.01,
        stoploss=45,
        takeprofit=110,
        point=0.01,
        price_digits=2,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
    )

    def __init__(self):
        """Initialize indicators, layer state, and strategy counters."""
        self.cci = bt.indicators.CommodityChannelIndex(self.data, period=self.p.ma_period_cci)
        self.ema_fast = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.ma_period_fast)
        self.ema_slow = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.ma_period_slow)
        self.wpr = bt.indicators.WilliamsR(self.data, period=self.p.calc_period_wpr)
        self.layers = []
        self.pending_order = None
        self.pending_action = None
        self.ext_lot = float(self.p.inp_lot)
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

    def _pip_size(self):
        digits_adjust = 10 if int(self.p.price_digits) in (3, 5) else 1
        return float(self.p.point) * digits_adjust

    def _lot_check(self, lots):
        step = float(self.p.lot_step)
        volume = round(float(lots), 2)
        volume = step * round(volume / step, 0)
        if volume < float(self.p.lot_min):
            return 0.0
        if volume > float(self.p.lot_max):
            return float(self.p.lot_max)
        return round(volume, 2)

    def _position_side(self):
        if not self.position:
            return None
        return "buy" if self.position.size > 0 else "sell"

    def _layer_stop(self, side, entry_price):
        distance = float(self.p.stoploss) * self._pip_size()
        if side == "buy":
            return round(entry_price - distance, self.p.price_digits)
        return round(entry_price + distance, self.p.price_digits)

    def _layer_take_profit(self, side, entry_price):
        distance = float(self.p.takeprofit) * self._pip_size()
        if side == "buy":
            return round(entry_price + distance, self.p.price_digits)
        return round(entry_price - distance, self.p.price_digits)

    def _submit_open(self, side):
        if self.pending_order is not None:
            return False
        size = self._lot_check(self.ext_lot)
        if size <= 0:
            return False
        self.signal_count += 1
        self.pending_action = {"type": "open", "side": side, "size": size}
        self.pending_order = self.buy(size=size) if side == "buy" else self.sell(size=size)
        return True

    def _submit_close(self, layer_indexes, reason):
        if self.pending_order is not None or not layer_indexes:
            return False
        close_size = sum(self.layers[idx]["size"] for idx in layer_indexes)
        side = self._position_side()
        self.pending_action = {"type": "close_layers", "indexes": sorted(layer_indexes), "reason": reason}
        self.pending_order = self.sell(size=close_size) if side == "buy" else self.buy(size=close_size)
        return True

    def _check_entries(self):
        total = len(self.layers)
        if total >= int(self.p.max_positions):
            return False
        cci_now = float(self.cci[0])
        will_now = float(self.wpr[0])
        will_prev = float(self.wpr[-1])
        if will_now < -80 and will_prev < -80 and cci_now < float(self.p.cci_level_buy):
            return self._submit_open("buy")
        if will_now > -20 and will_prev > -20 and cci_now > float(self.p.cci_level_sell):
            return self._submit_open("sell")
        return False

    def _check_risk(self):
        if not self.layers or self.pending_order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        to_close = []
        reason = None
        for idx, layer in enumerate(self.layers):
            if layer["side"] == "buy":
                stop_hit = low <= layer["stop_price"]
                take_hit = high >= layer["take_profit_price"]
            else:
                stop_hit = high >= layer["stop_price"]
                take_hit = low <= layer["take_profit_price"]
            if stop_hit or take_hit:
                to_close.append(idx)
                if reason is None:
                    reason = "take_profit" if take_hit and not stop_hit else "stop_loss"
        if to_close:
            return self._submit_close(to_close, reason or "risk_exit")
        return False

    def next(self):
        """Advance one bar: check exits, gate entries, and schedule actions."""
        self.bar_num += 1
        warmup = max(self.p.ma_period_slow, self.p.calc_period_wpr, self.p.ma_period_cci) + 3
        if len(self.data) < warmup:
            return
        if self._check_risk():
            return
        if self.pending_order is not None:
            return
        self._check_entries()

    def notify_order(self, order):
        """Handle order completion/rejection and update position layers.

        Args:
            order: Backtrader order instance whose state changed.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        action = self.pending_action if self.pending_order is not None and order.ref == self.pending_order.ref else None
        if order.status == bt.Order.Completed and action is not None:
            self.completed_order_count += 1
            if action["type"] == "open":
                side = action["side"]
                entry_price = float(order.executed.price)
                layer = {
                    "side": side,
                    "size": abs(float(order.executed.size)),
                    "entry_price": entry_price,
                    "stop_price": self._layer_stop(side, entry_price),
                    "take_profit_price": self._layer_take_profit(side, entry_price),
                }
                self.layers.append(layer)
                if side == "buy":
                    self.buy_count += 1
                else:
                    self.sell_count += 1
            elif action["type"] == "close_layers":
                remaining = []
                closed_pnl = 0.0
                fill_price = float(order.executed.price)
                for idx, layer in enumerate(self.layers):
                    if idx in action["indexes"]:
                        if layer["side"] == "buy":
                            closed_pnl += (fill_price - layer["entry_price"]) * layer["size"] * 100.0
                        else:
                            closed_pnl += (layer["entry_price"] - fill_price) * layer["size"] * 100.0
                    else:
                        remaining.append(layer)
                self.layers = remaining
                self.ext_lot = self._lot_check(float(self.p.inp_lot) * 1.6) if closed_pnl > float(self.p.profit_level) else float(self.p.inp_lot)
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.pending_order is not None and order.ref == self.pending_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.pending_order = None
            self.pending_action = None

    def notify_trade(self, trade):
        """Record win/loss counters for each closed trade.

        Args:
            trade: Backtrader trade instance.
        """
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_061_0062_0685_rabbit3() -> None:
    """Migrated regression test for trend_following/0062_0685_rabbit3."""
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
    cerebro.addstrategy(Rabbit3Strategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 6068
    assert strat.buy_count == 125
    assert strat.sell_count == 416
    assert strat.win_count == 258
    assert strat.loss_count == 281
    assert strat.trade_count == 539
    assert total_trades == 539
    assert abs(final_value - 999349.93) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
