from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
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


def prepare_turn_of_month_features(df, params):
    out = df.copy()
    entry_start_from_end = int(params.get('entry_start_from_end', 5))
    entry_end_from_end = int(params.get('entry_end_from_end', 3))
    exit_month_start_day = int(params.get('exit_month_start_day', 3))
    recent_lookback_days = int(params.get('recent_lookback_days', 5))
    min_observations = int(params.get('min_observations', 8))
    long_recent_return_max = float(params.get('long_recent_return_max', 0.01))
    short_recent_return_min = float(params.get('short_recent_return_min', 0.02))
    base_target_percent = float(params.get('base_target_percent', 0.03))
    max_target_percent = float(params.get('max_target_percent', 0.05))
    target_return = max(float(params.get('target_return', 0.004)), 1e-6)

    period = out.index.to_period('M')
    month_day = out.groupby(period).cumcount() + 1
    month_size = out.groupby(period)['close'].transform('size')
    month_end_pos = month_size - month_day + 1
    recent_return = out['close'] / out['close'].shift(recent_lookback_days) - 1.0

    future_returns = []
    index_values = list(out.index)
    close_values = out['close'].tolist()
    month_days = month_day.tolist()
    for idx, ts in enumerate(index_values):
        future_idx = None
        current_period = ts.to_period('M')
        for j in range(idx + 1, len(index_values)):
            next_ts = index_values[j]
            if next_ts.to_period('M') > current_period and month_days[j] >= exit_month_start_day:
                future_idx = j
                break
        if future_idx is None:
            future_returns.append(float('nan'))
        else:
            future_returns.append(close_values[future_idx] / close_values[idx] - 1.0)

    stats = {}
    historical_mean = []
    historical_std = []
    historical_count = []
    long_signal = []
    short_signal = []
    signal_strength = []
    target_percent = []

    for pos, recent_ret, future_ret in zip(month_end_pos, recent_return, future_returns):
        slot = int(pos) if entry_end_from_end <= int(pos) <= entry_start_from_end else None
        slot_stats = stats.setdefault(slot, {'count': 0, 'sum': 0.0, 'sum_sq': 0.0}) if slot is not None else None
        count = slot_stats['count'] if slot_stats is not None else 0
        mean = None
        std = None
        if slot_stats is not None and count >= 2:
            mean = slot_stats['sum'] / count
            variance = max(slot_stats['sum_sq'] / count - mean * mean, 0.0)
            std = variance ** 0.5

        historical_mean.append(mean)
        historical_std.append(std)
        historical_count.append(count)

        should_long = bool(slot is not None and count >= min_observations and mean is not None and mean > 0 and pd.notna(recent_ret) and recent_ret < long_recent_return_max)
        should_short = bool(slot is not None and count >= min_observations and mean is not None and mean < 0 and pd.notna(recent_ret) and recent_ret > short_recent_return_min)
        long_signal.append(1.0 if should_long else 0.0)
        short_signal.append(1.0 if should_short else 0.0)

        abs_mean = abs(mean or 0.0)
        strength = min(abs_mean / target_return, 2.0) if (should_long or should_short) else 0.0
        signal_strength.append(strength)
        target_percent.append(min(max_target_percent, base_target_percent * strength) if (should_long or should_short) else 0.0)

        if slot_stats is not None and pd.notna(future_ret):
            slot_stats['count'] += 1
            slot_stats['sum'] += float(future_ret)
            slot_stats['sum_sq'] += float(future_ret) * float(future_ret)

    out['month_day'] = month_day.astype(float)
    out['month_end_pos'] = month_end_pos.astype(float)
    out['recent_return'] = recent_return.astype(float)
    out['future_exit_return'] = pd.Series(future_returns, index=out.index, dtype='float64')
    out['historical_mean_return'] = pd.Series(historical_mean, index=out.index, dtype='float64')
    out['historical_std_return'] = pd.Series(historical_std, index=out.index, dtype='float64')
    out['historical_count'] = pd.Series(historical_count, index=out.index, dtype='float64')
    out['long_signal'] = pd.Series(long_signal, index=out.index, dtype='float64')
    out['short_signal'] = pd.Series(short_signal, index=out.index, dtype='float64')
    out['signal_strength'] = pd.Series(signal_strength, index=out.index, dtype='float64')
    out['target_percent'] = pd.Series(target_percent, index=out.index, dtype='float64')

    columns = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'month_day', 'month_end_pos', 'recent_return', 'future_exit_return',
        'historical_mean_return', 'historical_std_return', 'historical_count',
        'long_signal', 'short_signal', 'signal_strength', 'target_percent',
    ]
    return out[columns].copy()


