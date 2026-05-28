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


def prepare_modified_hikkake_features(df, params):
    trend_ma_period = int(params.get('trend_ma_period', 50))
    atr_period = int(params.get('atr_period', 14))
    atr_min_ratio = float(params.get('atr_min_ratio', 0.5))
    atr_max_ratio = float(params.get('atr_max_ratio', 2.0))

    out = df.copy()
    out['inside_bar'] = ((out['high'] < out['high'].shift(1)) & (out['low'] > out['low'].shift(1))).astype(float)
    tr = pd.concat([
        out['high'] - out['low'],
        (out['high'] - out['close'].shift(1)).abs(),
        (out['low'] - out['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    out['atr'] = tr.rolling(atr_period).mean()
    out['avg_atr'] = out['atr'].rolling(100, min_periods=20).mean()
    out['relative_atr'] = out['atr'] / out['avg_atr'].replace(0, np.nan)
    out['trend_ma'] = out['close'].rolling(trend_ma_period).mean()

    out['hikkake_direction'] = 0.0
    out['inside_high'] = np.nan
    out['inside_low'] = np.nan
    out['entry_signal'] = 0.0

    for i in range(2, len(out)):
        if float(out['inside_bar'].iloc[i - 1]) <= 0.5:
            continue
        inside_high = float(out['high'].iloc[i - 1])
        inside_low = float(out['low'].iloc[i - 1])
        current_close = float(out['close'].iloc[i])
        current_price = float(out['close'].iloc[i])
        trend_ma = float(out['trend_ma'].iloc[i]) if out['trend_ma'].iloc[i] == out['trend_ma'].iloc[i] else np.nan
        rel_atr = float(out['relative_atr'].iloc[i]) if out['relative_atr'].iloc[i] == out['relative_atr'].iloc[i] else np.nan
        if not np.isfinite(rel_atr) or rel_atr < atr_min_ratio or rel_atr > atr_max_ratio:
            continue
        direction = 0.0
        if float(out['high'].iloc[i]) > inside_high and current_close < inside_high and np.isfinite(trend_ma) and current_price < trend_ma:
            direction = -1.0
        elif float(out['low'].iloc[i]) < inside_low and current_close > inside_low and np.isfinite(trend_ma) and current_price > trend_ma:
            direction = 1.0
        if direction == 0.0:
            continue
        out.iloc[i, out.columns.get_loc('hikkake_direction')] = direction
        out.iloc[i, out.columns.get_loc('inside_high')] = inside_high
        out.iloc[i, out.columns.get_loc('inside_low')] = inside_low
        out.iloc[i, out.columns.get_loc('entry_signal')] = 1.0

    cols = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'inside_bar', 'atr', 'avg_atr', 'relative_atr', 'trend_ma',
        'hikkake_direction', 'inside_high', 'inside_low', 'entry_signal',
    ]
    return out[cols].dropna()


class ModifiedHikkakeFeed(bt.feeds.PandasData):
    lines = ('inside_bar', 'atr', 'avg_atr', 'relative_atr', 'trend_ma', 'hikkake_direction', 'inside_high', 'inside_low', 'entry_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('inside_bar', 6), ('atr', 7), ('avg_atr', 8), ('relative_atr', 9), ('trend_ma', 10),
        ('hikkake_direction', 11), ('inside_high', 12), ('inside_low', 13), ('entry_signal', 14),
    )


class ModifiedHikkakeStrategy(bt.Strategy):
    params = dict(
        stop_loss_atr=1.5,
        take_profit_ratio=2.0,
        max_holding_bars=8,
        position_size=0.95,
        trend_ma_period=50,
        atr_period=14,
        atr_min_ratio=0.5,
        atr_max_ratio=2.0,
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
        self.take_profit_price = None
        self.trade_direction = 0
        self.broker_value_series = []

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        direction = 1.0 if target_notional_pct >= 0 else -1.0
        size = broker_value * abs(float(target_notional_pct)) / (execution_price * multiplier)
        return direction * round(size, 2)

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return

        low = float(self.data.low[0])
        high = float(self.data.high[0])
        close = float(self.data.close[0])

        if self.position:
            if self.trade_direction > 0:
                if self.stop_price is not None and low <= self.stop_price:
                    self.sell_count += 1
                    self.pending_order = self.close()
                    return
                if self.take_profit_price is not None and high >= self.take_profit_price:
                    self.sell_count += 1
                    self.pending_order = self.close()
                    return
            elif self.trade_direction < 0:
                if self.stop_price is not None and high >= self.stop_price:
                    self.buy_count += 1
                    self.pending_order = self.close()
                    return
                if self.take_profit_price is not None and low <= self.take_profit_price:
                    self.buy_count += 1
                    self.pending_order = self.close()
                    return
            if self.bar_num - self.entry_bar >= int(self.p.max_holding_bars):
                if self.trade_direction > 0:
                    self.sell_count += 1
                else:
                    self.buy_count += 1
                self.pending_order = self.close()
                return
            return

        if float(self.data.entry_signal[0]) > 0.5:
            direction = int(float(self.data.hikkake_direction[0]))
            atr = float(self.data.atr[0]) if self.data.atr[0] == self.data.atr[0] else close * 0.01
            self.entry_bar = self.bar_num
            self.entry_price = close
            self.trade_direction = direction
            if direction > 0:
                self.stop_price = close - float(self.p.stop_loss_atr) * atr
                self.take_profit_price = close + float(self.p.stop_loss_atr) * float(self.p.take_profit_ratio) * atr
                self.buy_count += 1
            else:
                self.stop_price = close + float(self.p.stop_loss_atr) * atr
                self.take_profit_price = close - float(self.p.stop_loss_atr) * float(self.p.take_profit_ratio) * atr
                self.sell_count += 1
            target_size = self._get_position_size(target_notional_pct=float(self.p.position_size) * direction)
            self.pending_order = self.order_target_size(target=target_size)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.stop_price = None
            self.take_profit_price = None
            self.trade_direction = 0
