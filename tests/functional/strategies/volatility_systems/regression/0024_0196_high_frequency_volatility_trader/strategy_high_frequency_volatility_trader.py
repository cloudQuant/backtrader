from __future__ import absolute_import, division, print_function, unicode_literals

import io
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


def resample_to_h1(df):
    agg = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'sum',
    }
    h1 = df.resample('1h', label='right', closed='right').agg(agg)
    return h1.dropna(subset=['open', 'high', 'low', 'close'])


def signal_ma_from_open_and_prev_closes(frame, period):
    total = frame['open'].copy()
    for shift in range(1, period):
        total = total + frame['close'].shift(shift)
    return total / period


def build_signal_frame(
    filepath,
    fromdate=None,
    todate=None,
    bar_shift_minutes=15,
    fast_ma_period=5,
    slow_ma_period=25,
    buy_threshold=0.0015,
):
    base = load_mt5_csv(filepath, fromdate=fromdate, todate=todate, bar_shift_minutes=bar_shift_minutes)
    frame = resample_to_h1(base)
    frame['ma_fast_signal'] = signal_ma_from_open_and_prev_closes(frame, fast_ma_period)
    frame['ma_slow_signal'] = signal_ma_from_open_and_prev_closes(frame, slow_ma_period)
    frame['ma_fast_prev2'] = frame['close'].rolling(fast_ma_period).mean().shift(2)
    frame['tp_price'] = frame['ma_fast_signal']
    frame['buy_condition_1'] = frame['ma_fast_signal'] - frame['open'] < -buy_threshold
    frame['buy_condition_2'] = frame['ma_fast_signal'] > frame['ma_fast_prev2']
    frame['tp_valid'] = frame['tp_price'] > frame['open']
    frame['buy_signal'] = frame['buy_condition_1'] & frame['buy_condition_2'] & frame['tp_valid']
    return frame.dropna(subset=['ma_fast_signal', 'ma_slow_signal', 'ma_fast_prev2'])


class VolatilityHftFeed(bt.feeds.PandasData):
    lines = ('ma_fast_signal', 'ma_slow_signal', 'ma_fast_prev2', 'tp_price', 'buy_signal',)
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
        ('ma_fast_prev2', 8),
        ('tp_price', 9),
        ('buy_signal', 10),
    )


class HighFrequencyVolatilityTraderStrategy(bt.Strategy):
    params = dict(
        lot=1.0,
        stop_loss_points=15,
        take_profit_points=15,
        buy_threshold=0.0015,
        point=0.01,
        fast_ma_period=5,
        slow_ma_period=25,
    )

    def __init__(self):
        self.order = None
        self.current_stop = None
        self.current_take_profit = None
        self.pending_stop = None
        self.pending_take_profit = None
        self.bar_num = 0
        self.buy_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        self.bar_num += 1

    def next_open(self):
        if self.order:
            return
        if len(self.data) < 30:
            return

        if self.position:
            low = float(self.data.low[-1])
            high = float(self.data.high[-1])
            if self.current_stop is not None and low <= self.current_stop:
                self.log(f'close long stop={self.current_stop:.2f}')
                self.order = self.close()
                return
            if self.current_take_profit is not None and high >= self.current_take_profit:
                self.log(f'close long take_profit={self.current_take_profit:.2f}')
                self.order = self.close()
                return
            return

        if bool(self.data.buy_signal[0]):
            signal_open = float(self.data.open[0])
            take_profit = float(self.data.tp_price[0])
            if take_profit <= signal_open:
                return
            self.pending_stop = signal_open - self.p.stop_loss_points * self.p.point if self.p.stop_loss_points else None
            self.pending_take_profit = take_profit
            self.log(
                'buy '
                f'size={self.p.lot:.2f} '
                f'open={signal_open:.2f} '
                f'ma_fast_signal={float(self.data.ma_fast_signal[0]):.2f} '
                f'ma_fast_prev2={float(self.data.ma_fast_prev2[0]):.2f}'
            )
            self.order = self.buy(size=self.p.lot)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy() and self.position.size > 0:
                self.buy_count += 1
                self.current_stop = self.pending_stop
                self.current_take_profit = self.pending_take_profit
            elif self.position.size == 0:
                self.current_stop = None
                self.current_take_profit = None
        self.order = None
        self.pending_stop = None
        self.pending_take_profit = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
