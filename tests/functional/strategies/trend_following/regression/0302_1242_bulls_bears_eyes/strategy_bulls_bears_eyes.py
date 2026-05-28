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


MODE_TWIST = 0
MODE_BREAKDOWN1 = 1
MODE_BREAKDOWN2 = 2
MODE_BREAKDOWN3 = 3


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


class BullsBearsEyesFeed(btfeeds.PandasData):
    lines = ('bbe', 'sign',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('bbe', 6), ('sign', 7),
    )


def build_resampled_frame(df, indicator_minutes):
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
    return signal_df


def ema_series(values, period):
    return values.ewm(span=int(period), adjust=False).mean()


def build_bulls_bears_eyes_frame(df, indicator_minutes, period, gamma, mode, high_level, middle_level, low_level):
    signal_df = build_resampled_frame(df, indicator_minutes)
    period = int(period)
    gamma = float(gamma)
    mode = int(mode)
    high_level = float(high_level)
    middle_level = float(middle_level)
    low_level = float(low_level)

    ema = ema_series(signal_df['close'].astype(float), period)
    bears = signal_df['low'].astype(float) - ema
    bulls = signal_df['high'].astype(float) - ema

    bbe_values = [math.nan] * len(signal_df)
    colors = [0] * len(signal_df)
    signs = [0] * len(signal_df)

    l0 = 0.0
    l1 = 0.0
    l2 = 0.0
    l3 = 0.0
    trend = 0

    for idx in range(len(signal_df)):
        if idx < period + 3:
            continue

        l0a, l1a, l2a, l3a = l0, l1, l2, l3
        l0 = (1.0 - gamma) * (float(bears.iloc[idx]) + float(bulls.iloc[idx])) + gamma * l0a
        l1 = -gamma * l0 + l0a + gamma * l1a
        l2 = -gamma * l1 + l1a + gamma * l2a
        l3 = -gamma * l2 + l2a + gamma * l3a

        cu = 0.0
        cd = 0.0
        if l0 >= l1:
            cu += l0 - l1
        else:
            cd += l1 - l0
        if l1 >= l2:
            cu += l1 - l2
        else:
            cd += l2 - l1
        if l2 >= l3:
            cu += l2 - l3
        else:
            cd += l3 - l2

        result = (cu / (cu + cd) * 100.0) if (cu + cd) != 0 else 0.0
        bbe_values[idx] = result

        if mode == MODE_TWIST:
            if idx >= 1:
                if math.isfinite(bbe_values[idx - 1]) and bbe_values[idx - 1] > result:
                    colors[idx] = 1
                elif math.isfinite(bbe_values[idx - 1]) and bbe_values[idx - 1] < result:
                    colors[idx] = 2
        elif mode == MODE_BREAKDOWN1:
            if result < middle_level:
                colors[idx] = 1
            elif result > middle_level:
                colors[idx] = 2
        elif mode == MODE_BREAKDOWN2:
            if result < low_level:
                colors[idx] = 1
            elif result > high_level:
                colors[idx] = 2
        elif mode == MODE_BREAKDOWN3:
            if idx >= 1 and math.isfinite(bbe_values[idx - 1]):
                prev = bbe_values[idx - 1]
                if prev >= high_level and result < high_level:
                    trend = -1
                if prev >= low_level and result < low_level:
                    trend = -1
                if prev <= low_level and result > low_level:
                    trend = 1
                if prev <= high_level and result > high_level:
                    trend = 1
            if trend < 0:
                colors[idx] = 1
            elif trend > 0:
                colors[idx] = 2

        prev_sign = signs[idx - 1] if idx >= 1 else 0
        color = colors[idx]
        sign = 0
        if prev_sign > 0 and color == 1:
            sign = -2
        elif ((prev_sign <= 0 and color == 1) or (prev_sign < 0 and color == 0)):
            sign = -1
        if prev_sign < 0 and color == 2:
            sign = 2
        elif ((prev_sign >= 0 and color == 2) or (prev_sign > 0 and color == 0)):
            sign = 1
        signs[idx] = sign

    signal_df = signal_df.copy()
    signal_df['bbe'] = bbe_values
    signal_df['sign'] = signs
    return signal_df


class BullsBearsEyesStrategy(bt.Strategy):
    params = dict(
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        mm=-0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=240,
        period=13,
        gamma=0.6,
        mode=2,
        high_level=75,
        middle_level=50,
        low_level=25,
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

    def _line_value(self, line, ago):
        return float(line[-ago]) if ago else float(line[0])

    def _position_size(self, price):
        if self.p.mm < 0:
            return abs(float(self.p.mm))
        if price <= 0:
            return 0.0
        cash = self.broker.getcash()
        return round((cash * float(self.p.mm)) / price, 4)

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

        signal_bar = max(int(self.p.signal_bar), 1)
        if len(self.signal) < signal_bar:
            return

        current_signal_len = len(self.signal)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        recent_ago = signal_bar - 1
        trend = int(round(self._line_value(self.signal.sign, recent_ago)))
        value = self._line_value(self.signal.bbe, recent_ago)
        if trend == 0 or not math.isfinite(value):
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if trend > 0:
            self.signal_count += 1
            self.log(f'bull signal sign={trend} value={value:.2f} close={close_price:.2f}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if trend == 2 and self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if trend < 0:
            self.signal_count += 1
            self.log(f'bear signal sign={trend} value={value:.2f} close={close_price:.2f}')
            if self.position.size > 0 and self.p.buy_pos_close:
                self.close()
            if trend == -2 and self.position.size >= 0 and self.p.sell_pos_open:
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
