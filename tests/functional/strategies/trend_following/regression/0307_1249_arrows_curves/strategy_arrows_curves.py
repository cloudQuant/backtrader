from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import backtrader.feeds as btfeeds
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


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class ArrowsCurvesSignalFeed(btfeeds.PandasData):
    lines = ('buy_signal', 'sell_signal', 'buy_stop_signal', 'sell_stop_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('buy_signal', 6), ('sell_signal', 7), ('buy_stop_signal', 8), ('sell_stop_signal', 9),
    )


def build_arrows_curves_signal_frame(df, indicator_minutes, ssp, channel, ch_stop, relay):
    rule = f'{int(indicator_minutes)}min'
    signal_df = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    signal_df = signal_df.dropna(subset=['open', 'high', 'low', 'close']).copy()
    signal_df['openinterest'] = signal_df['openinterest'].fillna(0)
    signal_df['buy_signal'] = 0.0
    signal_df['sell_signal'] = 0.0
    signal_df['buy_stop_signal'] = 0.0
    signal_df['sell_stop_signal'] = 0.0

    start_bars = int(ssp) + 1 + int(relay)
    uptrend = False
    old = False
    uptrend2 = False
    old2 = False

    for pos in range(len(signal_df)):
        if pos < start_bars:
            continue

        history_end = pos - int(relay)
        history_start = history_end - int(ssp) + 1
        if history_start < 0:
            continue

        window = signal_df.iloc[history_start:history_end + 1]
        if len(window) < int(ssp):
            continue

        current_close = float(signal_df.iloc[pos]['close'])
        current_high = float(signal_df.iloc[pos]['high'])
        current_low = float(signal_df.iloc[pos]['low'])
        high_value = float(window['high'].max())
        low_value = float(window['low'].min())

        smax = high_value - (low_value - high_value) * float(channel) / 100.0
        smin = low_value + (high_value - low_value) * float(channel) / 100.0
        smax2 = high_value - (high_value - low_value) * float(channel + ch_stop) / 100.0
        smin2 = low_value + (high_value - low_value) * float(channel + ch_stop) / 100.0

        buy_signal = 0.0
        sell_signal = 0.0
        buy_stop_signal = 0.0
        sell_stop_signal = 0.0

        if current_close < smin and current_close < smax and uptrend2:
            uptrend = False
        if current_close > smax and current_close > smin and not uptrend2:
            uptrend = True
        if (current_close > smax2 or current_close > smin2) and not uptrend:
            uptrend2 = False
        if (current_close < smin2 or current_close < smax2) and uptrend:
            uptrend2 = True

        if current_close < smin and current_close < smax and not uptrend2:
            sell_signal = current_low
            uptrend2 = True
        if current_close > smax and current_close > smin and uptrend2:
            buy_signal = current_high
            uptrend2 = False

        if uptrend != old and not uptrend:
            sell_signal = current_low
        if uptrend != old and uptrend:
            buy_signal = current_high

        if uptrend2 != old2 and uptrend2:
            buy_stop_signal = smax2
        if uptrend2 != old2 and not uptrend2:
            sell_stop_signal = smin2

        old = uptrend
        old2 = uptrend2

        signal_df.iloc[pos, signal_df.columns.get_loc('buy_signal')] = buy_signal
        signal_df.iloc[pos, signal_df.columns.get_loc('sell_signal')] = sell_signal
        signal_df.iloc[pos, signal_df.columns.get_loc('buy_stop_signal')] = buy_stop_signal
        signal_df.iloc[pos, signal_df.columns.get_loc('sell_stop_signal')] = sell_stop_signal

    return signal_df


class ArrowsCurvesStrategy(bt.Strategy):
    params = dict(
        ssp=20,
        channel=0,
        ch_stop=30,
        relay=10,
        stop_loss_points=1000,
        take_profit_points=2000,
        mm=-0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=240,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal = self.datas[1]
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._last_signal_len = 0

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _is_signal(self, value):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return False
        return not math.isnan(numeric) and numeric not in (0.0,)

    def _position_size(self, price):
        if self.p.mm < 0:
            return abs(self.p.mm)
        if price <= 0:
            return 0.0
        cash = self.broker.getcash()
        return round((cash * self.p.mm) / price, 4)

    def _check_exit_levels(self):
        if not self.position:
            return False
        close_price = float(self.base.close[0])
        point_value = float(self.p.point)
        stop_distance = self.p.stop_loss_points * point_value if self.p.stop_loss_points > 0 else None
        take_distance = self.p.take_profit_points * point_value if self.p.take_profit_points > 0 else None
        entry_price = float(self.position.price)

        if self.position.size > 0:
            if stop_distance is not None and close_price <= entry_price - stop_distance:
                self.log(f'close long by stop loss close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
            if take_distance is not None and close_price >= entry_price + take_distance:
                self.log(f'close long by take profit close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
        elif self.position.size < 0:
            if stop_distance is not None and close_price >= entry_price + stop_distance:
                self.log(f'close short by stop loss close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
            if take_distance is not None and close_price <= entry_price - take_distance:
                self.log(f'close short by take profit close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return

        if self._check_exit_levels():
            return

        current_signal_len = len(self.signal)
        if current_signal_len < 2 or current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        buy_signal = self._is_signal(self.signal.buy_signal[0])
        sell_signal = self._is_signal(self.signal.sell_signal[0])
        buy_stop_signal = self._is_signal(self.signal.buy_stop_signal[0])
        sell_stop_signal = self._is_signal(self.signal.sell_stop_signal[0])

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if self.position.size < 0 and (sell_stop_signal or buy_signal) and self.p.sell_pos_close:
            self.log(f'close short by signal close={close_price:.2f}')
            self.close()
        if self.position.size > 0 and (buy_stop_signal or sell_signal) and self.p.buy_pos_close:
            self.log(f'close long by signal close={close_price:.2f}')
            self.close()

        if buy_signal and self.p.buy_pos_open:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f}')
            self.buy(size=size)
            return

        if sell_signal and self.p.sell_pos_open:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f}')
            self.sell(size=size)

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
