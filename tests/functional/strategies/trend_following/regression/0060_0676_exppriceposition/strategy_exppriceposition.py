from __future__ import absolute_import, division, print_function, unicode_literals

import io
from typing import Optional

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume']
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class ExpPricePositionStrategy(bt.Strategy):
    params = dict(
        risk_percentage=0.10,
        tp_vs_sl_ratio=3.0,
        money_management_type='fixed',
        trade_lot_size=0.1,
        close_by_opposite_signal=True,
        use_trailing_stop=True,
        trailing_fixed_pips_sl=10,
        point=0.01,
        price_digits=2,
        contract_multiplier=100.0,
        min_stop_pips=38,
        step_fast_period=2,
        step_slow_period=30,
        price_position_smma_period=26,
        price_position_sma_period=20,
        max_bars=360,
        min_lookback=12,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.h1 = self.datas[1]
        self.d1 = self.datas[2]

        median_h1 = (self.h1.high + self.h1.low) / 2.0
        typical_h1 = (self.h1.high + self.h1.low + self.h1.close) / 3.0

        self.media1 = bt.indicators.SmoothedMovingAverage(median_h1, period=self.p.price_position_smma_period)
        self.media2 = bt.indicators.SimpleMovingAverage(median_h1, period=self.p.price_position_sma_period)
        self.mma_fast = bt.indicators.SimpleMovingAverage(typical_h1, period=self.p.step_fast_period)
        self.mma_slow = bt.indicators.SmoothedMovingAverage(median_h1, period=self.p.step_slow_period)

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
        self.pending_reverse = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_h1_len = 0
        self.last_close_dt = None

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _point_value(self):
        return float(self.p.point)

    def _current_dt(self):
        return bt.num2date(self.base.datetime[0])

    def _can_open_after_close(self):
        if self.last_close_dt is None:
            return True
        current_dt = self._current_dt()
        return not (
            current_dt.year == self.last_close_dt.year
            and current_dt.month == self.last_close_dt.month
            and current_dt.day == self.last_close_dt.day
            and current_dt.hour == self.last_close_dt.hour
        )

    def _trade_size(self):
        if str(self.p.money_management_type).lower() != 'dynamic':
            return float(self.p.trade_lot_size)
        equity = float(self.broker.getvalue())
        money_risk = equity * float(self.p.risk_percentage) / 100.0
        lots = money_risk / max(float(self.p.contract_multiplier), 1.0)
        return max(float(self.p.trade_lot_size), round(lots, 2))

    def _risk_distance(self, lots):
        equity = float(self.broker.getvalue())
        money_risk = equity * float(self.p.risk_percentage) / 100.0
        spread_pad = self._point_value() * 2.0
        raw_distance = money_risk / max(lots * float(self.p.contract_multiplier), 1e-9)
        min_distance = float(self.p.min_stop_pips) * self._point_value()
        return max(min_distance, raw_distance + spread_pad)

    def _set_entry_risk(self, side, price, lots):
        distance = self._risk_distance(lots)
        if side == 'buy':
            self.stop_price = self._round(price - distance)
            self.take_profit_price = self._round(price + distance * float(self.p.tp_vs_sl_ratio))
        else:
            self.stop_price = self._round(price + distance)
            self.take_profit_price = self._round(price - distance * float(self.p.tp_vs_sl_ratio))

    def _trail_distance(self):
        stop_distance = float(self.p.trailing_fixed_pips_sl) * self._point_value()
        tp_distance = stop_distance * float(self.p.tp_vs_sl_ratio)
        return stop_distance, tp_distance

    def _manage_open_position(self):
        if not self.position or self.order is not None:
            return
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        close = float(self.base.close[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
            if self.p.use_trailing_stop:
                vts, vtp = self._trail_distance()
                if close - float(self.position.price) > vts:
                    candidate_sl = self._round(close - vts)
                    candidate_tp = self._round(close + vtp)
                    if self.stop_price is None or candidate_sl > float(self.stop_price):
                        self.stop_price = candidate_sl
                        self.take_profit_price = max(float(self.take_profit_price), candidate_tp) if self.take_profit_price is not None else candidate_tp
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return
            if self.p.use_trailing_stop:
                vts, vtp = self._trail_distance()
                if float(self.position.price) - close > vts:
                    candidate_sl = self._round(close + vts)
                    candidate_tp = self._round(close - vtp)
                    if self.stop_price is None or candidate_sl < float(self.stop_price):
                        self.stop_price = candidate_sl
                        self.take_profit_price = min(float(self.take_profit_price), candidate_tp) if self.take_profit_price is not None else candidate_tp

    def _get_recent_cross_direction(self) -> int:
        available = min(int(self.p.max_bars), len(self.h1) - 1)
        if available <= 0:
            return 0
        for i in range(0, available):
            signal = float((self.media1[-i] + self.media2[-i]) / 2.0)
            open_ = float(self.h1.open[-i])
            close_ = float(self.h1.close[-i])
            if open_ <= signal and close_ > signal:
                direction = float(self.h1.low[-i])
                current_close = float(self.h1.close[0])
                return 1 if current_close > direction else -1 if current_close < direction else 0
            if open_ >= signal and close_ < signal:
                direction = float(self.h1.high[-i])
                current_close = float(self.h1.close[0])
                return 1 if current_close > direction else -1 if current_close < direction else 0
        return 0

    def _step_up_down(self) -> int:
        pr = 9
        if len(self.h1) < pr + 2:
            return 0
        ma_values = [float(self.mma_fast[-i]) for i in range(0, pr + 1)]
        slow_values = [float(self.mma_slow[-i]) for i in range(0, pr + 1)]
        ma_hi = ma_values[0]
        ma_lo = ma_values[0]
        ml_hi = 0
        ml_lo = 0
        for idx, value in enumerate(ma_values):
            if value > ma_hi:
                ma_hi = value
                ml_hi = idx
            if value < ma_lo:
                ma_lo = value
                ml_lo = idx
        div0 = ma_values[0] - slow_values[0]
        div1 = ma_values[1] - slow_values[1]
        ups = False
        dns = False
        available = min(int(self.p.max_bars), len(self.h1) - 1)
        for j in range(available - 1, -1, -1):
            fast_j = float(self.mma_fast[-j])
            if ml_hi > ml_lo and fast_j > ma_lo:
                ups = True
                dns = False
            if ml_hi > ml_lo and div0 < div1:
                dns = True
                ups = False
            if ml_hi < ml_lo and fast_j < ma_hi:
                dns = True
                ups = False
            if ml_hi < ml_lo and div0 > div1:
                ups = True
                dns = False
        if ups:
            return 1
        if dns:
            return -1
        return 0

    def _trade_signal(self) -> int:
        if len(self.h1) < max(self.p.step_slow_period, self.p.price_position_smma_period) + self.p.min_lookback:
            return 0
        if len(self.d1) < 2:
            return 0
        price_position = self._get_recent_cross_direction()
        step_ud = self._step_up_down()
        if price_position == 0 or step_ud == 0:
            return 0
        ma_open0 = float(self.mma_fast[0])
        ma_open1 = float(self.mma_fast[-1])
        daily_close1 = float(self.d1.close[-1])
        h_close1 = float(self.h1.close[-1])
        h_close0 = float(self.h1.close[0])
        h_open0 = float(self.h1.open[0])
        h_high0 = float(self.h1.high[0])
        h_low0 = float(self.h1.low[0])
        pwr1 = ((h_close1 - daily_close1) / daily_close1) * 100.0 if daily_close1 else 0.0
        pwr0 = ((h_close0 - daily_close1) / daily_close1) * 100.0 if daily_close1 else 0.0
        if price_position == 1 and step_ud == 1 and h_close0 > h_open0 and h_low0 < ma_open0 and ma_open0 > ma_open1 and pwr0 > pwr1:
            return 1
        if price_position == -1 and step_ud == -1 and h_close0 < h_open0 and h_high0 > ma_open0 and ma_open0 < ma_open1 and pwr0 < pwr1:
            return -1
        return 0

    def _close_profitable_on_step_flip(self):
        if not self.position or self.order is not None:
            return
        if self.p.use_trailing_stop:
            return
        current_pnl = (float(self.base.close[0]) - float(self.position.price)) * float(self.position.size) * float(self.p.contract_multiplier)
        step_ud = self._step_up_down()
        if self.position.size > 0 and step_ud == -1 and current_pnl > 0:
            self.order = self.close()
        elif self.position.size < 0 and step_ud == 1 and current_pnl > 0:
            self.order = self.close()

    def _open_side(self, side: str):
        lots = self._trade_size()
        price = float(self.base.close[0])
        self._set_entry_risk(side, price, lots)
        self.signal_count += 1
        if side == 'buy':
            self.order = self.buy(size=lots)
        else:
            self.order = self.sell(size=lots)

    def next(self):
        self.bar_num += 1
        self._manage_open_position()
        self._close_profitable_on_step_flip()
        if len(self.h1) == self.last_h1_len:
            return
        self.last_h1_len = len(self.h1)
        if self.order is not None:
            return
        signal = self._trade_signal()
        if signal == 0:
            return
        if self.position:
            if self.position.size > 0 and signal < 0:
                if self.p.close_by_opposite_signal:
                    self.pending_reverse = 'sell'
                    self.order = self.close()
                return
            if self.position.size < 0 and signal > 0:
                if self.p.close_by_opposite_signal:
                    self.pending_reverse = 'buy'
                    self.order = self.close()
                return
            return
        if not self._can_open_after_close():
            return
        if signal > 0:
            self._open_side('buy')
        elif signal < 0:
            self._open_side('sell')

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if order.isbuy() and order.executed.size > 0:
                self.buy_count += 1
            elif order.issell() and order.executed.size < 0:
                self.sell_count += 1
            if not self.position:
                self.last_close_dt = self._current_dt()
                self.stop_price = None
                self.take_profit_price = None
                if self.pending_reverse is not None:
                    side = self.pending_reverse
                    self.pending_reverse = None
                    self._open_side(side)
                    return
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
            self.pending_reverse = None
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
