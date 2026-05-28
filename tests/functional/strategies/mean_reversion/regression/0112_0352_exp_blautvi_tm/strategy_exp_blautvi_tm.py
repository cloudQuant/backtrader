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


class BlauTVI(bt.Indicator):
    lines = ('value', 'color_idx')
    params = dict(xlength1=12, xlength2=12, xlength3=12)

    def __init__(self):
        up_ticks = (self.data.volume + (self.data.close - self.data.open) / 0.01) / 2.0
        dn_ticks = (self.data.volume - (self.data.close - self.data.open) / 0.01) / 2.0
        up_1 = bt.indicators.ExponentialMovingAverage(up_ticks, period=self.p.xlength1)
        dn_1 = bt.indicators.ExponentialMovingAverage(dn_ticks, period=self.p.xlength1)
        up_2 = bt.indicators.ExponentialMovingAverage(up_1, period=self.p.xlength2)
        dn_2 = bt.indicators.ExponentialMovingAverage(dn_1, period=self.p.xlength2)
        raw = 100.0 * (up_2 - dn_2) / (up_2 + dn_2 + 1e-12)
        self.lines.value = bt.indicators.ExponentialMovingAverage(raw, period=self.p.xlength3)
        self.addminperiod(self.p.xlength1 + self.p.xlength2 + self.p.xlength3 + 2)

    def next(self):
        current = float(self.lines.value[0])
        prev = float(self.lines.value[-1]) if len(self) > 1 and math.isfinite(float(self.lines.value[-1])) else current
        color = 2.0
        if current > 0:
            color = 4.0 if current > prev else 3.0
        elif current < 0:
            color = 0.0 if current < prev else 1.0
        self.lines.color_idx[0] = color


class ExpBlauTVITmStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        risk_percent=0.0,
        point_size=0.01,
        stoploss_pips=1000,
        takeprofit_pips=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        time_trade=True,
        start_hour=0,
        start_minute=0,
        end_hour=23,
        end_minute=59,
        xlength1=12,
        xlength2=12,
        xlength3=12,
        signal_bar=1,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.exec_feed = self.datas[0]
        self.signal_feed = self.datas[1]
        self.ind = BlauTVI(self.signal_feed, xlength1=self.p.xlength1, xlength2=self.p.xlength2, xlength3=self.p.xlength3)
        self.order = None
        self.entry_side = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None
        self.buy_count = 0
        self.sell_count = 0

    def log(self, text):
        dt = bt.num2date(self.exec_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _round_size(self, size):
        bounded = min(max(size, self.p.lot_min), self.p.lot_max)
        steps = round(bounded / self.p.lot_step)
        return min(max(steps * self.p.lot_step, self.p.lot_min), self.p.lot_max)

    def _position_size(self):
        if self.p.fixed_lot > 0:
            return self._round_size(self.p.fixed_lot)
        stop_distance = self.p.stoploss_pips * self.p.point_size
        if stop_distance <= 0 or self.p.risk_percent <= 0:
            return self._round_size(self.p.lot_min)
        risk_money = self.broker.getvalue() * (self.p.risk_percent / 100.0)
        raw_size = risk_money / (stop_distance * self.p.contract_multiplier)
        return self._round_size(raw_size)

    def _line_value(self, line, signal_bar, shift_extra=0):
        shift = (int(signal_bar) - 1) + int(shift_extra)
        if len(line.array) <= shift:
            return None
        value = float(line[-shift] if shift else line[0])
        if not math.isfinite(value):
            return None
        return value

    def _within_trade_window(self, dt):
        if not self.p.time_trade:
            return True
        start = self.p.start_hour * 60 + self.p.start_minute
        end = self.p.end_hour * 60 + self.p.end_minute
        current = dt.hour * 60 + dt.minute
        if start <= end:
            return start <= current <= end
        return current >= start or current <= end

    def _set_entry_risk(self, price, direction):
        stop_distance = self.p.stoploss_pips * self.p.point_size
        take_distance = self.p.takeprofit_pips * self.p.point_size
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stoploss_pips > 0 else None
            self.take_profit_price = price + take_distance if self.p.takeprofit_pips > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stoploss_pips > 0 else None
            self.take_profit_price = price - take_distance if self.p.takeprofit_pips > 0 else None

    def _clear_risk(self):
        self.stop_price = None
        self.take_profit_price = None

    def _check_exit_levels(self):
        if not self.position:
            return False
        low = float(self.exec_feed.low[0])
        high = float(self.exec_feed.high[0])
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

    def next(self):
        exec_dt = bt.num2date(self.exec_feed.datetime[0])
        if self.order is not None:
            return
        if self.position and self._check_exit_levels():
            return
        if self.p.time_trade and not self._within_trade_window(exec_dt):
            if self.position:
                self.order = self.close()
                self.log('CLOSE outside trading window')
            return
        signal_dt = bt.num2date(self.signal_feed.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        warmup = self.p.xlength1 + self.p.xlength2 + self.p.xlength3 + self.p.signal_bar + 3
        if len(self.signal_feed) < warmup:
            return
        value_now = self._line_value(self.ind.value, self.p.signal_bar, 0)
        value_prev = self._line_value(self.ind.value, self.p.signal_bar, 1)
        value_prev2 = self._line_value(self.ind.value, self.p.signal_bar, 2)
        if None in (value_now, value_prev, value_prev2):
            return
        buy_open = value_prev < value_prev2 and self.p.buy_pos_open and value_now > value_prev
        sell_close = value_prev < value_prev2 and self.p.sell_pos_close
        sell_open = value_prev > value_prev2 and self.p.sell_pos_open and value_now < value_prev
        buy_close = value_prev > value_prev2 and self.p.buy_pos_close
        if self.position.size > 0 and buy_close:
            self.order = self.close()
            self.log(f'CLOSE long value_now={value_now:.5f} value_prev={value_prev:.5f} value_prev2={value_prev2:.5f}')
            return
        if self.position.size < 0 and sell_close:
            self.order = self.close()
            self.log(f'CLOSE short value_now={value_now:.5f} value_prev={value_prev:.5f} value_prev2={value_prev2:.5f}')
            return
        if self.position:
            return
        size = self._position_size()
        if buy_open:
            self.entry_side = 'long'
            self.order = self.buy(size=size)
            self.log(f'OPEN LONG size={size:.2f} value_now={value_now:.5f} value_prev={value_prev:.5f} value_prev2={value_prev2:.5f}')
        elif sell_open:
            self.entry_side = 'short'
            self.order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size:.2f} value_now={value_now:.5f} value_prev={value_prev:.5f} value_prev2={value_prev2:.5f}')

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
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self._clear_risk()
            self.entry_side = None
