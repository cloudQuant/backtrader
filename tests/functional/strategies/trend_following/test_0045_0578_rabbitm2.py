"""Inlined regression test for trend_following/0045_0578_rabbitm2.

Self-contained single-file test (manually authored). Runs with runonce=True
only and validates the migrated strategy metrics against captured baselines.

Data Used:
- XAUUSD M15 bars from ``tests/datas/XAUUSD_M15.csv`` shifted by 15 minutes.
- Backtest window: 2025-12-03 01:15:00 to 2026-03-10 09:00:00.

Strategy Principle:
RabbitM2 is a trend-following pair of moving-average and momentum filters.
It combines CCI and Williams %R against Donchian channel breaks to switch
between buy/sell modes, with fixed stop-loss/take-profit exits and staged
position scaling after large unrealized gains.

Strategy Logic:
- Load M15 OHLCV data and create a custom Backtrader PandasData feed.
- Track CCI, two EMAs and Williams %R each bar, close the opposite side
  position when trend/mode changes, and flatten on Donchian breakout rules.
- Enter when momentum filters align with the active mode, then set stop-loss
  and take-profit levels for fixed-lot entries.
- Track order/trade lifecycle and expose counters for buy/sell, wins/losses,
  and completed/rejected orders in assertions.
"""
from __future__ import annotations
import backtrader as bt

import datetime
from pathlib import Path

from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


class Mt5PandasFeed(bt.feeds.PandasData):
    """Backtrader PandasData feed mapping MT5-exported columns by index."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class RabbitM2Strategy(bt.Strategy):
    """Trend-following strategy using CCI/Williams %R filters and Donchian logic."""
    params = dict(
        cci_sell_level=101, cci_buy_level=99, cci_ma_period=14,
        count_bars=100, max_open_positions=1, big_win=1.50,
        volume_step=0.01, wpr_calc_period=50,
        ma_fast_ma_period=40, ma_slow_ma_period=80,
        take_profit=50, stop_loss=50, volume=0.01,
        point=0.01, price_digits=2,
    )

    def __init__(self):
        """Create indicators and initialise strategy state/counters."""
        self.cci = bt.indicators.CommodityChannelIndex(self.data, period=int(self.p.cci_ma_period))
        self.ema_fast = bt.indicators.ExponentialMovingAverage(self.data.close, period=int(self.p.ma_fast_ma_period))
        self.ema_slow = bt.indicators.ExponentialMovingAverage(self.data.close, period=int(self.p.ma_slow_ma_period))
        self.wpr = bt.indicators.WilliamsR(self.data, period=int(self.p.wpr_calc_period))
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
        self.trade_size = float(self.p.volume)
        self.big_win = float(self.p.big_win)
        self.buy_mode = False
        self.sell_mode = False
        self.open_layers = 0

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _unrealized_profit(self):
        if not self.position:
            return 0.0
        mult = getattr(self.broker.getcommissioninfo(self.data).p, "mult", 1.0)
        current = float(self.data.close[0])
        if self.position.size > 0:
            return (current - float(self.position.price)) * abs(float(self.position.size)) * mult
        return (float(self.position.price) - current) * abs(float(self.position.size)) * mult

    def _maybe_step_volume(self):
        if self._unrealized_profit() > self.big_win:
            self.trade_size += float(self.p.volume_step)
            self.big_win *= 2.0

    def _arm(self, direction, price, size):
        sl = float(self.p.stop_loss) * self._point()
        tp = float(self.p.take_profit) * self._point()
        if direction == "buy":
            self.stop_price = self._round(price - sl) if sl > 0 else None
            self.take_profit_price = self._round(price + tp) if tp > 0 else None
            self.signal_count += 1
            self.order = self.buy(size=size)
        else:
            self.stop_price = self._round(price + sl) if sl > 0 else None
            self.take_profit_price = self._round(price - tp) if tp > 0 else None
            self.signal_count += 1
            self.order = self.sell(size=size)

    def _check_exit(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return

    def _donchian_high(self):
        values = list(self.data.high.get(size=int(self.p.count_bars) + 1))
        if len(values) <= 1:
            return None
        return max(values[:-1])

    def _donchian_low(self):
        values = list(self.data.low.get(size=int(self.p.count_bars) + 1))
        if len(values) <= 1:
            return None
        return min(values[:-1])

    def next(self):
        """Advance strategy state, manage exits, and evaluate new entries."""
        self.bar_num += 1
        warmup = max(int(self.p.cci_ma_period), int(self.p.ma_slow_ma_period), int(self.p.wpr_calc_period)) + 5
        if len(self) < warmup:
            return
        if self.order is not None:
            return

        self._check_exit()
        if self.order is not None:
            return

        cci = float(self.cci[0])
        ema_fast = float(self.ema_fast[0])
        ema_slow = float(self.ema_slow[0])
        will = float(self.wpr[0])
        will_lag = float(self.wpr[-1])

        if ema_fast < ema_slow:
            if self.position.size > 0:
                self._maybe_step_volume()
                self.order = self.close()
                self.sell_mode = True
                self.buy_mode = False
                return
            self.sell_mode = True
            self.buy_mode = False
        elif ema_fast > ema_slow:
            if self.position.size < 0:
                self._maybe_step_volume()
                self.order = self.close()
                self.sell_mode = False
                self.buy_mode = True
                return
            self.sell_mode = False
            self.buy_mode = True

        upper = self._donchian_high()
        lower = self._donchian_low()
        price = float(self.data.close[0])
        if self.position.size < 0 and upper is not None and price > upper:
            self._maybe_step_volume()
            self.order = self.close()
            return
        if self.position.size > 0 and lower is not None and price < lower:
            self._maybe_step_volume()
            self.order = self.close()
            return

        max_layers = max(1, int(self.p.max_open_positions))
        if self.open_layers >= max_layers:
            return

        size = float(self.trade_size)
        if will < -20 and will_lag > -20 and will_lag < 0 and self.sell_mode and cci > float(self.p.cci_sell_level):
            if self.position.size <= 0:
                self._arm("sell", price, size)
                return
        if will > -80 and will_lag < -80 and will_lag < 0 and self.buy_mode and cci < float(self.p.cci_buy_level):
            if self.position.size >= 0:
                self._arm("buy", price, size)

    def notify_order(self, order):
        """Process order updates and update execution counters.

        Args:
            order: Backtrader order instance whose status changed.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                self.open_layers += 1
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.stop_price = None
                self.take_profit_price = None
                self.open_layers = 0
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        """Track closed trade outcomes and update win/loss counters.

        Args:
            trade: Backtrader trade instance currently being processed.
        """
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_044_0045_0578_rabbitm2() -> None:
    """Migrated regression test for trend_following/0045_0578_rabbitm2."""
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
    cerebro.addstrategy(RabbitM2Strategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 6050
    assert strat.buy_count == 53
    assert strat.sell_count == 10
    assert strat.win_count == 36
    assert strat.loss_count == 27
    assert strat.trade_count == 63
    assert total_trades == 63
    assert abs(final_value - 1000000.92) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
