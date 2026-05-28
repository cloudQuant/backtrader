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


def weighted_price(data, ago=0):
    return (float(data.high[ago]) + float(data.low[ago]) + 2.0 * float(data.close[ago])) / 4.0


def indicator_source_price(data, ago=0):
    if all(hasattr(data, attr) for attr in ("high", "low", "close")):
        return weighted_price(data, ago)
    return float(data[ago])


class KalmanFilterLine(bt.Indicator):
    lines = ('value', 'color')
    params = dict(k=1.0, price_shift_points=0.0)

    def __init__(self):
        self.addminperiod(2)
        self._initialized = False
        self._velocity = 0.0
        self.sqrt100 = math.sqrt(float(self.p.k) / 100.0)
        self.k100 = float(self.p.k) / 100.0

    def next(self):
        source_price = indicator_source_price(self.data, 0)
        if not self._initialized:
            self.lines.value[0] = source_price + float(self.p.price_shift_points)
            self.lines.color[0] = 0
            self._velocity = 0.0
            self._initialized = True
            return
        prev_value = float(self.lines.value[-1]) - float(self.p.price_shift_points)
        distance = source_price - prev_value
        error = prev_value + distance * self.sqrt100
        self._velocity += distance * self.k100
        filtered = error + self._velocity + float(self.p.price_shift_points)
        self.lines.value[0] = filtered
        self.lines.color[0] = 1 if self._velocity > 0 else 0


class KalmanFilterCandleIndicator(bt.Indicator):
    lines = ('k_open', 'k_high', 'k_low', 'k_close', 'color')
    params = dict(k=1.0, point=0.01, price_shift=0)

    def __init__(self):
        price_shift_points = float(self.p.point) * float(self.p.price_shift)
        self.k_open_line = KalmanFilterLine(self.data.open, k=self.p.k, price_shift_points=price_shift_points)
        self.k_high_line = KalmanFilterLine(self.data.high, k=self.p.k, price_shift_points=price_shift_points)
        self.k_low_line = KalmanFilterLine(self.data.low, k=self.p.k, price_shift_points=price_shift_points)
        self.k_close_line = KalmanFilterLine(self.data.close, k=self.p.k, price_shift_points=price_shift_points)
        self.addminperiod(3)

    def next(self):
        o = float(self.k_open_line.value[0])
        h = max(float(self.k_high_line.value[0]), o)
        l = min(float(self.k_low_line.value[0]), o)
        c = float(self.k_close_line.value[0])
        h = max(h, c)
        l = min(l, c)
        self.lines.k_open[0] = o
        self.lines.k_high[0] = h
        self.lines.k_low[0] = l
        self.lines.k_close[0] = c
        if o < c:
            color = 2
        elif o > c:
            color = 0
        else:
            color = 1
        self.lines.color[0] = color


class KalmanFilterCandleStrategy(bt.Strategy):
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
        k=1.0,
        price_shift=0,
        signal_bar=1,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[-1]
        self.indicator = KalmanFilterCandleIndicator(
            self.signal_feed,
            k=self.p.k,
            point=self.p.point,
            price_shift=self.p.price_shift,
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
        self.pending_entry_direction = 0
        self.pending_reverse_direction = 0
        self.entry_side = None
        self.last_signal_dt = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.warmup = int(self.p.signal_bar) + 8

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

    def _color_at(self, shift):
        idx = max(int(shift) - 1, 0)
        if len(self.indicator.color.array) <= idx:
            return None
        return int(float(self.indicator.color[-idx] if idx else self.indicator.color[0]))

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
        current_color = self._color_at(int(self.p.signal_bar))
        previous_color = self._color_at(int(self.p.signal_bar) + 1)
        if current_color is None or previous_color is None:
            return
        buy_open = self.p.buy_pos_open and current_color == 2 and previous_color < 2
        sell_open = self.p.sell_pos_open and current_color == 0 and previous_color > 0
        sell_close = self.p.sell_pos_close and current_color == 2
        buy_close = self.p.buy_pos_close and current_color == 0
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        if self.position.size > 0:
            if buy_close:
                self.pending_reverse_direction = -1 if sell_open else 0
                self.order = self.close()
                self.log('CLOSE long KalmanFilterCandle signal')
            return
        if self.position.size < 0:
            if sell_close:
                self.pending_reverse_direction = 1 if buy_open else 0
                self.order = self.close()
                self.log('CLOSE short KalmanFilterCandle signal')
            return
        if buy_open:
            self._submit_entry(1, 'KalmanFilterCandle bullish color flip')
            return
        if sell_open:
            self._submit_entry(-1, 'KalmanFilterCandle bearish color flip')
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
                self._submit_entry(reverse_direction, 'reverse after KalmanFilterCandle signal')
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
