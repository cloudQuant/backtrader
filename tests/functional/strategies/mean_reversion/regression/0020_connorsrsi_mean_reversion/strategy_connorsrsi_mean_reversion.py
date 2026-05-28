from __future__ import absolute_import, division, print_function, unicode_literals

import io
from datetime import timedelta

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


def _calculate_rsi(series, period):
    delta = series.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    avg_gain = gains.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = losses.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def _calculate_streaks(close):
    diff = close.diff()
    streak = pd.Series(0.0, index=close.index)
    for idx in range(1, len(close)):
        change = diff.iloc[idx]
        previous = streak.iloc[idx - 1]
        if change > 0:
            streak.iloc[idx] = previous + 1 if previous > 0 else 1
        elif change < 0:
            streak.iloc[idx] = previous - 1 if previous < 0 else -1
        else:
            streak.iloc[idx] = 0.0
    return streak


def _calculate_percent_rank(close, rank_period):
    """计算价格在过去 rank_period 天中的百分位排名（0-100）"""
    values = []
    for idx in range(len(close)):
        if idx < rank_period:
            values.append(np.nan)
            continue
        window = close.iloc[idx - rank_period:idx]
        current = close.iloc[idx]
        if window.empty or pd.isna(current):
            values.append(np.nan)
            continue
        rank = float((window < current).sum() / len(window) * 100.0)
        values.append(rank)
    return pd.Series(values, index=close.index)


def _days_since_recent_high(high_series, lookback_days):
    values = [np.nan] * len(high_series)
    arr = high_series.to_numpy(dtype=float)
    for idx in range(lookback_days, len(arr)):
        window = arr[idx - lookback_days:idx]
        max_pos = int(np.argmax(window))
        values[idx] = lookback_days - 1 - max_pos
    return pd.Series(values, index=high_series.index)


def prepare_connors_features(df, params):
    out = df.copy()
    close = out['close']
    price_rsi = _calculate_rsi(close, int(params.get('rsi_period', 3)))
    streak_rsi = _calculate_rsi(_calculate_streaks(close), int(params.get('streak_period', 2)))
    percent_rank = _calculate_percent_rank(close, int(params.get('rank_period', 100)))
    out['crsi'] = pd.concat([price_rsi, streak_rsi, percent_rank], axis=1).mean(axis=1)
    out['rsi2'] = _calculate_rsi(close, 2)
    out['trend_ma'] = close.rolling(int(params.get('trend_ma_days', 200))).mean()
    lookback_days = int(params.get('high_lookback_weeks', 26)) * 5
    out['days_since_high'] = _days_since_recent_high(out['high'], lookback_days)
    out['setup_signal'] = (
        (out['crsi'] < float(params.get('crsi_entry', 20.0)))
        & (out['days_since_high'] <= float(params.get('recent_high_max_days', 30)))
        & (out['close'] > out['trend_ma'])
    ).astype(float)
    return out.dropna(subset=['crsi', 'rsi2', 'trend_ma', 'days_since_high'])


class Mt5ConnorsFeed(bt.feeds.PandasData):
    lines = ('crsi', 'rsi2', 'trend_ma', 'days_since_high', 'setup_signal',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('crsi', 6),
        ('rsi2', 7),
        ('trend_ma', 8),
        ('days_since_high', 9),
        ('setup_signal', 10),
    )


class ConnorsRSIMeanReversionStrategy(bt.Strategy):
    params = dict(
        high_lookback_weeks=26,
        recent_high_max_days=30,
        crsi_entry=20.0,
        entry_discount_pct=0.5,
        rsi_exit=55.0,
        trend_ma_days=200,
        rsi_period=3,
        streak_period=2,
        rank_period=100,
        lot_size=1.0,
    )

    def __init__(self):
        self.bar_num = 0
        self.setup_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.expired_count = 0
        self.cancelled_count = 0
        self.rejected_count = 0
        self.order = None
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

    def _entry_signal_ready(self):
        if len(self.data) < 1:
            return False
        return float(self.data.setup_signal[0]) > 0.5

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.order is not None:
            return
        if self.position:
            if float(self.data.rsi2[0]) >= float(self.p.rsi_exit):
                self.sell_count += 1
                self.order = self.close()
            return
        if not self._entry_signal_ready():
            return
        self.setup_count += 1
        limit_price = float(self.data.close[-1]) * (1.0 - float(self.p.entry_discount_pct) / 100.0)
        current_dt = bt.num2date(self.data.datetime[0])
        valid_until = current_dt + timedelta(days=1)
        self.order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size), price=limit_price), exectype=bt.Order.Limit, price=limit_price, valid=valid_until)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
        elif order.status == order.Expired:
            self.expired_count += 1
        elif order.status == order.Canceled:
            self.cancelled_count += 1
        elif order.status in (order.Margin, order.Rejected):
            self.rejected_count += 1
        # 无论订单状态如何，都清除挂单引用
        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
