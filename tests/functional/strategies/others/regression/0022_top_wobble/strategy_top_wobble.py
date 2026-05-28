from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
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


def prepare_top_wobble_features(df, params):
    ma_period = int(params.get('ma_period', 10))
    trend_ma_period = int(params.get('trend_ma_period', 20))
    long_term_ma_period = int(params.get('long_term_ma_period', 50))
    min_consecutive_days = int(params.get('min_consecutive_days', 15))
    strong_trend_days = int(params.get('strong_trend_days', 25))
    require_above_ma20 = bool(params.get('require_above_ma20', True))
    require_above_ma50 = bool(params.get('require_above_ma50', False))
    base_position_size = float(params.get('base_position_size', 0.08))
    max_position_size = float(params.get('max_position_size', 0.12))

    out = df.copy()
    out['ma_short'] = out['close'].rolling(ma_period).mean()
    out['ma_trend'] = out['close'].rolling(trend_ma_period).mean()
    out['ma_long'] = out['close'].rolling(long_term_ma_period).mean()
    out['above_short_ma'] = (out['close'] > out['ma_short']).astype(float)

    streak = []
    current_streak = 0
    for is_above in out['above_short_ma']:
        if is_above > 0.5:
            current_streak += 1
        else:
            current_streak = 0
        streak.append(float(current_streak))
    out['consecutive_above_ma'] = streak
    out['pre_break_streak'] = out['consecutive_above_ma'].shift(1)
    out['first_break'] = (
        (out['close'] < out['ma_short'])
        & (out['close'].shift(1) > out['ma_short'].shift(1))
        & (out['pre_break_streak'] >= min_consecutive_days)
    ).astype(float)

    out['entry_signal'] = 0.0
    out['position_size_signal'] = 0.0
    out['stop_ma'] = out['ma_trend']

    for i in range(len(out)):
        if float(out['first_break'].iloc[i]) <= 0.5:
            continue
        current_close = float(out['close'].iloc[i])
        ma20 = float(out['ma_trend'].iloc[i]) if out['ma_trend'].iloc[i] == out['ma_trend'].iloc[i] else np.nan
        ma50 = float(out['ma_long'].iloc[i]) if out['ma_long'].iloc[i] == out['ma_long'].iloc[i] else np.nan
        if require_above_ma20 and (not np.isfinite(ma20) or current_close < ma20):
            continue
        if require_above_ma50 and (not np.isfinite(ma50) or current_close < ma50):
            continue
        streak_before_break = float(out['pre_break_streak'].iloc[i]) if out['pre_break_streak'].iloc[i] == out['pre_break_streak'].iloc[i] else 0.0
        pos_size = max_position_size if streak_before_break >= strong_trend_days else base_position_size
        out.iloc[i, out.columns.get_loc('entry_signal')] = 1.0
        out.iloc[i, out.columns.get_loc('position_size_signal')] = pos_size

    cols = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'ma_short', 'ma_trend', 'ma_long', 'above_short_ma', 'consecutive_above_ma',
        'pre_break_streak', 'first_break', 'entry_signal', 'position_size_signal', 'stop_ma',
    ]
    return out[cols].dropna()


class TopWobbleFeed(bt.feeds.PandasData):
    lines = ('ma_short', 'ma_trend', 'ma_long', 'above_short_ma', 'consecutive_above_ma', 'pre_break_streak', 'first_break', 'entry_signal', 'position_size_signal', 'stop_ma',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('ma_short', 6), ('ma_trend', 7), ('ma_long', 8), ('above_short_ma', 9), ('consecutive_above_ma', 10),
        ('pre_break_streak', 11), ('first_break', 12), ('entry_signal', 13), ('position_size_signal', 14), ('stop_ma', 15),
    )


class TopWobbleStrategy(bt.Strategy):
    params = dict(
        holding_days=5,
        ma_period=10,
        trend_ma_period=20,
        long_term_ma_period=50,
        min_consecutive_days=15,
        strong_trend_days=25,
        base_position_size=0.08,
        max_position_size=0.12,
        require_above_ma20=True,
        require_above_ma50=False,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.entry_bar = 0
        self.stop_price = None
        self.broker_value_series = []

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        if target_notional_pct <= 0:
            return 0.0
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * float(target_notional_pct) / (execution_price * multiplier)
        return max(0.01, round(size, 2))

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return

        low = float(self.data.low[0])
        if self.position:
            stop_ma = float(self.data.stop_ma[0]) if self.data.stop_ma[0] == self.data.stop_ma[0] else None
            if stop_ma is not None and low <= stop_ma:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.bar_num - self.entry_bar >= int(self.p.holding_days):
                self.sell_count += 1
                self.pending_order = self.close()
                return
            return

        if float(self.data.entry_signal[0]) > 0.5:
            target_pct = float(self.data.position_size_signal[0])
            self.buy_count += 1
            self.entry_bar = self.bar_num
            self.stop_price = float(self.data.stop_ma[0]) if self.data.stop_ma[0] == self.data.stop_ma[0] else None
            self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=target_pct))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.stop_price = None
