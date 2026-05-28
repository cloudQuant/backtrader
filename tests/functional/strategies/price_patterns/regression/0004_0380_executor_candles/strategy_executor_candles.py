from __future__ import absolute_import, division, print_function, unicode_literals

import io

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


class ExecutorCandlesStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        price_digits=2,
        main_timeframe_off=True,
        stoploss_buy_pips=50,
        takeprofit_buy_pips=50,
        trailing_stop_buy_pips=15,
        stoploss_sell_pips=50,
        takeprofit_sell_pips=50,
        trailing_stop_sell_pips=15,
        trailing_step_pips=5,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.entry_order = None
        self.close_order = None
        self.active_side = None
        self.entry_price = None
        self.stop_price = None
        self.limit_price = None
        self.buy_count = 0
        self.sell_count = 0

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _bar(self, n):
        idx = 1 - n
        return {
            'open': float(self.data0_feed.open[idx]),
            'high': float(self.data0_feed.high[idx]),
            'low': float(self.data0_feed.low[idx]),
            'close': float(self.data0_feed.close[idx]),
        }

    def _compare_doubles(self, a, b):
        digits = max(int(self.p.price_digits) - 1, 0)
        return round(a - b, digits) == 0

    def _reset_exit_levels(self):
        self.stop_price = None
        self.limit_price = None

    def _initialize_exit_levels(self):
        if self.entry_price is None or self.active_side is None:
            return
        if self.active_side == 'long':
            self.stop_price = None if self.p.stoploss_buy_pips <= 0 else self.entry_price - self.p.stoploss_buy_pips * self.p.point_size
            self.limit_price = None if self.p.takeprofit_buy_pips <= 0 else self.entry_price + self.p.takeprofit_buy_pips * self.p.point_size
        else:
            self.stop_price = None if self.p.stoploss_sell_pips <= 0 else self.entry_price + self.p.stoploss_sell_pips * self.p.point_size
            self.limit_price = None if self.p.takeprofit_sell_pips <= 0 else self.entry_price - self.p.takeprofit_sell_pips * self.p.point_size

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason}')

    def _submit_entry(self, side, reason):
        if self.entry_order is not None or self.close_order is not None or self.position:
            return
        size = max(0.01, float(self.p.fixed_lot))
        if side == 'long':
            self.entry_order = self.buy(size=size)
            self.buy_count += 1
            self.log(f'OPEN LONG size={size} reason={reason}')
        else:
            self.entry_order = self.sell(size=size)
            self.sell_count += 1
            self.log(f'OPEN SHORT size={size} reason={reason}')
        self.active_side = side

    def _check_exit_thresholds(self):
        if not self.position or self.close_order is not None:
            return False
        bar_high = float(self.data0_feed.high[0])
        bar_low = float(self.data0_feed.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and bar_low <= self.stop_price:
                self._submit_close(f'stop loss hit @{self.stop_price:.5f}')
                return True
            if self.limit_price is not None and bar_high >= self.limit_price:
                self._submit_close(f'take profit hit @{self.limit_price:.5f}')
                return True
        else:
            if self.stop_price is not None and bar_high >= self.stop_price:
                self._submit_close(f'stop loss hit @{self.stop_price:.5f}')
                return True
            if self.limit_price is not None and bar_low <= self.limit_price:
                self._submit_close(f'take profit hit @{self.limit_price:.5f}')
                return True
        return False

    def _update_trailing(self):
        if not self.position or self.entry_price is None:
            return
        if self.position.size > 0:
            trailing_stop = self.p.trailing_stop_buy_pips
        else:
            trailing_stop = self.p.trailing_stop_sell_pips
        if trailing_stop <= 0:
            return
        trail_distance = trailing_stop * self.p.point_size
        trail_gate = (trailing_stop + self.p.trailing_step_pips) * self.p.point_size
        close_price = float(self.data0_feed.close[0])
        if self.position.size > 0:
            if close_price - self.entry_price > trail_gate:
                candidate = close_price - trail_distance
                if self.stop_price is None or candidate > self.stop_price + 1e-12:
                    self.stop_price = candidate
                    self.log(f'UPDATE LONG TRAIL stop={self.stop_price:.5f}')
        else:
            if self.entry_price - close_price > trail_gate:
                candidate = close_price + trail_distance
                if self.stop_price is None or candidate < self.stop_price - 1e-12:
                    self.stop_price = candidate
                    self.log(f'UPDATE SHORT TRAIL stop={self.stop_price:.5f}')

    def _is_hammer(self, trend_up):
        r1 = self._bar(1)
        r2 = self._bar(2)
        if self._compare_doubles(r1['close'], r1['open']):
            return False
        return ((not trend_up)
                and (r1['open'] - r1['close'] < 0)
                and ((r1['high'] - r1['close']) * 100.0 / (r1['close'] - r1['open']) > 200.0)
                and ((r1['open'] - r1['low']) * 100.0 / (r1['close'] - r1['open']) < 15.0)
                and (r2['open'] - r2['close'] > 0))

    def _is_bull(self, trend_up):
        r1 = self._bar(1)
        r2 = self._bar(2)
        if self._compare_doubles(r2['open'], r2['close']):
            return False
        return ((not trend_up)
                and (r1['open'] - r1['close'] < 0)
                and (r2['open'] - r2['close'] > 0)
                and (r1['close'] >= r2['open'])
                and (r1['open'] <= r2['close'])
                and ((r1['close'] - r1['open']) / (r2['open'] - r2['close']) > 1.5))

    def _is_piercing(self, trend_up):
        r1 = self._bar(1)
        r2 = self._bar(2)
        if self._compare_doubles(r2['high'], r2['low']):
            return False
        return ((not trend_up)
                and (r1['open'] - r1['close'] < 0)
                and (r2['open'] - r2['close'] > 0)
                and ((r2['open'] - r2['close']) / (r2['high'] - r2['low']) > 0.6)
                and (r1['open'] < r2['low'])
                and (r1['close'] > (r2['close'] + (r2['open'] - r2['close']) / 2.0)))

    def _is_morning_star(self, trend_up):
        r1 = self._bar(1)
        r2 = self._bar(2)
        r3 = self._bar(3)
        if self._compare_doubles(r3['open'], r3['close']) or self._compare_doubles(r3['high'], r3['low']) or self._compare_doubles(r2['high'], r2['low']) or self._compare_doubles(r1['high'], r1['low']):
            return False
        return ((r3['open'] - r3['close'] > 0)
                and (r2['close'] - r2['open'] > 0)
                and (r1['close'] - r1['open'] > 0)
                and (r2['close'] < r3['close'])
                and (r1['open'] > r2['close'])
                and (((abs(r3['open'] - r1['close']) + abs(r1['open'] - r3['close'])) / (r3['open'] - r3['close'])) < 0.1)
                and ((r3['open'] - r3['close']) / (r3['high'] - r3['low']) > 0.8)
                and ((r2['close'] - r2['open']) / (r2['high'] - r2['low']) < 0.3)
                and ((r1['close'] - r1['open']) / (r1['high'] - r1['low']) > 0.8))

    def _is_morning_doji_star(self):
        r1 = self._bar(1)
        r2 = self._bar(2)
        r3 = self._bar(3)
        if self._compare_doubles(r3['open'], r3['close']):
            return False
        return ((r3['open'] - r3['close'] > 0)
                and (r2['close'] - r2['open'] == 0)
                and (r1['close'] - r1['open'] > 0)
                and (r2['close'] <= r3['close'])
                and (r1['open'] >= r2['close'])
                and (((abs(r3['open'] - r1['close']) + abs(r1['open'] - r3['close'])) / (r3['open'] - r3['close'])) < 0.1))

    def _is_hanging_man(self, trend_up):
        r1 = self._bar(1)
        r2 = self._bar(2)
        if self._compare_doubles(r1['open'], r1['close']):
            return False
        return (trend_up
                and (r1['open'] - r1['close'] > 0)
                and ((r1['high'] - r1['open']) * 100.0 / (r1['open'] - r1['close']) < 15.0)
                and ((r1['close'] - r1['low']) * 100.0 / (r1['open'] - r1['close']) > 200.0)
                and (r2['open'] - r2['close'] < 0))

    def _is_bear(self, trend_up):
        r1 = self._bar(1)
        r2 = self._bar(2)
        if self._compare_doubles(r2['close'], r2['open']):
            return False
        return (trend_up
                and (r1['open'] - r1['close'] > 0)
                and (r1['open'] >= r2['close'])
                and (r1['close'] <= r2['open'])
                and (r2['open'] - r2['close'] < 0)
                and ((r1['open'] - r1['close']) / (r2['close'] - r2['open']) > 1.5))

    def _is_dark_cloud_cover(self, trend_up):
        r1 = self._bar(1)
        r2 = self._bar(2)
        if self._compare_doubles(r2['high'], r2['low']):
            return False
        return (trend_up
                and (r1['open'] - r1['close'] > 0)
                and (r2['open'] - r2['close'] < 0)
                and ((r2['close'] - r2['open']) / (r2['high'] - r2['low']) > 0.6)
                and (r1['open'] > r2['high'])
                and (r1['close'] < (r2['open'] + (r2['close'] - r2['open']) / 2.0)))

    def _is_evening_star(self):
        r1 = self._bar(1)
        r2 = self._bar(2)
        r3 = self._bar(3)
        if self._compare_doubles(r3['close'], r3['open']) or self._compare_doubles(r3['high'], r3['low']) or self._compare_doubles(r1['high'], r1['low']):
            return False
        return ((r3['open'] - r3['close'] < 0)
                and (r2['close'] - r2['open'] < 0)
                and (r1['close'] - r1['open'] < 0)
                and (r2['close'] > r3['close'])
                and (r1['open'] < r2['close'])
                and (((abs(r3['open'] - r1['close']) + abs(r1['open'] - r3['close'])) / (r3['close'] - r3['open'])) < 0.1)
                and ((r3['close'] - r3['open']) / (r3['high'] - r3['low']) > 0.8)
                and ((r2['open'] - r2['close']) / (r2['high'] - r2['low']) < 0.3)
                and ((r1['open'] - r1['close']) / (r1['high'] - r1['low']) > 0.8))

    def _is_evening_doji_star(self):
        r1 = self._bar(1)
        r2 = self._bar(2)
        r3 = self._bar(3)
        if self._compare_doubles(r3['open'], r3['close']):
            return False
        return ((r3['open'] - r3['close'] < 0)
                and (r2['close'] - r2['open'] == 0)
                and (r1['close'] - r1['open'] < 0)
                and (r2['close'] >= r3['close'])
                and (r1['open'] <= r2['close'])
                and (((abs(r3['open'] - r1['close']) + abs(r1['open'] - r3['close'])) / (r3['open'] - r3['close'])) < 0.1))

    def next(self):
        if len(self.data0_feed) < 4:
            return
        if self._check_exit_thresholds():
            return
        self._update_trailing()
        if self.entry_order is not None or self.close_order is not None or self.position:
            return
        trend_up = False
        if not self.p.main_timeframe_off:
            trend_up = float(self.data0_feed.open[-1]) >= float(self.data0_feed.close[-1])
        signal = None
        if self._is_hammer(trend_up):
            signal = ('long', 'hammer')
        elif self._is_bull(trend_up):
            signal = ('long', 'bullish engulfing')
        elif self._is_piercing(trend_up):
            signal = ('long', 'piercing line')
        elif self._is_morning_star(trend_up):
            signal = ('long', 'morning star')
        elif self._is_morning_doji_star():
            signal = ('long', 'morning doji star')
        elif self._is_hanging_man(trend_up):
            signal = ('short', 'hanging man')
        elif self._is_bear(trend_up):
            signal = ('short', 'bearish engulfing')
        elif self._is_dark_cloud_cover(trend_up):
            signal = ('short', 'dark cloud cover')
        elif self._is_evening_star():
            signal = ('short', 'evening star')
        elif self._is_evening_doji_star():
            signal = ('short', 'evening doji star')
        if signal is not None:
            self._submit_entry(signal[0], signal[1])

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.entry_price = order.executed.price
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
                self._initialize_exit_levels()
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.active_side = None
                self.entry_price = None
                self._reset_exit_levels()
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED side={self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
            self.entry_price = None
            self._reset_exit_levels()
