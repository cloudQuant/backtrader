from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
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
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume'] if 'tick_volume' in df.columns else 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_high_effect_features(df, params):
    out = df.copy()
    lookback_days = int(params.get('lookback_weeks', 26)) * 5
    lower_threshold = float(params.get('lower_threshold', 0.85))
    upper_threshold = float(params.get('upper_threshold', 0.95))
    trend_ma_days = int(params.get('trend_ma_days', 200))
    rolling_high = out['high'].rolling(lookback_days).max().shift(1)
    ratio = out['close'] / rolling_high
    trend_ma = out['close'].rolling(trend_ma_days).mean()
    near_high = ((ratio >= lower_threshold) & (ratio <= upper_threshold)).astype(float)
    trend_filter = (out['close'] > trend_ma).astype(float)
    entry_signal = ((near_high > 0.5) & (trend_filter > 0.5)).astype(float)
    out['rolling_high'] = rolling_high
    out['ratio'] = ratio
    out['trend_ma'] = trend_ma
    out['near_high'] = near_high
    out['trend_filter'] = trend_filter
    out['entry_signal'] = entry_signal
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'rolling_high', 'ratio', 'trend_ma', 'near_high', 'trend_filter', 'entry_signal']].copy()
    return out.dropna()


class Mt5HighEffectFeed(bt.feeds.PandasData):
    lines = ('rolling_high', 'ratio', 'trend_ma', 'near_high', 'trend_filter', 'entry_signal',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('rolling_high', 6),
        ('ratio', 7),
        ('trend_ma', 8),
        ('near_high', 9),
        ('trend_filter', 10),
        ('entry_signal', 11),
    )


class High52WeekEffectStrategy(bt.Strategy):
    params = dict(
        lookback_weeks=26,
        lower_threshold=0.85,
        upper_threshold=0.95,
        exit_threshold=0.80,
        trend_ma_days=200,
        max_holding_days=63,
        target_percent=0.95,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_setup_count = 0
        self.exit_signal_count = 0
        self.near_high_days = 0
        self.trend_ok_days = 0
        self.days_in_position = 0
        self.pending_order = None
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
        if float(self.data.near_high[0]) > 0.5:
            self.near_high_days += 1
        if float(self.data.trend_filter[0]) > 0.5:
            self.trend_ok_days += 1
        if self.pending_order is not None:
            return
        if self.position:
            self.days_in_position += 1
            should_exit = False
            if float(self.data.ratio[0]) < float(self.p.exit_threshold):
                should_exit = True
            if float(self.data.close[0]) < float(self.data.trend_ma[0]):
                should_exit = True
            if self.days_in_position >= int(self.p.max_holding_days):
                should_exit = True
            if should_exit:
                self.exit_signal_count += 1
                self.sell_count += 1
                self.pending_order = self.close()
            return
        self.days_in_position = 0
        if float(self.data.entry_signal[0]) > 0.5:
            self.entry_setup_count += 1
            self.buy_count += 1
            self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.target_percent)))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        # 无论订单状态如何，都清除挂单引用
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.days_in_position = 0
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