class Mt5TurnOfMonthFeed(bt.feeds.PandasData):
    lines = (
        'month_day', 'month_end_pos', 'recent_return', 'future_exit_return',
        'historical_mean_return', 'historical_std_return', 'historical_count',
        'long_signal', 'short_signal', 'signal_strength', 'target_percent',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('month_day', 6), ('month_end_pos', 7), ('recent_return', 8), ('future_exit_return', 9),
        ('historical_mean_return', 10), ('historical_std_return', 11), ('historical_count', 12),
        ('long_signal', 13), ('short_signal', 14), ('signal_strength', 15), ('target_percent', 16),
    )


class GoldTurnOfMonthStrategy(bt.Strategy):
    params = dict(
        exit_month_start_day=3,
        stop_loss_pct=0.015,
        take_profit_pct=0.025,
        entry_start_from_end=5,
        entry_end_from_end=3,
        recent_lookback_days=5,
        long_recent_return_max=0.01,
        short_recent_return_min=0.02,
        min_observations=8,
        base_target_percent=0.03,
        max_target_percent=0.05,
        target_return=0.004,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.short_count = 0
        self.cover_count = 0
        self.long_signal_count = 0
        self.short_signal_count = 0
        self.time_exit_count = 0
        self.stop_exit_count = 0
        self.pending_order = None
        self.entry_price = None
        self.entry_month = None
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
        current_month = bt.num2date(self.data.datetime[0]).month
        month_day = int(self.data.month_day[0])

        if self.position:
            pnl_pct = (close_price / self.entry_price - 1.0) if self.entry_price else 0.0
            if self.position.size < 0:
                pnl_pct = -pnl_pct
            if not self.break_even_armed and pnl_pct >= float(self.p.take_profit_pct):
                self.break_even_armed = True
            stop_loss_limit = 0.0 if self.break_even_armed else -float(self.p.stop_loss_pct)
            if pnl_pct <= stop_loss_limit:
                if self.position.size > 0:
                    self.sell_count += 1
                else:
                    self.cover_count += 1
                self.stop_exit_count += 1
                self.pending_order = self.close()
                return
            if self.entry_month is not None and current_month != self.entry_month and month_day >= int(self.p.exit_month_start_day):
                if self.position.size > 0:
                    self.sell_count += 1
                else:
                    self.cover_count += 1
                self.time_exit_count += 1
                self.pending_order = self.close()
                return
            return

        target_percent = float(self.data.target_percent[0])
        if target_percent <= 0:
            return
        size = self._get_position_size(target_notional_pct=target_percent)
        if size <= 0:
            return

        if float(self.data.long_signal[0]) > 0.5:
            self.long_signal_count += 1
            self.buy_count += 1
            self.pending_order = self.buy(size=size)
            return
        if float(self.data.short_signal[0]) > 0.5:
            self.short_signal_count += 1
            self.short_count += 1
            self.pending_order = self.sell(size=size)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if order.isbuy() and self.position.size > 0:
                self.entry_price = float(order.executed.price)
                self.entry_month = bt.num2date(self.data.datetime[0]).month
                self.break_even_armed = False
            elif order.issell() and self.position.size < 0:
                self.entry_price = float(order.executed.price)
                self.entry_month = bt.num2date(self.data.datetime[0]).month
                self.break_even_armed = False
            elif not self.position:
                self.entry_price = None
                self.entry_month = None
                self.break_even_armed = False
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
