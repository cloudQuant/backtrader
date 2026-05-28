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
    if bar_shift_minutes:
        parsed = parsed + pd.to_timedelta(int(bar_shift_minutes), unit='m')
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


def prepare_overnight_features(df, params):
    out = df.copy()
    threshold = float(params.get('overnight_threshold', 0.01))
    lookback = int(params.get('overnight_lookback', 3))
    vol_window = int(params.get('vol_window', 20))
    target_volatility = max(float(params.get('target_volatility', 0.15)), 1e-6)
    base_target_percent = float(params.get('base_target_percent', 0.02))
    max_target_percent = float(params.get('max_target_percent', 0.05))

    out['overnight_return'] = out['open'] / out['close'].shift(1) - 1.0
    out['intraday_return'] = out['close'] / out['open'] - 1.0
    out['daily_return'] = out['close'].pct_change()
    out['volatility_20'] = out['daily_return'].rolling(vol_window).std() * np.sqrt(252.0)
    out['overnight_trend'] = out['overnight_return'].shift(1).rolling(lookback).mean()
    out['overnight_streak'] = np.sign(out['overnight_return'].shift(1)).rolling(lookback).sum()

    long_signal = (
        (out['overnight_return'] > 0)
        & (out['overnight_return'] < threshold)
        & (out['overnight_trend'] > 0)
        & (out['overnight_streak'] > 0)
    )
    short_signal = (
        (out['overnight_return'] < 0)
        & (out['overnight_return'] > -threshold)
        & (out['overnight_trend'] < 0)
        & (out['overnight_streak'] < 0)
    )

    vol_factor = target_volatility / out['volatility_20'].replace(0, np.nan)
    out['target_percent'] = (base_target_percent * vol_factor).clip(lower=0.0, upper=max_target_percent).fillna(0.0)
    out['long_signal'] = long_signal.astype(float)
    out['short_signal'] = short_signal.astype(float)
    out['signal'] = out['long_signal'] - out['short_signal']

    columns = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'overnight_return', 'intraday_return', 'volatility_20', 'overnight_trend',
        'overnight_streak', 'long_signal', 'short_signal', 'signal', 'target_percent',
    ]
    return out[columns].dropna().copy()


class Mt5OvernightMomentumFeed(bt.feeds.PandasData):
    lines = (
        'overnight_return', 'intraday_return', 'volatility_20', 'overnight_trend',
        'overnight_streak', 'long_signal', 'short_signal', 'signal', 'target_percent',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('overnight_return', 6), ('intraday_return', 7), ('volatility_20', 8), ('overnight_trend', 9),
        ('overnight_streak', 10), ('long_signal', 11), ('short_signal', 12), ('signal', 13), ('target_percent', 14),
    )


class GoldOvernightMomentumStrategy(bt.Strategy):
    params = dict(
        stop_loss_pct=0.01,
        take_profit_pct=0.015,
        max_consecutive_losses=5,
        pause_days_after_loss_streak=20,
        overnight_threshold=0.01,
        overnight_lookback=3,
        vol_window=20,
        target_volatility=0.15,
        base_target_percent=0.02,
        max_target_percent=0.05,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.short_count = 0
        self.cover_count = 0
        self.daily_exit_count = 0
        self.stop_exit_count = 0
        self.take_exit_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.entry_price = None
        self.entry_session_date = None
        self.current_side = 0
        self.consecutive_losses = 0
        self.pause_until_bar = -1
        self.broker_value_series = []

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        if target_notional_pct <= 0:
            return 0.0
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.open[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * float(target_notional_pct) / (execution_price * multiplier)
        return max(0.01, round(size, 2))

    def next_open(self):
        if self.pending_order is not None or self.position:
            return
        if self.bar_num < 1 or self.bar_num <= self.pause_until_bar:
            return

        long_signal = float(self.data.long_signal[0]) > 0.5
        short_signal = float(self.data.short_signal[0]) > 0.5
        target_percent = float(self.data.target_percent[0])
        size = self._get_position_size(target_notional_pct=target_percent, price=float(self.data.open[0]))
        if size <= 0:
            return

        if long_signal:
            self.buy_count += 1
            self.current_side = 1
            self.entry_price = float(self.data.open[0])
            self.entry_session_date = bt.num2date(self.data.datetime[0]).date()
            self.pending_order = self.buy(size=size)
        elif short_signal:
            self.short_count += 1
            self.current_side = -1
            self.entry_price = float(self.data.open[0])
            self.entry_session_date = bt.num2date(self.data.datetime[0]).date()
            self.pending_order = self.sell(size=size)

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        current_session_date = bt.num2date(self.data.datetime[0]).date()
        if not self.position or self.entry_session_date != current_session_date:
            return

        if self.current_side > 0:
            stop_hit = float(self.data.low[0]) <= self.entry_price * (1.0 - float(self.p.stop_loss_pct))
            take_hit = float(self.data.high[0]) >= self.entry_price * (1.0 + float(self.p.take_profit_pct))
            self.sell_count += 1
        else:
            stop_hit = float(self.data.high[0]) >= self.entry_price * (1.0 + float(self.p.stop_loss_pct))
            take_hit = float(self.data.low[0]) <= self.entry_price * (1.0 - float(self.p.take_profit_pct))
            self.cover_count += 1

        if stop_hit:
            self.stop_exit_count += 1
        elif take_hit:
            self.take_exit_count += 1
        else:
            self.daily_exit_count += 1
        self.pending_order = self.close()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status in (order.Canceled, order.Margin, order.Rejected):
            if not self.position:
                self.entry_price = None
                self.entry_session_date = None
                self.current_side = 0
        if order.status == order.Completed and not self.position:
            self.entry_price = None
            self.entry_session_date = None
            self.current_side = 0
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
            self.consecutive_losses = 0
        else:
            self.loss_count += 1
            self.consecutive_losses += 1
            if self.consecutive_losses >= int(self.p.max_consecutive_losses):
                self.pause_until_bar = self.bar_num + int(self.p.pause_days_after_loss_streak)
                self.consecutive_losses = 0
