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


class DeMarkerIndicator(bt.Indicator):
    lines = ('demarker',)
    params = dict(period=14)

    def __init__(self):
        self.addminperiod(int(self.p.period) + 1)
        self._up_moves = []
        self._down_moves = []

    def next(self):
        up_move = max(float(self.data.high[0]) - float(self.data.high[-1]), 0.0)
        down_move = max(float(self.data.low[-1]) - float(self.data.low[0]), 0.0)
        self._up_moves.append(up_move)
        self._down_moves.append(down_move)
        period = int(self.p.period)
        if len(self._up_moves) > period:
            self._up_moves.pop(0)
            self._down_moves.pop(0)
        if len(self._up_moves) < period:
            self.lines.demarker[0] = float('nan')
            return
        up_sum = sum(self._up_moves)
        down_sum = sum(self._down_moves)
        denom = up_sum + down_sum
        self.lines.demarker[0] = 0.5 if denom == 0.0 else up_sum / denom


class ColorZerolagDeMarker(bt.Indicator):
    lines = ('fast', 'slow')
    params = dict(
        smoothing=15,
        factor1=0.05,
        demarker_period1=8,
        factor2=0.10,
        demarker_period2=21,
        factor3=0.16,
        demarker_period3=34,
        factor4=0.26,
        demarker_period4=55,
        factor5=0.43,
        demarker_period5=89,
    )

    def __init__(self):
        periods = [
            int(self.p.demarker_period1),
            int(self.p.demarker_period2),
            int(self.p.demarker_period3),
            int(self.p.demarker_period4),
            int(self.p.demarker_period5),
        ]
        self.addminperiod(3 * max(periods) + 5)
        self.dem1 = DeMarkerIndicator(self.data, period=int(self.p.demarker_period1))
        self.dem2 = DeMarkerIndicator(self.data, period=int(self.p.demarker_period2))
        self.dem3 = DeMarkerIndicator(self.data, period=int(self.p.demarker_period3))
        self.dem4 = DeMarkerIndicator(self.data, period=int(self.p.demarker_period4))
        self.dem5 = DeMarkerIndicator(self.data, period=int(self.p.demarker_period5))
        self.smooth_const = (float(self.p.smoothing) - 1.0) / float(self.p.smoothing)
        self._initialized = False

    def next(self):
        values = [
            float(self.dem1[0]),
            float(self.dem2[0]),
            float(self.dem3[0]),
            float(self.dem4[0]),
            float(self.dem5[0]),
        ]
        if any(not math.isfinite(value) for value in values):
            self.lines.fast[0] = float('nan')
            self.lines.slow[0] = float('nan')
            return
        osc1 = float(self.p.factor1) * values[0]
        osc2 = float(self.p.factor2) * values[1]
        osc3 = float(self.p.factor3) * values[2]
        osc4 = float(self.p.factor4) * values[3]
        osc5 = float(self.p.factor5) * values[4]
        fast_trend = osc1 + osc2 + osc3 + osc4 + osc5
        if not self._initialized:
            slow_trend = fast_trend / float(self.p.smoothing)
            self._initialized = True
        else:
            slow_trend = fast_trend / float(self.p.smoothing) + float(self.lines.slow[-1]) * self.smooth_const
        self.lines.fast[0] = fast_trend
        self.lines.slow[0] = slow_trend


class ColorZerolagDeMarkerStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        risk_percent=0.0,
        point=0.01,
        stop_loss_points=1000,
        take_profit_points=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        smoothing=15,
        factor1=0.05,
        demarker_period1=8,
        factor2=0.10,
        demarker_period2=21,
        factor3=0.16,
        demarker_period3=34,
        factor4=0.26,
        demarker_period4=55,
        factor5=0.43,
        demarker_period5=89,
        signal_bar=1,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[-1]
        self.indicator = ColorZerolagDeMarker(
            self.signal_feed,
            smoothing=self.p.smoothing,
            factor1=self.p.factor1,
            demarker_period1=self.p.demarker_period1,
            factor2=self.p.factor2,
            demarker_period2=self.p.demarker_period2,
            factor3=self.p.factor3,
            demarker_period3=self.p.demarker_period3,
            factor4=self.p.factor4,
            demarker_period4=self.p.demarker_period4,
            factor5=self.p.factor5,
            demarker_period5=self.p.demarker_period5,
        )
        self.bar_num = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.order = None
        self.entry_side = None
        self.pending_entry_direction = 0
        self.pending_reverse_direction = 0
        self.last_signal_dt = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        max_period = max(
            int(self.p.demarker_period1),
            int(self.p.demarker_period2),
            int(self.p.demarker_period3),
            int(self.p.demarker_period4),
            int(self.p.demarker_period5),
        )
        self.warmup = 3 * max_period + int(self.p.signal_bar) + 6

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _round_size(self, size):
        bounded = min(max(size, self.p.lot_min), self.p.lot_max)
        steps = round(bounded / self.p.lot_step)
        return min(max(steps * self.p.lot_step, self.p.lot_min), self.p.lot_max)

    def _position_size(self):
        if self.p.fixed_lot > 0:
            return self._round_size(self.p.fixed_lot)
        stop_distance = self.p.stop_loss_points * self.p.point
        if stop_distance <= 0 or self.p.risk_percent <= 0:
            return self._round_size(self.p.lot_min)
        risk_money = self.broker.getvalue() * (self.p.risk_percent / 100.0)
        raw_size = risk_money / (stop_distance * self.p.contract_multiplier)
        return self._round_size(raw_size)

    def _buffer_value(self, line, signal_bar, previous=False):
        shift = (int(signal_bar) - 1) + (1 if previous else 0)
        if len(line.array) <= shift:
            return None
        value = float(line[-shift] if shift else line[0])
        if not math.isfinite(value):
            return None
        return value

    def _set_entry_risk(self, price, direction):
        stop_distance = self.p.stop_loss_points * self.p.point
        take_distance = self.p.take_profit_points * self.p.point
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price + take_distance if self.p.take_profit_points > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price - take_distance if self.p.take_profit_points > 0 else None

    def _clear_risk(self):
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None

    def _submit_entry(self, direction, reason):
        size = self._position_size()
        if size <= 0:
            return False
        self.pending_entry_direction = direction
        if direction > 0:
            self.entry_side = 'long'
            self.order = self.buy(size=size)
            self.log(f'OPEN LONG size={size:.2f} reason={reason}')
        else:
            self.entry_side = 'short'
            self.order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size:.2f} reason={reason}')
        return True

    def _check_exit_levels(self):
        if not self.position:
            return False
        low = float(self.data0_feed.low[0])
        high = float(self.data0_feed.high[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.pending_reverse_direction = 0
                self.order = self.close()
                self.log(f'CLOSE long protective stop={self.stop_price:.5f}')
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.pending_reverse_direction = 0
                self.order = self.close()
                self.log(f'CLOSE long take_profit={self.take_profit_price:.5f}')
                return True
            return False
        if self.stop_price is not None and high >= self.stop_price:
            self.pending_reverse_direction = 0
            self.order = self.close()
            self.log(f'CLOSE short protective stop={self.stop_price:.5f}')
            return True
        if self.take_profit_price is not None and low <= self.take_profit_price:
            self.pending_reverse_direction = 0
            self.order = self.close()
            self.log(f'CLOSE short take_profit={self.take_profit_price:.5f}')
            return True
        return False

    def next(self):
        self.bar_num += 1
        signal_dt = bt.num2date(self.signal_feed.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        if len(self.signal_feed) < self.warmup:
            return
        if self.order is not None:
            return
        if self.position and self._check_exit_levels():
            return
        fast_now = self._buffer_value(self.indicator.fast, self.p.signal_bar)
        fast_prev = self._buffer_value(self.indicator.fast, self.p.signal_bar, previous=True)
        slow_now = self._buffer_value(self.indicator.slow, self.p.signal_bar)
        slow_prev = self._buffer_value(self.indicator.slow, self.p.signal_bar, previous=True)
        if None in (fast_now, fast_prev, slow_now, slow_prev):
            return
        buy_open = self.p.buy_pos_open and fast_prev > slow_prev and fast_now < slow_now
        sell_open = self.p.sell_pos_open and fast_prev < slow_prev and fast_now > slow_now
        buy_close = self.p.buy_pos_close and sell_open
        sell_close = self.p.sell_pos_close and buy_open
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        if self.position.size > 0:
            if buy_close:
                self.pending_reverse_direction = -1 if sell_open else 0
                self.order = self.close()
                self.log(f'CLOSE long fast_prev={fast_prev:.5f} fast_now={fast_now:.5f} slow_prev={slow_prev:.5f} slow_now={slow_now:.5f}')
            return
        if self.position.size < 0:
            if sell_close:
                self.pending_reverse_direction = 1 if buy_open else 0
                self.order = self.close()
                self.log(f'CLOSE short fast_prev={fast_prev:.5f} fast_now={fast_now:.5f} slow_prev={slow_prev:.5f} slow_now={slow_now:.5f}')
            return
        if buy_open:
            self._submit_entry(1, f'fast_prev={fast_prev:.5f} fast_now={fast_now:.5f} slow_prev={slow_prev:.5f} slow_now={slow_now:.5f}')
            return
        if sell_open:
            self._submit_entry(-1, f'fast_prev={fast_prev:.5f} fast_now={fast_now:.5f} slow_prev={slow_prev:.5f} slow_now={slow_now:.5f}')
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.rejected_order_count += 1
            self.log(f'ORDER FAILED status={order.getstatusname()}')
            self.order = None
            self.pending_entry_direction = 0
            self.pending_reverse_direction = 0
            if not self.position:
                self.entry_side = None
            return
        if order.status != order.Completed:
            return
        self.completed_order_count += 1
        if self.pending_entry_direction == 1 and order.isbuy() and self.position.size > 0:
            self.buy_count += 1
            self.entry_price = order.executed.price
            self._set_entry_risk(self.entry_price, 1)
            self.pending_entry_direction = 0
            self.log(f'ENTRY FILLED LONG price={order.executed.price:.5f} size={order.executed.size:.2f}')
            self.order = None
            return
        if self.pending_entry_direction == -1 and order.issell() and self.position.size < 0:
            self.sell_count += 1
            self.entry_price = order.executed.price
            self._set_entry_risk(self.entry_price, -1)
            self.pending_entry_direction = 0
            self.log(f'ENTRY FILLED SHORT price={order.executed.price:.5f} size={order.executed.size:.2f}')
            self.order = None
            return
        if not self.position:
            self._clear_risk()
            self.log(f'EXIT FILLED price={order.executed.price:.5f} size={order.executed.size:.2f}')
            self.order = None
            self.entry_side = None
            reverse_direction = self.pending_reverse_direction
            self.pending_reverse_direction = 0
            if reverse_direction != 0:
                self._submit_entry(reverse_direction, 'reverse after zerolag cross')
            return
        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self._clear_risk()
            self.entry_side = None
