from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

import numpy as np
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
    out = df.resample('1h', label='right', closed='right').agg(agg)
    return out.dropna(subset=['open', 'high', 'low', 'close'])


def moving_average(series, period, method='lwma'):
    method = str(method).lower()
    if method == 'sma':
        return series.rolling(period).mean()
    if method == 'ema':
        return series.ewm(span=period, adjust=False).mean()
    if method == 'smma':
        values = []
        prev = None
        for idx, value in enumerate(series.astype(float)):
            if idx + 1 < period:
                values.append(np.nan)
                continue
            if prev is None:
                prev = float(series.iloc[idx - period + 1: idx + 1].mean())
            else:
                prev = (prev * (period - 1) + float(value)) / period
            values.append(prev)
        return pd.Series(values, index=series.index)
    weights = np.arange(1, period + 1, dtype=float)
    return series.rolling(period).apply(lambda values: np.dot(values, weights) / weights.sum(), raw=True)


def build_indicator_frame(
    filepath,
    fromdate=None,
    todate=None,
    bar_shift_minutes=15,
    ma_period=3,
    ma_method='lwma',
):
    base = load_mt5_csv(filepath, fromdate=fromdate, todate=todate, bar_shift_minutes=bar_shift_minutes)
    frame = resample_to_h1(base)
    weighted_price = (frame['high'] + frame['low'] + 2.0 * frame['close']) / 4.0

    ma_close = moving_average(frame['close'], ma_period, ma_method)
    ma_open = moving_average(frame['open'], ma_period, ma_method)
    ma_weighted = moving_average(weighted_price, ma_period, ma_method)

    mamy_open = pd.Series(0.0, index=frame.index)
    mamy_close = pd.Series(0.0, index=frame.index)
    raw_close = ma_close - ma_weighted

    for idx in range(1, len(frame)):
        if pd.isna(ma_close.iat[idx]) or pd.isna(ma_open.iat[idx]) or pd.isna(ma_weighted.iat[idx]):
            mamy_open.iat[idx] = np.nan
            mamy_close.iat[idx] = np.nan
            continue
        close_now = raw_close.iat[idx]
        close_prev = raw_close.iat[idx - 1] if not pd.isna(raw_close.iat[idx - 1]) else 0.0
        bull_condition = (
            ma_close.iat[idx] > ma_close.iat[idx - 1]
            and ma_weighted.iat[idx] > ma_weighted.iat[idx - 1]
            and ma_close.iat[idx] > ma_weighted.iat[idx]
            and ma_weighted.iat[idx] > ma_open.iat[idx]
            and ma_weighted.iat[idx - 1] > ma_open.iat[idx - 1]
            and close_now >= close_prev
        )
        bear_condition = (
            ma_close.iat[idx] < ma_close.iat[idx - 1]
            and ma_weighted.iat[idx] < ma_weighted.iat[idx - 1]
            and ma_close.iat[idx] < ma_weighted.iat[idx]
            and ma_weighted.iat[idx] < ma_open.iat[idx]
            and ma_weighted.iat[idx - 1] < ma_open.iat[idx - 1]
            and close_now <= close_prev
        )
        open_now = (ma_weighted.iat[idx] - ma_open.iat[idx]) + (ma_close.iat[idx] - ma_weighted.iat[idx]) if (bull_condition or bear_condition) else 0.0
        previous_open = 0.0 if pd.isna(mamy_open.iat[idx - 1]) else mamy_open.iat[idx - 1]
        previous_close = 0.0 if pd.isna(mamy_close.iat[idx - 1]) else mamy_close.iat[idx - 1]
        close_buffer = close_now
        if open_now >= 0.0 and open_now > previous_open and close_now < 0.0 and previous_close >= 0.0:
            close_buffer = 0.0
        mamy_open.iat[idx] = open_now
        mamy_close.iat[idx] = close_buffer

    frame['mamy_open'] = mamy_open
    frame['mamy_close'] = mamy_close
    frame['open_buy'] = (frame['mamy_open'] > 0) & (frame['mamy_open'].shift(1) <= 0)
    frame['open_sell'] = (frame['mamy_open'] < 0) & (frame['mamy_open'].shift(1) >= 0)
    frame['close_buy'] = (frame['mamy_close'] < 0) & (frame['mamy_close'].shift(1) >= 0)
    frame['close_sell'] = (frame['mamy_close'] > 0) & (frame['mamy_close'].shift(1) <= 0)
    return frame.dropna(subset=['mamy_open', 'mamy_close'])


class MAMySystemFeed(bt.feeds.PandasData):
    lines = ('mamy_open', 'mamy_close', 'open_buy', 'open_sell', 'close_buy', 'close_sell')
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('mamy_open', 6),
        ('mamy_close', 7),
        ('open_buy', 8),
        ('open_sell', 9),
        ('close_buy', 10),
        ('close_sell', 11),
    )


class MAMySystemStrategy(bt.Strategy):
    params = dict(
        lots=1.0,
        ma_period=3,
        ma_method='lwma',
    )

    def __init__(self):
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
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
        if len(self.data) < 2:
            return

        if not self.position:
            if bool(self.data.open_buy[0]):
                self.log(f'buy open={float(self.data.open[0]):.2f} mamy_open={float(self.data.mamy_open[0]):.6f}')
                self.order = self.buy(size=self.p.lots)
                return
            if bool(self.data.open_sell[0]):
                self.log(f'sell open={float(self.data.open[0]):.2f} mamy_open={float(self.data.mamy_open[0]):.6f}')
                self.order = self.sell(size=self.p.lots)
                return

        if self.position.size > 0 and bool(self.data.close_buy[0]):
            self.log(f'close long mamy_close={float(self.data.mamy_close[0]):.6f}')
            self.order = self.close()
            return

        if self.position.size < 0 and bool(self.data.close_sell[0]):
            self.log(f'close short mamy_close={float(self.data.mamy_close[0]):.6f}')
            self.order = self.close()

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy() and self.position.size > 0:
                self.buy_count += 1
            elif order.issell() and self.position.size < 0:
                self.sell_count += 1
        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
