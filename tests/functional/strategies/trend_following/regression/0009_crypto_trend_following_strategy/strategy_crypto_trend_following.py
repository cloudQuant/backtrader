from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = '\n'.join(lines)
    sep = '\t' if '\t' in lines[0] else ','
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = df['<DATE>'].astype(str) + ' ' + df['<TIME>'].astype(str)
    parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M', errors='coerce')
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M:%S', errors='coerce')
    df['datetime'] = parsed
    df = df.rename(columns={
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume'] if 'tick_volume' in df.columns else 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_crypto_trend_features(df, params):
    out = df.copy()
    fast_ma = int(params.get('fast_ma', 50))
    slow_ma = int(params.get('slow_ma', 200))
    breakout_period = int(params.get('breakout_period', 50))
    atr_period = int(params.get('atr_period', 14))
    atr_multiplier = float(params.get('atr_multiplier', 2.5))
    risk_per_trade = float(params.get('risk_per_trade', 0.02))
    max_target_percent = float(params.get('max_target_percent', 1.0))

    out['ma_fast'] = out['close'].rolling(fast_ma).mean()
    out['ma_slow'] = out['close'].rolling(slow_ma).mean()
    out['donchian_high'] = out['high'].rolling(breakout_period).max().shift(1)
    out['donchian_low'] = out['low'].rolling(breakout_period).min().shift(1)

    prev_close = out['close'].shift(1)
    tr = pd.concat([
        out['high'] - out['low'],
        (out['high'] - prev_close).abs(),
        (out['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    out['atr'] = tr.rolling(atr_period).mean()

    trend_up = (out['ma_fast'] > out['ma_slow']) & (out['close'] > out['ma_slow'])
    trend_down = (out['ma_fast'] < out['ma_slow']) & (out['close'] < out['ma_slow'])
    breakout_up = out['close'] > out['donchian_high']
    breakout_down = out['close'] < out['donchian_low']

    out['signal'] = 0.0
    out.loc[trend_up & breakout_up, 'signal'] = 1.0
    out.loc[trend_down & breakout_down, 'signal'] = -1.0

    atr_fraction = (out['atr'] * atr_multiplier / out['close']).replace(0, pd.NA)
    raw_target = risk_per_trade / atr_fraction
    raw_target = raw_target.clip(lower=0.0, upper=max_target_percent)
    out['target_percent'] = raw_target.fillna(0.0) * out['signal']
    out['stop_distance_pct'] = (out['atr'] * atr_multiplier / out['close']).fillna(0.0)

    return out[[
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'ma_fast', 'ma_slow', 'donchian_high', 'donchian_low', 'atr', 'signal', 'target_percent', 'stop_distance_pct',
    ]].dropna().copy()


class CryptoTrendFeed(bt.feeds.PandasData):
    lines = ('ma_fast', 'ma_slow', 'donchian_high', 'donchian_low', 'atr', 'signal', 'target_percent', 'stop_distance_pct')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('ma_fast', 6), ('ma_slow', 7), ('donchian_high', 8), ('donchian_low', 9), ('atr', 10), ('signal', 11), ('target_percent', 12), ('stop_distance_pct', 13),
    )


class CryptoTrendFollowingStrategy(bt.Strategy):
    params = dict(
        rebalance_tolerance=0.05,
        fast_ma=50,
        slow_ma=200,
        breakout_period=50,
        atr_period=14,
        atr_multiplier=2.5,
        risk_per_trade=0.02,
        max_target_percent=1.0,
        commission_pct=0.0005,
        lot=0.1,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.broker_value_series = []
        self.long_signal_days = 0
        self.short_signal_days = 0
        self.neutral_signal_days = 0

    def _current_exposure(self):
        broker_value = float(self.broker.getvalue())
        price = float(self.data.close[0])
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if broker_value <= 0 or price <= 0 or multiplier <= 0:
            return 0.0
        return float(self.position.size) * price * multiplier / broker_value

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        signal_value = float(self.data.signal[0])
        if signal_value > 0.5:
            self.long_signal_days += 1
        elif signal_value < -0.5:
            self.short_signal_days += 1
        else:
            self.neutral_signal_days += 1
        if self.pending_order is not None:
            return
        target_percent = float(self.data.target_percent[0])
        current_exposure = self._current_exposure()
        if abs(target_percent - current_exposure) <= float(self.p.rebalance_tolerance):
            return
        if target_percent > current_exposure:
            self.buy_count += 1
        elif target_percent < current_exposure:
            self.sell_count += 1
        self.pending_order = self.order_target_percent(target=target_percent)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
