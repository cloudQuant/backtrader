from __future__ import absolute_import, division, print_function, unicode_literals

import io

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
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
    })
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
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class ChannelsStrategy(bt.Strategy):
    params = dict(
        lot=0.1,
        stop_loss_buy_pips=0,
        stop_loss_sell_pips=0,
        take_profit_buy_pips=0,
        take_profit_sell_pips=0,
        trailing_stop_buy_pips=30,
        trailing_stop_sell_pips=30,
        trailing_step_pips=1,
        use_hours=False,
        from_hour=0,
        to_hour=23,
        current_tf_compression=15,
        higher_tf_compression=60,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.data_current = self.datas[0]
        self.data_h1 = self.datas[1]
        self.ema_close_2 = bt.ind.ExponentialMovingAverage(self.data_h1.close, period=2)
        self.ema_open_2 = bt.ind.ExponentialMovingAverage(self.data_h1.open, period=2)
        self.ema_close_220 = bt.ind.ExponentialMovingAverage(self.data_h1.close, period=220)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0

    def log(self, text):
        dt = bt.num2date(self.data_current.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _pip_size(self):
        digits_adjust = 10 if self.p.price_digits in (3, 5) else 1
        return self.p.point * digits_adjust

    def _clear_position_state(self):
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0

    def _set_initial_protection(self):
        if not self.position:
            self._clear_position_state()
            return
        if self._entry_price is not None and self._last_position_size == float(self.position.size):
            return
        self._entry_price = float(self.position.price)
        self._last_position_size = float(self.position.size)
        pip_size = self._pip_size()
        if self.position.size > 0:
            self._stop_price = self._entry_price - self.p.stop_loss_buy_pips * pip_size if self.p.stop_loss_buy_pips > 0 else None
            self._take_profit_price = self._entry_price + self.p.take_profit_buy_pips * pip_size if self.p.take_profit_buy_pips > 0 else None
        else:
            self._stop_price = self._entry_price + self.p.stop_loss_sell_pips * pip_size if self.p.stop_loss_sell_pips > 0 else None
            self._take_profit_price = self._entry_price - self.p.take_profit_sell_pips * pip_size if self.p.take_profit_sell_pips > 0 else None

    def _env_levels(self, base):
        return {
            'upper_03': base * 1.003,
            'lower_03': base * 0.997,
            'upper_07': base * 1.007,
            'lower_07': base * 0.993,
            'upper_10': base * 1.010,
            'lower_10': base * 0.990,
        }

    def _use_session(self):
        if not self.p.use_hours:
            return True
        hour = bt.num2date(self.data_current.datetime[0]).hour
        return self.p.from_hour <= hour <= self.p.to_hour

    def _buy_signal(self):
        ema_close_0 = float(self.ema_close_2[0])
        ema_close_1 = float(self.ema_close_2[-1])
        ema_base_0 = float(self.ema_close_220[0])
        levels = self._env_levels(ema_base_0)
        return (
            (ema_close_0 > levels['lower_10'] and ema_close_1 < levels['lower_10'])
            or (ema_close_0 > levels['lower_07'] and ema_close_1 < levels['lower_07'])
            or (ema_close_0 < levels['lower_03'] and ema_close_1 < levels['lower_03'])
            or (ema_close_0 > ema_base_0 and ema_close_1 < ema_base_0)
            or (ema_close_0 > levels['upper_03'] and ema_close_1 < levels['upper_03'])
            or (ema_close_0 > levels['upper_07'] and ema_close_1 < levels['upper_07'])
        )

    def _sell_signal(self):
        ema_open_0 = float(self.ema_open_2[0])
        ema_open_1 = float(self.ema_open_2[-1])
        ema_base_0 = float(self.ema_close_220[0])
        levels = self._env_levels(ema_base_0)
        return (
            (ema_open_0 < levels['upper_10'] and ema_open_1 > levels['upper_10'])
            or (ema_open_0 < levels['upper_07'] and ema_open_1 > levels['upper_07'])
            or (ema_open_0 < levels['upper_03'] and ema_open_1 > levels['upper_03'])
            or (ema_open_0 < ema_base_0 and ema_open_1 > ema_base_0)
            or (ema_open_0 < levels['lower_03'] and ema_open_1 > levels['lower_03'])
            or (ema_open_0 < levels['lower_07'] and ema_open_1 > levels['lower_07'])
        )

    def _update_trailing(self):
        if not self.position or self._entry_price is None:
            return
        pip_size = self._pip_size()
        close = float(self.data_current.close[0])
        if self.position.size > 0 and self.p.trailing_stop_buy_pips > 0:
            distance = self.p.trailing_stop_buy_pips * pip_size
            step = self.p.trailing_step_pips * pip_size
            if close - self._entry_price > distance + step:
                candidate = close - distance
                if self._stop_price is None or candidate > self._stop_price:
                    self._stop_price = candidate
        elif self.position.size < 0 and self.p.trailing_stop_sell_pips > 0:
            distance = self.p.trailing_stop_sell_pips * pip_size
            step = self.p.trailing_step_pips * pip_size
            if self._entry_price - close > distance + step:
                candidate = close + distance
                if self._stop_price is None or candidate < self._stop_price or self._stop_price == 0:
                    self._stop_price = candidate

    def _maybe_hit_exit(self):
        if not self.position:
            return False
        high = float(self.data_current.high[0])
        low = float(self.data_current.low[0])
        if self.position.size > 0:
            if self._stop_price is not None and low <= self._stop_price:
                self.log(f'close long stop={self._stop_price:.2f}')
                self.order = self.close(data=self.data_current)
                return True
            if self._take_profit_price is not None and high >= self._take_profit_price:
                self.log(f'close long take_profit={self._take_profit_price:.2f}')
                self.order = self.close(data=self.data_current)
                return True
        else:
            if self._stop_price is not None and high >= self._stop_price:
                self.log(f'close short stop={self._stop_price:.2f}')
                self.order = self.close(data=self.data_current)
                return True
            if self._take_profit_price is not None and low <= self._take_profit_price:
                self.log(f'close short take_profit={self._take_profit_price:.2f}')
                self.order = self.close(data=self.data_current)
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.data_h1) < 225:
            return
        if self.order:
            return
        if not self._use_session():
            return
        if self.p.trailing_stop_buy_pips == 0 and self.p.trailing_stop_sell_pips == 0:
            return

        if self.position:
            self._set_initial_protection()
            self._update_trailing()
            if self._maybe_hit_exit():
                return
            return

        if self._buy_signal():
            self.log('buy channels signal')
            self.order = self.buy(data=self.data_current, size=self.p.lot)
            return
        if self._sell_signal():
            self.log('sell channels signal')
            self.order = self.sell(data=self.data_current, size=self.p.lot)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy() and order.executed.size > 0 and self.position.size > 0:
                self.buy_count += 1
                self._set_initial_protection()
            elif order.issell() and order.executed.size < 0 and self.position.size < 0:
                self.sell_count += 1
                self._set_initial_protection()
            elif self.position:
                self._set_initial_protection()
            else:
                self._clear_position_state()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
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
        if not self.position:
            self._clear_position_state()
