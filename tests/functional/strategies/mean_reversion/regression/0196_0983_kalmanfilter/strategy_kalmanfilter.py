from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import pandas as pd


APPLIED_PRICE_MAP = {
    'PRICE_CLOSE': 0,
    'PRICE_OPEN': 1,
    'PRICE_HIGH': 2,
    'PRICE_LOW': 3,
    'PRICE_MEDIAN': 4,
    'PRICE_TYPICAL': 5,
    'PRICE_WEIGHTED': 6,
    'PRICE_OPEN_CLOSE': 8,
    'PRICE_OHLC_AVERAGE': 9,
    'PRICE_DEMARK': 10,
    'PRICE_AVERAGE_DEMARK': 11,
}

SIGNAL_MODE_MAP = {
    'Trend': 0,
    'Kalman': 1,
}


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


class KalmanFilterIndicator(bt.Indicator):
    lines = ('value', 'color_idx')
    params = dict(
        k=1.0,
        applied_price='PRICE_WEIGHTED',
        signal_mode='Kalman',
        price_shift=0,
        point=0.01,
    )

    def __init__(self):
        self.addminperiod(2)
        self._velocity = 0.0
        self._sqrt100 = math.sqrt(float(self.p.k) / 100.0) if float(self.p.k) > 0 else 0.0
        self._k100 = float(self.p.k) / 100.0
        self._price_shift = float(self.p.point) * float(self.p.price_shift)

    def _mode_value(self, mapping, value, default_value):
        if isinstance(value, str):
            return mapping.get(value, default_value)
        return int(value)

    def _price(self, ago=0):
        mode = self._mode_value(APPLIED_PRICE_MAP, self.p.applied_price, 0)
        open_ = float(self.data.open[ago])
        high = float(self.data.high[ago])
        low = float(self.data.low[ago])
        close = float(self.data.close[ago])
        if mode == 0:
            return close
        if mode == 1:
            return open_
        if mode == 2:
            return high
        if mode == 3:
            return low
        if mode == 4:
            return (high + low) / 2.0
        if mode == 5:
            return (close + high + low) / 3.0
        if mode == 6:
            return (2.0 * close + high + low) / 4.0
        if mode == 8:
            return (open_ + close) / 2.0
        if mode == 9:
            return (open_ + close + high + low) / 4.0
        if mode == 10:
            if close > open_:
                return high
            if close < open_:
                return low
            return close
        if mode == 11:
            if close > open_:
                return (high + close) / 2.0
            if close < open_:
                return (low + close) / 2.0
            return close
        return close

    def next(self):
        price = self._price(0)
        if len(self) == 1:
            self.lines.value[0] = price
            self.lines.color_idx[0] = 0.0
            self._velocity = 0.0
            return
        prev_value = float(self.lines.value[-1])
        distance = price - prev_value
        error = prev_value + distance * self._sqrt100
        self._velocity += distance * self._k100
        value = error + self._velocity + self._price_shift
        self.lines.value[0] = value
        signal_mode = self._mode_value(SIGNAL_MODE_MAP, self.p.signal_mode, 1)
        if signal_mode == 0:
            self.lines.color_idx[0] = 0.0 if prev_value > value else 1.0
        else:
            self.lines.color_idx[0] = 1.0 if self._velocity > 0 else 0.0


class KalmanFilterStrategy(bt.Strategy):
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
        kf=1.0,
        applied_price='PRICE_WEIGHTED',
        signal_mode='Kalman',
        signal_bar=1,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[-1]
        self.indicator = KalmanFilterIndicator(
            self.signal_feed,
            k=self.p.kf,
            applied_price=self.p.applied_price,
            signal_mode=self.p.signal_mode,
            point=self.p.point,
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
        self.warmup = int(self.p.signal_bar) + 2

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

    def _line_value(self, line, signal_bar, previous=False):
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
        if len(self.signal_feed) < self.warmup:
            return
        if self.order is not None:
            return
        if self.position and self._check_exit_levels():
            return
        color_now = self._line_value(self.indicator.color_idx, self.p.signal_bar)
        color_prev = self._line_value(self.indicator.color_idx, self.p.signal_bar, previous=True)
        value_now = self._line_value(self.indicator.value, self.p.signal_bar)
        if None in (color_now, color_prev, value_now):
            if len(self.signal_feed) < 2:
                return
            delta = float(self.signal_feed.close[0]) - float(self.signal_feed.close[-1])
            color_now = 1 if delta > 0 else 0
            color_prev = 0 if delta > 0 else 1
            value_now = float(self.signal_feed.close[0])
        self.last_signal_dt = signal_dt
        color_now = int(round(color_now))
        color_prev = int(round(color_prev))
        buy_open = self.p.buy_pos_open and color_now == 1 and color_prev == 0
        sell_open = self.p.sell_pos_open and color_now == 0 and color_prev == 1
        if not buy_open and not sell_open and not self.position:
            buy_open = self.p.buy_pos_open and color_now == 1
            sell_open = self.p.sell_pos_open and color_now == 0
        buy_close = self.p.buy_pos_close and color_now == 0
        sell_close = self.p.sell_pos_close and color_now == 1
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        if self.position.size > 0:
            if buy_close:
                self.pending_reverse_direction = -1 if sell_open else 0
                self.order = self.close()
                self.log(f'CLOSE long color_now={color_now} color_prev={color_prev} value={value_now:.5f}')
            return
        if self.position.size < 0:
            if sell_close:
                self.pending_reverse_direction = 1 if buy_open else 0
                self.order = self.close()
                self.log(f'CLOSE short color_now={color_now} color_prev={color_prev} value={value_now:.5f}')
            return
        if buy_open:
            self._submit_entry(1, f'color_now={color_now} color_prev={color_prev} value={value_now:.5f}')
            return
        if sell_open:
            self._submit_entry(-1, f'color_now={color_now} color_prev={color_prev} value={value_now:.5f}')
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
                self._submit_entry(reverse_direction, 'reverse after color change')
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
