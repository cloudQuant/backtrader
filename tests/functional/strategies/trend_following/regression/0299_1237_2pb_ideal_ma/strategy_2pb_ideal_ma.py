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


class TwoPbIdealMAFeed(btfeeds.PandasData):
    lines = ('fast_ma', 'slow_ma')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('fast_ma', 6), ('slow_ma', 7),
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


def ideal_ma_smooth(weight_1, weight_2, series_1, series_0, result_1):
    dseries = series_0 - series_1
    dseries2 = dseries * dseries - 1.0
    denominator = 1.0 + weight_2 * dseries2
    if abs(denominator) <= 1e-12:
        return result_1
    return (
        weight_1 * (series_0 - result_1)
        + result_1
        + weight_2 * result_1 * dseries2
    ) / denominator


def build_fast_ideal_ma(price_series, period1, period2):
    weight_1 = 1.0 / max(1, int(period1))
    weight_2 = 1.0 / max(1, int(period2))
    values = price_series.astype(float).tolist()
    result = [math.nan] * len(values)
    if not values:
        return result
    result[0] = values[0]
    for idx in range(1, len(values)):
        result[idx] = ideal_ma_smooth(weight_1, weight_2, values[idx - 1], values[idx], result[idx - 1])
    return result


def build_slow_ideal_ma(price_series, periodx1, periodx2, periody1, periody2, periodz1, periodz2):
    wx1 = 1.0 / max(1, int(periodx1))
    wx2 = 1.0 / max(1, int(periodx2))
    wy1 = 1.0 / max(1, int(periody1))
    wy2 = 1.0 / max(1, int(periody2))
    wz1 = 1.0 / max(1, int(periodz1))
    wz2 = 1.0 / max(1, int(periodz2))
    values = price_series.astype(float).tolist()
    result = [math.nan] * len(values)
    if not values:
        return result

    result[0] = values[0]
    moving01 = values[0]
    moving11 = values[0]
    moving21 = values[0]
    for idx in range(1, len(values)):
        moving00 = ideal_ma_smooth(wx1, wx2, values[idx - 1], values[idx], moving01)
        moving10 = ideal_ma_smooth(wy1, wy2, moving01, moving00, moving11)
        moving20 = ideal_ma_smooth(wz1, wz2, moving11, moving10, moving21)
        moving01 = moving00
        moving11 = moving10
        moving21 = moving20
        result[idx] = moving20
    return result


def build_2pb_ideal_ma_frame(df, indicator_minutes, period1, period2, periodx1, periodx2, periody1, periody2, periodz1, periodz2):
    signal_df = build_resampled_frame(df, indicator_minutes)
    price_series = signal_df['close'].astype(float)
    signal_df = signal_df.copy()
    signal_df['fast_ma'] = build_fast_ideal_ma(price_series, period1, period2)
    signal_df['slow_ma'] = build_slow_ideal_ma(price_series, periodx1, periodx2, periody1, periody2, periodz1, periodz2)
    return signal_df


class TwoPbIdealMAStrategy(bt.Strategy):
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
        period1=10,
        period2=10,
        periodx1=10,
        periodx2=10,
        periody1=10,
        periody2=10,
        periodz1=10,
        periodz2=10,
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
        if len(self.signal) < signal_bar + 1:
            return

        current_signal_len = len(self.signal)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        recent_ago = signal_bar - 1
        prev_ago = signal_bar
        fast_recent = self._line_value(self.signal.fast_ma, recent_ago)
        slow_recent = self._line_value(self.signal.slow_ma, recent_ago)
        fast_prev = self._line_value(self.signal.fast_ma, prev_ago)
        slow_prev = self._line_value(self.signal.slow_ma, prev_ago)
        if not all(math.isfinite(v) for v in [fast_recent, slow_recent, fast_prev, slow_prev]):
            return

        buy_signal = fast_recent > slow_recent and fast_prev < slow_prev
        sell_signal = fast_recent < slow_recent and fast_prev > slow_prev
        if not buy_signal and not sell_signal:
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} fast={fast_recent:.2f} slow={slow_recent:.2f}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} fast={fast_recent:.2f} slow={slow_recent:.2f}')
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
