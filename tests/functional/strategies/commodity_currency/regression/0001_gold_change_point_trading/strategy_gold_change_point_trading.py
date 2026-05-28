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
    df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_change_point_features(df, params):
    out = df.copy()
    detection_window = int(params.get('detection_window', 60))
    confirm_days = int(params.get('confirm_days', 3))
    min_change_gap = int(params.get('min_change_gap', 20))
    t_stat_threshold = float(params.get('t_stat_threshold', 1.0))
    vol_switch_threshold = float(params.get('vol_switch_threshold', 1.4))
    target_volatility = max(float(params.get('target_volatility', 0.15)), 1e-6)
    base_target_percent = float(params.get('base_target_percent', 0.02))
    max_target_percent = float(params.get('max_target_percent', 0.05))

    out['returns'] = out['close'].pct_change()
    prev_mean = out['returns'].shift(confirm_days).rolling(window=detection_window).mean()
    recent_mean = out['returns'].rolling(window=confirm_days).mean()
    prev_std = out['returns'].shift(confirm_days).rolling(window=detection_window).std()
    recent_std = out['returns'].rolling(window=confirm_days).std()

    pooled_std = np.sqrt(((prev_std ** 2) + (recent_std ** 2)) / 2.0)
    mean_shift = recent_mean - prev_mean
    t_like_stat = mean_shift / pooled_std.replace(0, np.nan)
    vol_ratio = recent_std / prev_std.replace(0, np.nan)
    up_confirm = (out['returns'] > 0).rolling(window=confirm_days).sum() == confirm_days
    down_confirm = (out['returns'] < 0).rolling(window=confirm_days).sum() == confirm_days

    raw_long = (t_like_stat > t_stat_threshold) & up_confirm
    raw_short = (t_like_stat < -t_stat_threshold) & down_confirm
    raw_high_vol = (vol_ratio > vol_switch_threshold) & (recent_std > prev_std)

    long_signal = []
    short_signal = []
    high_vol_exit = []
    last_change_idx = -10 ** 9
    index_list = list(range(len(out)))
    for idx, long_flag, short_flag, high_vol_flag in zip(index_list, raw_long.fillna(False), raw_short.fillna(False), raw_high_vol.fillna(False)):
        allowed = (idx - last_change_idx) >= min_change_gap
        long_now = bool(long_flag and allowed)
        short_now = bool(short_flag and allowed and not long_now)
        high_vol_now = bool(high_vol_flag and allowed and not long_now and not short_now)
        if long_now or short_now or high_vol_now:
            last_change_idx = idx
        long_signal.append(1.0 if long_now else 0.0)
        short_signal.append(1.0 if short_now else 0.0)
        high_vol_exit.append(1.0 if high_vol_now else 0.0)

    actual_vol = recent_std * np.sqrt(252.0)
    vol_scaler = (target_volatility / actual_vol.replace(0, np.nan)).clip(lower=0.0, upper=max_target_percent / max(base_target_percent, 1e-6))
    target_percent = (base_target_percent * vol_scaler).clip(upper=max_target_percent).fillna(0.0)
    target_percent[(pd.Series(long_signal, index=out.index) <= 0.5) & (pd.Series(short_signal, index=out.index) <= 0.5)] = 0.0

    out['prev_mean'] = prev_mean.astype(float)
    out['recent_mean'] = recent_mean.astype(float)
    out['prev_std'] = prev_std.astype(float)
    out['recent_std'] = recent_std.astype(float)
    out['t_like_stat'] = t_like_stat.astype(float)
    out['vol_ratio'] = vol_ratio.astype(float)
    out['long_signal'] = pd.Series(long_signal, index=out.index, dtype='float64')
    out['short_signal'] = pd.Series(short_signal, index=out.index, dtype='float64')
    out['high_vol_exit'] = pd.Series(high_vol_exit, index=out.index, dtype='float64')
    out['target_percent'] = pd.Series(target_percent, index=out.index, dtype='float64')

    columns = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'prev_mean', 'recent_mean', 'prev_std', 'recent_std', 't_like_stat', 'vol_ratio',
        'long_signal', 'short_signal', 'high_vol_exit', 'target_percent',
    ]
    return out[columns].copy().dropna()


class Mt5ChangePointFeed(bt.feeds.PandasData):
    lines = (
        'prev_mean', 'recent_mean', 'prev_std', 'recent_std', 't_like_stat', 'vol_ratio',
        'long_signal', 'short_signal', 'high_vol_exit', 'target_percent',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('prev_mean', 6), ('recent_mean', 7), ('prev_std', 8), ('recent_std', 9), ('t_like_stat', 10), ('vol_ratio', 11),
        ('long_signal', 12), ('short_signal', 13), ('high_vol_exit', 14), ('target_percent', 15),
    )


class GoldChangePointStrategy(bt.Strategy):
    params = dict(
        stop_loss_pct=0.02,
        take_profit_pct=0.05,
        detection_window=60,
        confirm_days=3,
        min_change_gap=20,
        t_stat_threshold=1.0,
        vol_switch_threshold=1.4,
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
        self.long_signal_count = 0
        self.short_signal_count = 0
        self.high_vol_exit_count = 0
        self.stop_exit_count = 0
        self.reverse_exit_count = 0
        self.pending_order = None
        self.entry_price = None
        self.break_even_armed = False
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

        close_price = float(self.data.close[0])
        long_signal = float(self.data.long_signal[0]) > 0.5
        short_signal = float(self.data.short_signal[0]) > 0.5
        high_vol_exit = float(self.data.high_vol_exit[0]) > 0.5
        target_percent = float(self.data.target_percent[0])

        if self.position:
            pnl_pct = (close_price / self.entry_price - 1.0) if self.entry_price else 0.0
            if self.position.size < 0:
                pnl_pct = -pnl_pct
            if not self.break_even_armed and pnl_pct >= float(self.p.take_profit_pct):
                self.break_even_armed = True
            stop_limit = 0.0 if self.break_even_armed else -float(self.p.stop_loss_pct)
            if pnl_pct <= stop_limit:
                if self.position.size > 0:
                    self.sell_count += 1
                else:
                    self.cover_count += 1
                self.stop_exit_count += 1
                self.pending_order = self.close()
                return
            if high_vol_exit:
                if self.position.size > 0:
                    self.sell_count += 1
                else:
                    self.cover_count += 1
                self.high_vol_exit_count += 1
                self.pending_order = self.close()
                return
            if (self.position.size > 0 and short_signal) or (self.position.size < 0 and long_signal):
                if self.position.size > 0:
                    self.sell_count += 1
                else:
                    self.cover_count += 1
                self.reverse_exit_count += 1
                self.pending_order = self.close()
                return
            return

        if target_percent <= 0:
            return
        size = self._get_position_size(target_notional_pct=target_percent)
        if size <= 0:
            return
        if long_signal:
            self.long_signal_count += 1
            self.buy_count += 1
            self.pending_order = self.buy(size=size)
            return
        if short_signal:
            self.short_signal_count += 1
            self.short_count += 1
            self.pending_order = self.sell(size=size)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if self.position:
                self.entry_price = float(order.executed.price)
                self.break_even_armed = False
            else:
                self.entry_price = None
                self.break_even_armed = False
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
