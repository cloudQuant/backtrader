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

MODE_BREAKDOWN = 0
MODE_OSC_TWIST = 1
MODE_SIGNAL_TWIST = 2
MODE_OSC_DISPOSITION = 3
MODE_SIGNAL_BREAKDOWN = 4

DMETHOD_SMA = 0
DMETHOD_EMA = 1
PRICE_LOWHIGH = 0
PRICE_CLOSECLOSE = 1


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


class ColorStochNrFeed(btfeeds.PandasData):
    lines = ('up_stoh', 'dn_stoh', 'color_stoh', 'sign', 'color_sign')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('up_stoh', 6), ('dn_stoh', 7), ('color_stoh', 8), ('sign', 9), ('color_sign', 10),
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


def stoch_value(kperiod, slowing, price_field, sens, high, low, close, index):
    max_value = 0.0
    min_value = 0.0
    close_sum = 0.0
    for j in range(index, index + int(slowing)):
        if int(price_field) == PRICE_CLOSECLOSE:
            window_close = close[j:j + int(kperiod)]
            max_value += max(window_close)
            min_value += min(window_close)
        else:
            window_high = high[j:j + int(kperiod)]
            window_low = low[j:j + int(kperiod)]
            max_value += max(window_high)
            min_value += min(window_low)
        close_sum += close[j]

    delta = max_value - min_value
    if delta < sens:
        sens2 = sens / 2.0
        max_value += sens2
        min_value -= sens2
    delta = max_value - min_value
    if delta:
        s0 = (close_sum - min_value) / delta
    else:
        s0 = 1.0
    return 100.0 * s0


def build_color_stoch_nr_frame(df, indicator_minutes, kperiod, dperiod, slowing, dmethod, price_field, sens_points, point):
    signal_df = build_resampled_frame(df, indicator_minutes)
    n = len(signal_df)
    up = [math.nan] * n
    dn = [math.nan] * n
    color_stoh = [math.nan] * n
    sign = [math.nan] * n
    color_sign = [math.nan] * n
    sens = float(sens_points) * float(point)
    kd = 2.0 / (1.0 + float(dperiod)) if int(dmethod) == DMETHOD_EMA else None
    min_rates_total = int(kperiod + dperiod + slowing + 1)

    high_rev = signal_df['high'].astype(float).iloc[::-1].tolist()
    low_rev = signal_df['low'].astype(float).iloc[::-1].tolist()
    close_rev = signal_df['close'].astype(float).iloc[::-1].tolist()
    up_rev = [50.0] * n
    dn_rev = [50.0] * n
    sign_rev = [math.nan] * n
    color_stoh_rev = [math.nan] * n
    color_sign_rev = [math.nan] * n

    if n <= min_rates_total:
        out = signal_df.copy()
        out['up_stoh'] = up
        out['dn_stoh'] = dn
        out['color_stoh'] = color_stoh
        out['sign'] = sign
        out['color_sign'] = color_sign
        return out

    limit = n - min_rates_total - 1
    sign_rev[limit + 1] = 50.0
    for bar in range(n - 1, limit, -1):
        up_rev[bar] = 50.0
        dn_rev[bar] = 50.0

    for bar in range(limit, -1, -1):
        main = stoch_value(kperiod, slowing, price_field, sens, high_rev, low_rev, close_rev, bar)
        if main < 50:
            dn_rev[bar] = main
            up_rev[bar] = 50.0
        else:
            up_rev[bar] = main
            dn_rev[bar] = 50.0

        if int(dmethod) == DMETHOD_EMA:
            next_sign = sign_rev[bar + 1] if bar + 1 < n and math.isfinite(sign_rev[bar + 1]) else 50.0
            sign_rev[bar] = kd * main + (1.0 - kd) * next_sign
        else:
            sh = int(bar + dperiod)
            old_main = up_rev[sh] + dn_rev[sh] - 50.0 if sh < n else 50.0
            next_sign = sign_rev[bar + 1] if bar + 1 < n and math.isfinite(sign_rev[bar + 1]) else 50.0
            sum_value = next_sign * float(dperiod) - old_main
            sign_rev[bar] = (sum_value + main) / float(dperiod)

    if limit >= 0:
        limit2 = limit - 1
    else:
        limit2 = limit
    for bar in range(limit2, -1, -1):
        main = up_rev[bar] + dn_rev[bar] - 50.0
        prev_main = up_rev[bar + 1] + dn_rev[bar + 1] - 50.0
        color_stoh_rev[bar] = 0.0
        if main > 50:
            if main > prev_main:
                color_stoh_rev[bar] = 1.0
            if main < prev_main:
                color_stoh_rev[bar] = 2.0
        if main < 50:
            if main < prev_main:
                color_stoh_rev[bar] = 3.0
            if main > prev_main:
                color_stoh_rev[bar] = 4.0

    for bar in range(limit2, -1, -1):
        main = up_rev[bar] + dn_rev[bar] - 50.0
        color_sign_rev[bar] = 0.0
        if main > sign_rev[bar]:
            color_sign_rev[bar] = 1.0
        if main < sign_rev[bar]:
            color_sign_rev[bar] = 2.0

    out = signal_df.copy()
    out['up_stoh'] = list(reversed(up_rev))
    out['dn_stoh'] = list(reversed(dn_rev))
    out['color_stoh'] = list(reversed(color_stoh_rev))
    out['sign'] = list(reversed(sign_rev))
    out['color_sign'] = list(reversed(color_sign_rev))
    return out


