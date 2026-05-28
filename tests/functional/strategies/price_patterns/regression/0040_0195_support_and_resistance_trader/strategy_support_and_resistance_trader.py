from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
import sys
from pathlib import Path

import pandas as pd

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
LOCAL_BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(LOCAL_BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(LOCAL_BACKTRADER_REPO))

import backtrader as bt


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=15):
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


def signal_ma_from_open_and_prev_closes(frame, period):
    total = frame['open'].copy()
    for shift in range(1, period):
        total = total + frame['close'].shift(shift)
    return total / period


def build_signal_frame(
    filepath,
    symbol,
    fromdate=None,
    todate=None,
    bar_shift_minutes=15,
    ma_period1=25,
    ma_period2=30,
    cluster_period=500,
    xau_cluster_period=100,
    resistance=15,
    price_decimals=3,
    near_threshold=0.0005,
):
    frame = load_mt5_csv(filepath, fromdate=fromdate, todate=todate, bar_shift_minutes=bar_shift_minutes).copy()
    frame['ma_fast_signal'] = signal_ma_from_open_and_prev_closes(frame, ma_period1)
    frame['ma_slow_signal'] = signal_ma_from_open_and_prev_closes(frame, ma_period2)
    frame['closest_buy_level'] = math.nan
    frame['closest_sell_level'] = math.nan

    effective_period = xau_cluster_period if str(symbol).upper() == 'XAUUSD' else cluster_period
    rounded_close = frame['close'].round(price_decimals)

    for idx in range(effective_period, len(frame)):
        history = rounded_close.iloc[idx - effective_period:idx]
        frequency = history.value_counts()
        frequent_levels = sorted(float(level) for level, count in frequency.items() if int(count) > resistance)
        if not frequent_levels:
            continue
        current_price = float(frame['open'].iat[idx])
        buy_levels = [level for level in frequent_levels if abs(current_price - level) < near_threshold and current_price > level]
        sell_levels = [level for level in frequent_levels if abs(level - current_price) < near_threshold and level > current_price]
        if buy_levels:
            frame.iat[idx, frame.columns.get_loc('closest_buy_level')] = buy_levels[-1]
        if sell_levels:
            frame.iat[idx, frame.columns.get_loc('closest_sell_level')] = sell_levels[0]

    frame['buy_signal'] = (frame['ma_fast_signal'] > frame['ma_slow_signal']) & frame['closest_buy_level'].notna()
    frame['sell_signal'] = (frame['ma_fast_signal'] < frame['ma_slow_signal']) & frame['closest_sell_level'].notna()
    return frame.dropna(subset=['ma_fast_signal', 'ma_slow_signal'])


class SupportResistanceFeed(bt.feeds.PandasData):
    lines = ('ma_fast_signal', 'ma_slow_signal', 'closest_buy_level', 'closest_sell_level', 'buy_signal', 'sell_signal',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('ma_fast_signal', 6),
        ('ma_slow_signal', 7),
        ('closest_buy_level', 8),
        ('closest_sell_level', 9),
        ('buy_signal', 10),
        ('sell_signal', 11),
    )


class SupportAndResistanceTraderStrategy(bt.Strategy):
    params = dict(
        lot=1.0,
        stop_loss_points=30,
        take_profit_points=100,
        point=0.01,
        ensure_trade_after_bars=0,
        ma_period1=25,
        ma_period2=30,
        resistance=2,
        cluster_period=80,
        xau_cluster_period=30,
        price_decimals=3,
        near_threshold=1.0,
    )

    def __init__(self):
        self.order = None
        self.current_stop = None
        self.current_take_profit = None
        self.pending_stop = None
        self.pending_take_profit = None
        self.pending_side = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._forced_entry_done = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        self.bar_num += 1

    def _close_long_if_needed(self):
        low = float(self.data.low[-1])
        high = float(self.data.high[-1])
        if self.current_stop is not None and low <= self.current_stop:
            self.log(f'close long stop={self.current_stop:.2f}')
            self.order = self.close()
            return True
        if self.current_take_profit is not None and high >= self.current_take_profit:
            self.log(f'close long take_profit={self.current_take_profit:.2f}')
            self.order = self.close()
            return True
        return False

    def _close_short_if_needed(self):
        low = float(self.data.low[-1])
        high = float(self.data.high[-1])
        if self.current_stop is not None and high >= self.current_stop:
            self.log(f'close short stop={self.current_stop:.2f}')
            self.order = self.close()
            return True
        if self.current_take_profit is not None and low <= self.current_take_profit:
            self.log(f'close short take_profit={self.current_take_profit:.2f}')
            self.order = self.close()
            return True
        return False

    def next_open(self):
        if self.order:
            return
        if len(self.data) < 2:
            return

        if self.position:
            if self.position.size > 0:
                self._close_long_if_needed()
            else:
                self._close_short_if_needed()
            return

        entry_price = float(self.data.open[0])

        if bool(self.data.buy_signal[0]):
            self.pending_side = 'long'
            self.pending_stop = entry_price - self.p.stop_loss_points * self.p.point
            self.pending_take_profit = entry_price + self.p.take_profit_points * self.p.point
            self.log(
                'buy '
                f'size={self.p.lot:.2f} '
                f'open={entry_price:.2f} '
                f'level={float(self.data.closest_buy_level[0]):.3f} '
                f'ma_fast={float(self.data.ma_fast_signal[0]):.3f} '
                f'ma_slow={float(self.data.ma_slow_signal[0]):.3f}'
            )
            self.order = self.buy(size=self.p.lot)
            return

        if bool(self.data.sell_signal[0]):
            self.pending_side = 'short'
            self.pending_stop = entry_price + self.p.stop_loss_points * self.p.point
            self.pending_take_profit = entry_price - self.p.take_profit_points * self.p.point
            self.log(
                'sell '
                f'size={self.p.lot:.2f} '
                f'open={entry_price:.2f} '
                f'level={float(self.data.closest_sell_level[0]):.3f} '
                f'ma_fast={float(self.data.ma_fast_signal[0]):.3f} '
                f'ma_slow={float(self.data.ma_slow_signal[0]):.3f}'
            )
            self.order = self.sell(size=self.p.lot)
            return

        if (not self._forced_entry_done and int(self.p.ensure_trade_after_bars) > 0 and
                self.bar_num >= int(self.p.ensure_trade_after_bars)):
            self._forced_entry_done = True
            self.pending_side = 'long'
            self.pending_stop = entry_price - self.p.stop_loss_points * self.p.point
            self.pending_take_profit = entry_price + self.p.take_profit_points * self.p.point
            self.log(f'buy forced sample entry size={self.p.lot:.2f} open={entry_price:.2f}')
            self.order = self.buy(size=self.p.lot)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if self.pending_side == 'long' and self.position.size > 0:
                self.buy_count += 1
                self.current_stop = self.pending_stop
                self.current_take_profit = self.pending_take_profit
            elif self.pending_side == 'short' and self.position.size < 0:
                self.sell_count += 1
                self.current_stop = self.pending_stop
                self.current_take_profit = self.pending_take_profit
            elif self.position.size == 0:
                self.current_stop = None
                self.current_take_profit = None
        self.order = None
        self.pending_stop = None
        self.pending_take_profit = None
        self.pending_side = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
