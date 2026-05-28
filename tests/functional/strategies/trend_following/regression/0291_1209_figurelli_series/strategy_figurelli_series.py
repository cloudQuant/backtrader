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


class FigurelliSeriesFeed(btfeeds.PandasData):
    lines = ('figurelli',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('figurelli', 6),
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


def applied_price_series(df, applied_price):
    price = str(applied_price).upper()
    if price == 'PRICE_OPEN':
        return df['open'].astype(float)
    if price == 'PRICE_HIGH':
        return df['high'].astype(float)
    if price == 'PRICE_LOW':
        return df['low'].astype(float)
    if price == 'PRICE_MEDIAN':
        return (df['high'].astype(float) + df['low'].astype(float)) / 2.0
    if price == 'PRICE_WEIGHTED':
        return (df['high'].astype(float) + df['low'].astype(float) + df['close'].astype(float) * 2.0) / 4.0
    if price == 'PRICE_TYPICAL':
        return (df['high'].astype(float) + df['low'].astype(float) + df['close'].astype(float)) / 3.0
    return df['close'].astype(float)


def moving_average(series, period, method='ema'):
    period = int(period)
    s = pd.Series(series, dtype=float)
    method = str(method).lower()
    if method == 'sma':
        return s.rolling(period).mean()
    if method == 'smma':
        result = [math.nan] * len(s)
        if len(s) < period:
            return pd.Series(result, dtype=float)
        seed = s.iloc[:period].mean()
        result[period - 1] = seed
        prev = seed
        for idx in range(period, len(s)):
            prev = (prev * (period - 1) + s.iloc[idx]) / period
            result[idx] = prev
        return pd.Series(result, dtype=float)
    if method == 'lwma':
        weights = list(range(1, period + 1))
        denom = sum(weights)
        result = [math.nan] * len(s)
        for idx in range(period - 1, len(s)):
            window = s.iloc[idx - period + 1:idx + 1].tolist()
            result[idx] = sum(v * w for v, w in zip(window, weights)) / denom
        return pd.Series(result, dtype=float)
    return s.ewm(span=period, adjust=False).mean()


def build_figurelli_series_frame(df, indicator_minutes, start_period, step, total, ma_type, ma_price):
    signal_df = build_resampled_frame(df, indicator_minutes)
    price = applied_price_series(signal_df, ma_price)
    ma_frames = []
    periods = []
    for count in range(int(total)):
        period = int(start_period + step * count)
        periods.append(period)
        ma_frames.append(moving_average(price, period, method=ma_type))
    min_rates_total = int(start_period + step * (int(total) - 1))

    figurelli = [math.nan] * len(signal_df)
    for idx in range(len(signal_df)):
        if idx < min_rates_total - 1:
            continue
        tot_ask = 0
        tot_bid = 0
        close_value = float(signal_df['close'].iloc[idx])
        valid = True
        for ma in ma_frames:
            ma_value = float(ma.iloc[idx]) if math.isfinite(float(ma.iloc[idx])) else math.nan
            if not math.isfinite(ma_value):
                valid = False
                break
            if close_value < ma_value:
                tot_ask += 1
            if close_value > ma_value:
                tot_bid += 1
        if valid:
            figurelli[idx] = float(tot_bid - tot_ask)

    out = signal_df.copy()
    out['figurelli'] = figurelli
    return out


class FigurelliSeriesStrategy(bt.Strategy):
    params = dict(
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        mm=0.1,
        point=0.01,
        start_hour=8,
        start_minute=0,
        stop_hour=23,
        stop_minute=59,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=30,
        start_period=6,
        step=6,
        total=36,
        ma_type='ema',
        ma_price='PRICE_CLOSE',
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
        self._last_base_dt = None

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
        current_dt = bt.num2date(self.base.datetime[0])
        if self._last_base_dt == current_dt:
            return
        self._last_base_dt = current_dt

        if len(self.signal) < max(int(self.p.signal_bar), 1):
            return

        if self._check_exit_levels():
            return

        signal_ago = max(int(self.p.signal_bar), 1) - 1
        ind_value = self._line_value(self.signal.figurelli, signal_ago)
        if not math.isfinite(ind_value):
            return

        buy_open1 = ind_value > 0
        sell_open1 = ind_value < 0
        buy_close = sell_open1 and self.p.buy_pos_close
        sell_close = buy_open1 and self.p.sell_pos_close

        if current_dt.hour == int(self.p.stop_hour) and current_dt.minute >= int(self.p.stop_minute) or current_dt.hour > int(self.p.stop_hour) or current_dt.hour < int(self.p.start_hour):
            if self.position.size > 0 and self.p.buy_pos_close:
                self.close()
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            return

        if buy_close and self.position.size > 0:
            self.close()
        if sell_close and self.position.size < 0:
            self.close()

        if current_dt.hour != int(self.p.start_hour) or current_dt.minute != int(self.p.start_minute):
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if buy_open1:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} figurelli={ind_value:.2f}')
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if sell_open1:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} figurelli={ind_value:.2f}')
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