class ColorStochNrStrategy(bt.Strategy):
    params = dict(
        mode=MODE_OSC_DISPOSITION,
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
        kperiod=5,
        dperiod=3,
        slowing=3,
        dmethod=0,
        price_field=0,
        sens_points=0,
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
        if len(self.signal) < signal_bar + 2:
            return

        current_signal_len = len(self.signal)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        recent_ago = signal_bar - 1
        prev_ago = signal_bar
        old_ago = signal_bar + 1
        up_recent = self._line_value(self.signal.up_stoh, recent_ago)
        dn_recent = self._line_value(self.signal.dn_stoh, recent_ago)
        up_prev = self._line_value(self.signal.up_stoh, prev_ago)
        dn_prev = self._line_value(self.signal.dn_stoh, prev_ago)
        color_recent = self._line_value(self.signal.color_stoh, recent_ago)
        color_prev = self._line_value(self.signal.color_stoh, prev_ago)
        sign_recent = self._line_value(self.signal.sign, recent_ago)
        sign_prev = self._line_value(self.signal.sign, prev_ago)
        sign_old = self._line_value(self.signal.sign, old_ago)
        color_sign_recent = self._line_value(self.signal.color_sign, recent_ago)
        color_sign_prev = self._line_value(self.signal.color_sign, prev_ago)
        if not all(math.isfinite(v) for v in [up_recent, dn_recent, up_prev, dn_prev, color_recent, color_prev, sign_recent, sign_prev, sign_old, color_sign_recent, color_sign_prev]):
            return

        color_recent = int(round(color_recent))
        color_prev = int(round(color_prev))
        color_sign_recent = int(round(color_sign_recent))
        color_sign_prev = int(round(color_sign_prev))

        buy_signal = False
        sell_signal = False
        mode = int(self.p.mode)
        if mode == MODE_BREAKDOWN:
            buy_signal = up_prev > 50 and dn_recent <= 50
            sell_signal = dn_prev < 50 and up_recent >= 50
        elif mode == MODE_OSC_TWIST:
            buy_signal = ((color_prev == 1 and color_recent > 1) or (color_prev == 2 and color_recent > 2) or (color_prev == 3 and color_recent == 4)) and (color_recent > color_prev)
            sell_signal = ((color_prev == 4 and (color_recent < 4 and color_recent != 0)) or (color_prev == 3 and (color_recent < 3 and color_recent != 0)) or (color_prev == 2 and color_recent <= 1)) and (color_recent < color_prev)
        elif mode == MODE_SIGNAL_TWIST:
            buy_signal = sign_prev < sign_old and sign_recent > sign_prev
            sell_signal = sign_prev > sign_old and sign_recent < sign_prev
        elif mode == MODE_OSC_DISPOSITION:
            buy_signal = color_sign_prev == 1 and (color_sign_recent == 2 or color_sign_recent != 0)
            sell_signal = color_sign_prev == 2 and (color_sign_recent == 1 or color_sign_recent != 0)
        else:
            buy_signal = sign_prev > 50 and sign_recent <= 50
            sell_signal = sign_prev < 50 and sign_recent >= 50

        if not buy_signal and not sell_signal:
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} mode={mode}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} mode={mode}')
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
