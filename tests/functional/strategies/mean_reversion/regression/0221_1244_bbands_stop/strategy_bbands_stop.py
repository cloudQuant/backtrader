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


class BBandsStopFeed(btfeeds.PandasData):
    lines = ('up_buffer', 'dn_buffer', 'buy_signal', 'sell_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('up_buffer', 6), ('dn_buffer', 7), ('buy_signal', 8), ('sell_signal', 9),
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


def build_bbands_stop_frame(df, indicator_minutes, length, deviation, money_risk):
    signal_df = build_resampled_frame(df, indicator_minutes)
    close = signal_df['close'].astype(float)
    mid = close.rolling(int(length), min_periods=int(length)).mean()
    std = close.rolling(int(length), min_periods=int(length)).std(ddof=0)
    upper = mid + float(deviation) * std
    lower = mid - float(deviation) * std
    mrisk = 0.5 * (float(money_risk) - 1.0)

    up_buffer = [math.nan] * len(signal_df)
    dn_buffer = [math.nan] * len(signal_df)
    buy_signal = [math.nan] * len(signal_df)
    sell_signal = [math.nan] * len(signal_df)

    trend = 0
    prev_smax = None
    prev_smin = None
    prev_bsmax = None
    prev_bsmin = None
    prev_up_value = 0.0
    prev_dn_value = 0.0

    highs = signal_df['high'].astype(float).tolist()
    lows = signal_df['low'].astype(float).tolist()
    closes = close.tolist()
    uppers = upper.tolist()
    lowers = lower.tolist()

    for idx in range(len(signal_df)):
        smax0 = uppers[idx]
        smin0 = lowers[idx]
        if not math.isfinite(smax0) or not math.isfinite(smin0):
            continue

        if prev_smax is None or prev_smin is None or prev_bsmax is None or prev_bsmin is None:
            prev_smax = smax0
            prev_smin = smin0
            dsize = mrisk * (smax0 - smin0)
            prev_bsmax = smax0 + dsize
            prev_bsmin = smin0 - dsize
            continue

        if closes[idx] > prev_smax:
            trend = 1
        if closes[idx] < prev_smin:
            trend = -1

        if trend > 0 and smin0 < prev_smin:
            smin0 = prev_smin
        if trend < 0 and smax0 > prev_smax:
            smax0 = prev_smax

        dsize = mrisk * (smax0 - smin0)
        bsmax0 = smax0 + dsize
        bsmin0 = smin0 - dsize

        if trend > 0 and bsmin0 < prev_bsmin:
            bsmin0 = prev_bsmin
        if trend < 0 and bsmax0 > prev_bsmax:
            bsmax0 = prev_bsmax

        current_up_value = 0.0
        current_dn_value = 0.0
        if trend > 0:
            current_up_value = bsmin0
            up_buffer[idx] = bsmin0
            if prev_up_value == 0.0:
                buy_signal[idx] = bsmin0
        elif trend < 0:
            current_dn_value = bsmax0
            dn_buffer[idx] = bsmax0
            if prev_dn_value == 0.0:
                sell_signal[idx] = bsmax0

        prev_smax = smax0
        prev_smin = smin0
        prev_bsmax = bsmax0
        prev_bsmin = bsmin0
        prev_up_value = current_up_value
        prev_dn_value = current_dn_value

    signal_df = signal_df.copy()
    signal_df['up_buffer'] = up_buffer
    signal_df['dn_buffer'] = dn_buffer
    signal_df['buy_signal'] = buy_signal
    signal_df['sell_signal'] = sell_signal
    return signal_df


class BBandsStopStrategy(bt.Strategy):
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
        length=20,
        deviation=2.0,
        money_risk=1.0,
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

    def _has_value(self, value):
        return math.isfinite(value) and not math.isnan(value) and abs(value) > 1e-12

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
        if len(self.signal) < signal_bar + 1:
            return

        current_signal_len = len(self.signal)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        recent_ago = signal_bar - 1
        prev_ago = signal_bar
        recent_up = self._line_value(self.signal.up_buffer, recent_ago)
        recent_dn = self._line_value(self.signal.dn_buffer, recent_ago)
        prev_up = self._line_value(self.signal.up_buffer, prev_ago)
        prev_dn = self._line_value(self.signal.dn_buffer, prev_ago)

        buy_signal = self._has_value(recent_up) and self._has_value(prev_dn)
        sell_signal = self._has_value(recent_dn) and self._has_value(prev_up)
        if not buy_signal and not sell_signal:
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} recent_up={recent_up:.2f} prev_dn={prev_dn:.2f}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} recent_dn={recent_dn:.2f} prev_up={prev_up:.2f}')
            if self.position.size > 0 and self.p.buy_pos_close:
                self.close()
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
