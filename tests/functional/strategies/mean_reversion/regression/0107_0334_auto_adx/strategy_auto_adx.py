from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('spread', 6),
    )


class AutoAdxStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        risk_percent=0.0,
        stop_loss_pips=50.0,
        take_profit_pips=50.0,
        trailing_stop_pips=5.0,
        trailing_step_pips=5.0,
        adx_period=14,
        adx_level=30.0,
        reverse=True,
        pip_size=0.01,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.order = None
        self.entry_side = None
        self.stop_price = None
        self.take_profit_price = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.adx = bt.indicators.AverageDirectionalMovementIndex(self.data, period=self.p.adx_period)
        self.di = bt.indicators.DirectionalIndicator(self.data, period=self.p.adx_period)

    def prenext(self):
        self.next()

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _clear_risk(self):
        self.stop_price = None
        self.take_profit_price = None

    def _round_size(self, size):
        bounded = min(max(size, self.p.lot_min), self.p.lot_max)
        steps = round(bounded / self.p.lot_step)
        normalized = steps * self.p.lot_step
        return max(self.p.lot_min, min(normalized, self.p.lot_max))

    def _position_size(self):
        if self.p.fixed_lot > 0:
            return self._round_size(self.p.fixed_lot)
        stop_distance = self.p.stop_loss_pips * self.p.pip_size
        if stop_distance <= 0 or self.p.risk_percent <= 0:
            return self._round_size(self.p.lot_min)
        risk_money = self.broker.getvalue() * (self.p.risk_percent / 100.0)
        raw_size = risk_money / (stop_distance * self.p.contract_multiplier)
        return self._round_size(raw_size)

    def _signal_ready(self):
        return len(self.data) > self.p.adx_period + 2

    def _set_entry_risk(self, price, direction):
        stop_distance = self.p.stop_loss_pips * self.p.pip_size
        take_profit_distance = self.p.take_profit_pips * self.p.pip_size
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stop_loss_pips > 0 else None
            self.take_profit_price = price + take_profit_distance if self.p.take_profit_pips > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stop_loss_pips > 0 else None
            self.take_profit_price = price - take_profit_distance if self.p.take_profit_pips > 0 else None

    def _update_trailing_stop(self):
        if not self.position or self.p.trailing_stop_pips <= 0:
            return
        trailing_stop = self.p.trailing_stop_pips * self.p.pip_size
        trailing_step = self.p.trailing_step_pips * self.p.pip_size
        if self.position.size > 0:
            current_price = float(self.data.high[0])
            if current_price - self.position.price > trailing_stop + trailing_step:
                threshold = current_price - (trailing_stop + trailing_step)
                candidate = current_price - trailing_stop
                if self.stop_price is None or self.stop_price < threshold:
                    self.stop_price = candidate
        else:
            current_price = float(self.data.low[0])
            if self.position.price - current_price > trailing_stop + trailing_step:
                threshold = current_price + trailing_stop + trailing_step
                candidate = current_price + trailing_stop
                if self.stop_price is None or self.stop_price > threshold:
                    self.stop_price = candidate

    def _check_exit_levels(self):
        if not self.position:
            return False
        low = float(self.data.low[0])
        high = float(self.data.high[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                self.log(f'CLOSE long protective stop={self.stop_price:.5f}')
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                self.log(f'CLOSE long take_profit={self.take_profit_price:.5f}')
                return True
            return False
        if self.stop_price is not None and high >= self.stop_price:
            self.order = self.close()
            self.log(f'CLOSE short protective stop={self.stop_price:.5f}')
            return True
        if self.take_profit_price is not None and low <= self.take_profit_price:
            self.order = self.close()
            self.log(f'CLOSE short take_profit={self.take_profit_price:.5f}')
            return True
        return False

    def _reverse_signal(self):
        adx_1 = float(self.adx[0])
        adx_2 = float(self.adx[-1])
        plus_di_1 = float(self.di.plusDI[0])
        minus_di_1 = float(self.di.minusDI[0])
        if not all(math.isfinite(v) for v in [adx_1, adx_2, plus_di_1, minus_di_1]):
            return False
        if self.position.size > 0:
            return plus_di_1 < minus_di_1 or adx_1 < adx_2
        return plus_di_1 > minus_di_1 or adx_1 > adx_2

    def _entry_signal(self):
        adx_1 = float(self.adx[0])
        adx_2 = float(self.adx[-1])
        plus_di_1 = float(self.di.plusDI[0])
        minus_di_1 = float(self.di.minusDI[0])
        if not all(math.isfinite(v) for v in [adx_1, adx_2, plus_di_1, minus_di_1]):
            return 0
        if plus_di_1 > minus_di_1 and adx_1 > self.p.adx_level and adx_1 > adx_2:
            return 1
        if plus_di_1 < minus_di_1 and adx_1 < self.p.adx_level and adx_1 < adx_2:
            return -1
        return 0

    def next(self):
        self.bar_num += 1
        if not self._signal_ready():
            return
        if self.order is not None:
            return
        if abs(self.position.size) > 1e-12:
            self._update_trailing_stop()
            if self._check_exit_levels():
                return
        if self.p.reverse and self.position and self._reverse_signal():
            self.order = self.close()
            self.log('CLOSE reverse signal')
            return
        if self.position:
            return
        signal = self._entry_signal()
        size = self._position_size()
        if signal > 0:
            self.entry_side = 'long'
            self.order = self.buy(size=size)
            self.log(f'OPEN LONG size={size:.2f}')
        elif signal < 0:
            self.entry_side = 'short'
            self.order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size:.2f}')

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if order == self.order and self.entry_side == 'long' and order.isbuy() and self.position.size > 0:
                self.buy_count += 1
                self._set_entry_risk(order.executed.price, 1)
                self.log(f'ENTRY FILLED LONG price={order.executed.price:.5f} size={order.executed.size:.2f}')
            elif order == self.order and self.entry_side == 'short' and order.issell() and self.position.size < 0:
                self.sell_count += 1
                self._set_entry_risk(order.executed.price, -1)
                self.log(f'ENTRY FILLED SHORT price={order.executed.price:.5f} size={order.executed.size:.2f}')
            elif not self.position:
                self._clear_risk()
                self.log(f'EXIT FILLED price={order.executed.price:.5f} size={order.executed.size:.2f}')
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            if order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
                self.log(f'ORDER FAILED status={order.getstatusname()}')
            self.order = None
            if not self.position:
                self.entry_side = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm > 0:
            self.win_count += 1
        elif trade.pnlcomm < 0:
            self.loss_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self._clear_risk()
            self.entry_side = None
