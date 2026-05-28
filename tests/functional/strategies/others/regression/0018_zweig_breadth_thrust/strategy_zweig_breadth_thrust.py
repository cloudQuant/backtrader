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
    df = df.rename(columns={'<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close', '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume'})
    df['openinterest'] = 0
    df['volume'] = df['tick_volume'] if 'tick_volume' in df.columns else 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_zweig_features(df, params):
    ema_period = int(params.get('ema_period', 10))
    low_threshold = float(params.get('low_threshold', 0.40))
    high_threshold = float(params.get('high_threshold', 0.615))
    lookback_days = int(params.get('lookback_days', 10))
    out = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    out['ret_1'] = out['close'].pct_change(1)
    out['ret_3'] = out['close'].pct_change(3)
    out['ret_5'] = out['close'].pct_change(5)
    out['ret_10'] = out['close'].pct_change(10)
    out['ma_5'] = out['close'].rolling(5).mean()
    out['ma_20'] = out['close'].rolling(20).mean()
    signals = pd.DataFrame(index=out.index)
    signals['s1'] = (out['ret_1'] > 0).astype(float)
    signals['s2'] = (out['ret_3'] > 0).astype(float)
    signals['s3'] = (out['ret_5'] > 0).astype(float)
    signals['s4'] = (out['ret_10'] > 0).astype(float)
    signals['s5'] = (out['close'] > out['ma_5']).astype(float)
    signals['s6'] = (out['ma_5'] > out['ma_20']).astype(float)
    out['up_pct_proxy'] = signals.mean(axis=1)
    out['breadth_ema'] = out['up_pct_proxy'].ewm(span=ema_period, adjust=False).mean()
    out['was_below_low'] = (out['breadth_ema'].rolling(lookback_days).min() < low_threshold).astype(float)
    above_high = out['breadth_ema'] >= high_threshold
    out['thrust_signal'] = (above_high & (out['was_below_low'] > 0.5) & (~above_high.shift(1).fillna(False))).astype(float)
    return out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'up_pct_proxy', 'breadth_ema', 'was_below_low', 'thrust_signal']].dropna().copy()


class ZweigBreadthFeed(bt.feeds.PandasData):
    lines = ('up_pct_proxy', 'breadth_ema', 'was_below_low', 'thrust_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('up_pct_proxy', 6), ('breadth_ema', 7), ('was_below_low', 8), ('thrust_signal', 9),
    )


class ZweigBreadthThrustStrategy(bt.Strategy):
    params = dict(
        holding_days=20,
        stop_loss_pct=0.03,
        position_size=0.90,
        ema_period=10,
        low_threshold=0.4,
        high_threshold=0.615,
        lookback_days=10,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.entry_bar = 0
        self.entry_price = None
        self.stop_price = None
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        low = float(self.data.low[0])
        close = float(self.data.close[0])
        if self.position:
            if self.stop_price is not None and low <= self.stop_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.bar_num - self.entry_bar >= int(self.p.holding_days):
                self.sell_count += 1
                self.pending_order = self.close()
                return
            return
        if float(self.data.thrust_signal[0]) > 0.5:
            self.entry_bar = self.bar_num
            self.entry_price = close
            self.stop_price = close * (1.0 - float(self.p.stop_loss_pct))
            self.buy_count += 1
            self.pending_order = self.order_target_percent(target=float(self.p.position_size))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.stop_price = None
