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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class EMA612Strategy(bt.Strategy):
    params = dict(
        fast_period=6,
        slow_period=54,
        lot=1.0,
        point=0.01,
        price_digits=2,
        take_profit_pips=10,
        trailing_stop_pips=50,
        trailing_step_pips=5,
    )

    def __init__(self):
        self.fast_sma = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.slow_sma = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._entry_price = None
        self._take_profit_price = None
        self._trail_stop_price = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _pip_size(self):
        digits_adjust = 10 if self.p.price_digits in (3, 5) else 1
        return self.p.point * digits_adjust

    def _clear_position_state(self):
        self._entry_price = None
        self._take_profit_price = None
        self._trail_stop_price = None

    def _sync_position_state(self):
        if not self.position:
            self._clear_position_state()
            return
        if self._entry_price is not None:
            return
        self._entry_price = float(self.position.price)
        pip_size = self._pip_size()
        tp_distance = self.p.take_profit_pips * pip_size
        if self.position.size > 0:
            self._take_profit_price = self._entry_price + tp_distance if self.p.take_profit_pips > 0 else None
        else:
            self._take_profit_price = self._entry_price - tp_distance if self.p.take_profit_pips > 0 else None

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.p.slow_period + 5:
            return

        self._sync_position_state()

        prev_fast = float(self.fast_sma[-1])
        prev_slow = float(self.slow_sma[-1])
        curr_fast = float(self.fast_sma[0])
        curr_slow = float(self.slow_sma[0])
        bull_cross = prev_fast <= prev_slow and curr_fast > curr_slow
        bear_cross = prev_fast >= prev_slow and curr_fast < curr_slow

        count_buys = 1 if self.position.size > 0 else 0
        count_sells = 1 if self.position.size < 0 else 0

        if bull_cross and count_sells > 0:
            self.log(f'close short on bull cross fast={curr_fast:.2f} slow={curr_slow:.2f}')
            self.close()
            return

        if bear_cross and count_buys > 0:
            self.log(f'close long on bear cross fast={curr_fast:.2f} slow={curr_slow:.2f}')
            self.close()
            return

        if count_buys == 0 and count_sells == 0:
            if bull_cross:
                self.log(f'buy fast={curr_fast:.2f} slow={curr_slow:.2f}')
                self.buy(size=self.p.lot)
                return
            if bear_cross:
                self.log(f'sell fast={curr_fast:.2f} slow={curr_slow:.2f}')
                self.sell(size=self.p.lot)
                return
            return

        pip_size = self._pip_size()
        trailing_distance = self.p.trailing_stop_pips * pip_size
        trailing_step = self.p.trailing_step_pips * pip_size
        close = float(self.data.close[0])
        high = float(self.data.high[0])
        low = float(self.data.low[0])

        if self.position.size > 0:
            if self._take_profit_price is not None and high >= self._take_profit_price:
                self.log(f'long take profit hit tp={self._take_profit_price:.2f} high={high:.2f}')
                self.close()
                return
            if trailing_distance > 0 and self._entry_price is not None:
                if close - self._entry_price > trailing_distance + trailing_step:
                    candidate = close - trailing_distance
                    if self._trail_stop_price is None or candidate > self._trail_stop_price:
                        self._trail_stop_price = candidate
                if self._trail_stop_price is not None and low <= self._trail_stop_price:
                    self.log(f'long trailing stop hit stop={self._trail_stop_price:.2f} low={low:.2f}')
                    self.close()
                    return
        elif self.position.size < 0:
            if self._take_profit_price is not None and low <= self._take_profit_price:
                self.log(f'short take profit hit tp={self._take_profit_price:.2f} low={low:.2f}')
                self.close()
                return
            if trailing_distance > 0 and self._entry_price is not None:
                if self._entry_price - close > trailing_distance + trailing_step:
                    candidate = close + trailing_distance
                    if self._trail_stop_price is None or candidate < self._trail_stop_price:
                        self._trail_stop_price = candidate
                if self._trail_stop_price is not None and high >= self._trail_stop_price:
                    self.log(f'short trailing stop hit stop={self._trail_stop_price:.2f} high={high:.2f}')
                    self.close()
                    return

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            self._position_was_open = True
            self._entry_price = float(trade.price)
            pip_size = self._pip_size()
            tp_distance = self.p.take_profit_pips * pip_size
            if trade.size > 0:
                self._take_profit_price = self._entry_price + tp_distance if self.p.take_profit_pips > 0 else None
            else:
                self._take_profit_price = self._entry_price - tp_distance if self.p.take_profit_pips > 0 else None
            self._trail_stop_price = None
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self._clear_position_state()
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
