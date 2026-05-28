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


def resample_ohlcv(df, timeframe):
    timeframe = str(timeframe).lower()
    rule_map = {
        '1min': '1min',
        '5min': '5min',
        '15min': '15min',
        '30min': '30min',
        '1h': '1h',
        '4h': '4h',
        '1d': '1d',
    }
    rule = rule_map.get(timeframe, timeframe)
    agg = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'sum',
    }
    out = df.resample(rule, label='right', closed='right').agg(agg)
    return out.dropna(subset=['open', 'high', 'low', 'close'])


def applied_price_series(frame, applied_price):
    key = str(applied_price).lower()
    if key == 'open':
        return frame['open']
    if key == 'high':
        return frame['high']
    if key == 'low':
        return frame['low']
    if key == 'hl2':
        return (frame['high'] + frame['low']) / 2.0
    if key == 'hlc3':
        return (frame['high'] + frame['low'] + frame['close']) / 3.0
    if key == 'ohlc4':
        return (frame['open'] + frame['high'] + frame['low'] + frame['close']) / 4.0
    if key == 'weighted':
        return (frame['high'] + frame['low'] + 2.0 * frame['close']) / 4.0
    return frame['close']


def moving_average(series, period, method='sma'):
    method = str(method).lower()
    if method == 'ema':
        return series.ewm(span=period, adjust=False).mean()
    if method == 'smma':
        return series.ewm(alpha=1.0 / period, adjust=False).mean()
    if method == 'lwma':
        weights = pd.Series(range(1, period + 1), dtype=float)
        return series.rolling(period).apply(lambda values: (values * weights.values).sum() / weights.sum(), raw=True)
    return series.rolling(period).mean()


def compute_macd_main(series, fast_period, slow_period):
    fast = series.ewm(span=fast_period, adjust=False).mean()
    slow = series.ewm(span=slow_period, adjust=False).mean()
    return fast - slow


def compute_stochastic_signal(frame, k_period, d_period, slowing, ma_method='sma', price_field='lowhigh'):
    price_field = str(price_field).lower()
    if price_field == 'closeclose':
        highest = frame['close'].rolling(k_period).max()
        lowest = frame['close'].rolling(k_period).min()
    else:
        highest = frame['high'].rolling(k_period).max()
        lowest = frame['low'].rolling(k_period).min()
    spread = (highest - lowest).replace(0, pd.NA)
    raw_k = ((frame['close'] - lowest) / spread) * 100.0
    slow_k = moving_average(raw_k, slowing, ma_method)
    signal = moving_average(slow_k, d_period, ma_method)
    return signal.fillna(50.0)


def compute_rsi(series, period):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def build_signal_frame(
    filepath,
    fromdate=None,
    todate=None,
    bar_shift_minutes=15,
    work_timeframe='15min',
    macd_fast_period=11,
    macd_slow_period=53,
    macd_signal_period=26,
    macd_applied_price='close',
    sto_k_period=40,
    sto_d_period=23,
    sto_slowing=82,
    sto_ma_method='sma',
    sto_price_field='lowhigh',
    rsi_period=86,
    rsi_applied_price='close',
):
    base = load_mt5_csv(filepath, fromdate=fromdate, todate=todate, bar_shift_minutes=bar_shift_minutes)
    frame = resample_ohlcv(base, work_timeframe)

    macd_price = applied_price_series(frame, macd_applied_price)
    rsi_price = applied_price_series(frame, rsi_applied_price)

    frame['macd_main'] = compute_macd_main(macd_price, macd_fast_period, macd_slow_period)
    frame['sto_signal'] = compute_stochastic_signal(frame, sto_k_period, sto_d_period, sto_slowing, sto_ma_method, sto_price_field)
    frame['rsi_value'] = compute_rsi(rsi_price, rsi_period)

    frame['candle'] = 0
    frame.loc[frame['open'] > frame['open'].shift(1), 'candle'] = 1
    frame.loc[frame['open'] < frame['open'].shift(1), 'candle'] = -1

    frame['macd'] = 0
    delta_macd = frame['macd_main'] - frame['macd_main'].shift(1)
    frame.loc[delta_macd < 0, 'macd'] = 1
    frame.loc[delta_macd > 0, 'macd'] = -1

    frame['sto'] = 0
    frame.loc[frame['sto_signal'] < 50.0, 'sto'] = 1
    frame.loc[frame['sto_signal'] > 50.0, 'sto'] = -1

    frame['rsi'] = 0
    frame.loc[frame['rsi_value'] < 50.0, 'rsi'] = 1
    frame.loc[frame['rsi_value'] > 50.0, 'rsi'] = -1

    frame['buy_signal'] = (frame['candle'] >= 0) & (frame['macd'] >= 0) & (frame['sto'] >= 0) & (frame['rsi'] >= 0)
    frame['sell_signal'] = (frame['candle'] <= 0) & (frame['macd'] <= 0) & (frame['sto'] <= 0) & (frame['rsi'] <= 0)
    return frame.dropna(subset=['macd_main', 'sto_signal', 'rsi_value'])


class ThreeIndicatorsFeed(bt.feeds.PandasData):
    lines = ('candle_signal', 'macd_main', 'macd_signal_flag', 'sto_signal', 'sto_signal_flag', 'rsi_value', 'rsi_signal_flag', 'buy_signal', 'sell_signal')
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('candle_signal', 6),
        ('macd_main', 7),
        ('macd_signal_flag', 8),
        ('sto_signal', 9),
        ('sto_signal_flag', 10),
        ('rsi_value', 11),
        ('rsi_signal_flag', 12),
        ('buy_signal', 13),
        ('sell_signal', 14),
    )


class ThreeIndicatorsStrategy(bt.Strategy):
    params = dict(
        lots=1.0,
        work_timeframe='15min',
        macd_fast_period=11,
        macd_slow_period=53,
        macd_signal_period=26,
        macd_applied_price='close',
        sto_k_period=40,
        sto_d_period=23,
        sto_slowing=82,
        sto_ma_method='sma',
        sto_price_field='lowhigh',
        rsi_period=86,
        rsi_applied_price='close',
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

        buy_signal = bool(self.data.buy_signal[0])
        sell_signal = bool(self.data.sell_signal[0])
        target_size = None

        if not self.position:
            if buy_signal:
                target_size = self.p.lots
            if sell_signal:
                target_size = -self.p.lots
        elif self.position.size > 0 and sell_signal:
            target_size = -self.p.lots
        elif self.position.size < 0 and buy_signal:
            target_size = self.p.lots

        if target_size is None:
            return

        self.log(
            f'target={target_size:.2f} '
            f'candle={int(self.data.candle_signal[0])} '
            f'macd={int(self.data.macd_signal_flag[0])} '
            f'sto={int(self.data.sto_signal_flag[0])} '
            f'rsi={int(self.data.rsi_signal_flag[0])}'
        )
        self.order = self.order_target_size(target=target_size)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if self.position.size > 0:
                self.buy_count += 1
            elif self.position.size < 0:
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
