from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

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
    df = df[['datetime', 'open', 'high', 'low', 'close', 'tick_volume', 'openinterest']]
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


class SilverTrendSignalProxy(bt.Indicator):
    lines = ('signal',)
    params = dict(risk=3)

    def __init__(self):
        self.period = max(3, int(self.p.risk) * 2 + 1)
        self.ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.period)
        self.addminperiod(self.period + 2)

    def next(self):
        signal = float(self.lines.signal[-1]) if len(self) > 0 else 0.0
        if not math.isfinite(signal):
            signal = 0.0
        close_prev = float(self.data.close[-1])
        close_now = float(self.data.close[0])
        ma_prev = float(self.ma[-1])
        ma_now = float(self.ma[0])
        if close_prev <= ma_prev and close_now > ma_now:
            signal = 1.0
        elif close_prev >= ma_prev and close_now < ma_now:
            signal = -1.0
        self.lines.signal[0] = signal


class JTpoProxy(bt.Indicator):
    lines = ('value',)
    params = dict(period=14)

    def __init__(self):
        self.period = max(2, int(self.p.period))
        self.ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.period)
        self.addminperiod(self.period + 1)

    def next(self):
        self.lines.value[0] = float(self.data.close[0]) - float(self.ma[0])


class SilverTrendV3Strategy(bt.Strategy):
    params = dict(
        trailing_stop=50,
        take_profit=50,
        initial_stop_loss=0,
        friday_night_hour=16,
        risk=3,
        jtpo_period=14,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.silver = SilverTrendSignalProxy(self.data0_feed, risk=self.p.risk)
        self.jtpo = JTpoProxy(self.data0_feed, period=self.p.jtpo_period)

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
        self.last_direction = 0

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _set_entry_risk(self, side):
        price = float(self.data0_feed.close[0])
        unit = self._unit()
        if side == 'buy':
            self.stop_price = round(price - float(self.p.initial_stop_loss) * unit, int(self.p.price_digits)) if self.p.initial_stop_loss > 0 else None
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + float(self.p.initial_stop_loss) * unit, int(self.p.price_digits)) if self.p.initial_stop_loss > 0 else None
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None

    def _apply_trailing_stop(self):
        if not self.position or self.p.trailing_stop <= 0:
            return
        unit = self._unit()
        if self.position.size > 0:
            move = float(self.data0_feed.close[0]) - float(self.position.price)
            if move > float(self.p.trailing_stop) * unit:
                candidate = round(float(self.data0_feed.close[0]) - float(self.p.trailing_stop) * unit, int(self.p.price_digits))
                if self.stop_price is None or candidate > self.stop_price:
                    self.stop_price = candidate
        else:
            move = float(self.position.price) - float(self.data0_feed.close[0])
            if move > float(self.p.trailing_stop) * unit:
                candidate = round(float(self.data0_feed.close[0]) + float(self.p.trailing_stop) * unit, int(self.p.price_digits))
                if self.stop_price is None or candidate < self.stop_price:
                    self.stop_price = candidate

    def _manage_risk(self):
        if not self.position:
            return False
        self._apply_trailing_stop()
        high = float(self.data0_feed.high[0])
        low = float(self.data0_feed.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.order = self.close()
                return True
        return False

    def _allow_new_trade(self):
        dt = bt.num2date(self.data0_feed.datetime[0])
        if float(self.p.friday_night_hour) > 0 and dt.weekday() == 4 and dt.hour > int(self.p.friday_night_hour):
            return False
        return True

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if len(self.data0_feed) < max(int(self.p.risk) * 2 + 3, int(self.p.jtpo_period) + 2):
            return
        if self._manage_risk():
            return

        signal_value = float(self.silver.signal[0])
        if not math.isfinite(signal_value):
            return
        direction = int(signal_value)
        jtpo_value = float(self.jtpo[0])
        long_signal = self.last_direction != direction and direction > 0 and jtpo_value > 0
        short_signal = self.last_direction != direction and direction < 0 and jtpo_value < 0
        exit_long = direction < 0
        exit_short = direction > 0

        if long_signal or short_signal:
            self.signal_count += 1
        self.log(f'signal={direction} prev={self.last_direction} jtpo={jtpo_value:.4f} long={long_signal} short={short_signal}')
        self.last_direction = direction

        if exit_long and self.position and self.position.size > 0:
            self.order = self.close()
            return
        if exit_short and self.position and self.position.size < 0:
            self.order = self.close()
            return
        if not self._allow_new_trade():
            return

        if long_signal and (not self.position or self.position.size <= 0):
            if self.position and self.position.size < 0:
                self.order = self.close()
                return
            self._set_entry_risk('buy')
            self.order = self.buy(size=float(self.p.size))
            return

        if short_signal and (not self.position or self.position.size >= 0):
            if self.position and self.position.size > 0:
                self.order = self.close()
                return
            self._set_entry_risk('sell')
            self.order = self.sell(size=float(self.p.size))

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
                self.log(f'filled size={order.executed.size:.2f} price={order.executed.price:.2f}')
            else:
                self.stop_price = None
                self.take_profit_price = None
                self.log(f'closed size={order.executed.size:.2f} price={order.executed.price:.2f}')
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
            self.log(f'order failed status={order.getstatusname()}')
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
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
