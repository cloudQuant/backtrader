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


class BeginnerFeed(btfeeds.PandasData):
    lines = ('sell_arrow', 'buy_arrow')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('sell_arrow', 6), ('buy_arrow', 7),
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


def get_range(length, highs, lows, index):
    window_high = highs[index:index + length]
    window_low = lows[index:index + length]
    return (window_high - window_low).abs().mean()


def build_beginner_frame(df, indicator_minutes, otstup, per, atr_period=10):
    signal_df = build_resampled_frame(df, indicator_minutes)
    highs = signal_df['high'].astype(float).reset_index(drop=True)
    lows = signal_df['low'].astype(float).reset_index(drop=True)
    close = signal_df['close'].astype(float).reset_index(drop=True)
    n = len(signal_df)
    sell_arrow = [0.0] * n
    buy_arrow = [0.0] * n
    min_rates_total = max(int(per), int(atr_period))
    trend = 0

    for idx in range(n - min_rates_total - 1, -1, -1):
        price_range = get_range(atr_period, highs, lows, idx) / 3.0
        sh_max = highs.iloc[idx:idx + int(per)].max()
        sh_min = lows.iloc[idx:idx + int(per)].min()
        diff = (sh_max - sh_min) * float(otstup) / 100.0

        if close.iloc[idx] < sh_min + diff and trend != -1:
            sell_arrow[idx] = highs.iloc[idx] + price_range
            if idx:
                trend = -1
        elif close.iloc[idx] > sh_max - diff and trend != 1:
            buy_arrow[idx] = lows.iloc[idx] - price_range
            if idx:
                trend = 1

    out = signal_df.copy()
    out['sell_arrow'] = sell_arrow
    out['buy_arrow'] = buy_arrow
    return out


class BeginnerStrategy(bt.Strategy):
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
        otstup=30,
        per=9,
        atr_period=10,
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

    def _has_signal(self, value):
        return math.isfinite(value) and value != 0.0

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

        ago = signal_bar - 1
        buy_value = self._line_value(self.signal.buy_arrow, ago)
        sell_value = self._line_value(self.signal.sell_arrow, ago)
        buy_signal = self._has_signal(buy_value)
        sell_signal = self._has_signal(sell_value)
        buy_close = False
        sell_close = False

        if buy_signal:
            sell_close = True
        if sell_signal:
            buy_close = True

        if not buy_close and not sell_close:
            for history_ago in range(signal_bar, len(self.signal)):
                if self.p.sell_pos_close:
                    older_buy = self._line_value(self.signal.buy_arrow, history_ago)
                    if self._has_signal(older_buy):
                        sell_close = True
                        break
                if self.p.buy_pos_close:
                    older_sell = self._line_value(self.signal.sell_arrow, history_ago)
                    if self._has_signal(older_sell):
                        buy_close = True
                        break

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if buy_close and self.position.size > 0 and self.p.buy_pos_close:
            self.close()
        if sell_close and self.position.size < 0 and self.p.sell_pos_close:
            self.close()
        if size <= 0:
            return

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} arrow={buy_value:.2f}')
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} arrow={sell_value:.2f}')
            if self.position.size >= 0 and self.p.sell_pos_open:
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
