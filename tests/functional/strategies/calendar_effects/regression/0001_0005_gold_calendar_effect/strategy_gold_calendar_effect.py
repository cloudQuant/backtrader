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


def prepare_calendar_features(df, params):
    out = df.copy()
    hold_days = int(params.get('hold_days', 2))
    month_start_days = int(params.get('month_start_days', 3))
    month_end_days = int(params.get('month_end_days', 3))
    min_observations = int(params.get('min_observations', 8))
    t_stat_threshold = float(params.get('t_stat_threshold', 0.5))
    base_target_percent = float(params.get('base_target_percent', 0.15))
    max_target_percent = float(params.get('max_target_percent', 0.30))
    target_return = max(float(params.get('target_return', 0.003)), 1e-6)

    period = out.index.to_period('M')
    month_day = out.groupby(period).cumcount() + 1
    month_size = out.groupby(period)['close'].transform('size')
    month_end_pos = month_size - month_day + 1
    forward_return = out['close'].shift(-hold_days) / out['close'] - 1.0

    slot_labels = []
    for start_pos, end_pos in zip(month_day, month_end_pos):
        if start_pos <= month_start_days:
            slot_labels.append(f'S{int(start_pos)}')
        elif end_pos <= month_end_days:
            slot_labels.append(f'E{int(end_pos)}')
        else:
            slot_labels.append('')

    historical_mean = []
    historical_std = []
    historical_count = []
    historical_t = []
    calendar_signal = []
    signal_strength = []
    target_percent = []

    stats = {}
    for slot, fwd_ret in zip(slot_labels, forward_return):
        slot_stats = stats.setdefault(slot, {'count': 0, 'sum': 0.0, 'sum_sq': 0.0})
        count = slot_stats['count'] if slot else 0
        mean = None
        std = None
        t_value = None
        if slot and count >= 2:
            mean = slot_stats['sum'] / count
            variance = max(slot_stats['sum_sq'] / count - mean * mean, 0.0)
            std = variance ** 0.5
            if std and std > 0:
                t_value = mean / (std / (count ** 0.5))
        historical_mean.append(mean)
        historical_std.append(std)
        historical_count.append(count)
        historical_t.append(t_value)

        should_trade = bool(
            slot
            and count >= min_observations
            and mean is not None
            and mean > 0
            and t_value is not None
            and t_value >= t_stat_threshold
        )
        calendar_signal.append(1.0 if should_trade else 0.0)
        strength = min(max((mean or 0.0) / target_return, 0.0), 2.0) if should_trade else 0.0
        signal_strength.append(strength)
        target_percent.append(min(max_target_percent, base_target_percent * strength) if should_trade else 0.0)

        if slot and pd.notna(fwd_ret):
            slot_stats['count'] += 1
            slot_stats['sum'] += float(fwd_ret)
            slot_stats['sum_sq'] += float(fwd_ret) * float(fwd_ret)

    out['month_day'] = month_day.astype(float)
    out['month_end_pos'] = month_end_pos.astype(float)
    out['forward_return'] = forward_return.astype(float)
    out['historical_mean_return'] = pd.Series(historical_mean, index=out.index, dtype='float64')
    out['historical_std_return'] = pd.Series(historical_std, index=out.index, dtype='float64')
    out['historical_count'] = pd.Series(historical_count, index=out.index, dtype='float64')
    out['historical_t_stat'] = pd.Series(historical_t, index=out.index, dtype='float64')
    out['calendar_signal'] = pd.Series(calendar_signal, index=out.index, dtype='float64')
    out['signal_strength'] = pd.Series(signal_strength, index=out.index, dtype='float64')
    out['target_percent'] = pd.Series(target_percent, index=out.index, dtype='float64')

    columns = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'month_day', 'month_end_pos', 'historical_mean_return', 'historical_std_return',
        'historical_count', 'historical_t_stat', 'calendar_signal', 'signal_strength', 'target_percent',
    ]
    return out[columns].copy()


class Mt5CalendarEffectFeed(bt.feeds.PandasData):
    lines = (
        'month_day', 'month_end_pos', 'historical_mean_return', 'historical_std_return',
        'historical_count', 'historical_t_stat', 'calendar_signal', 'signal_strength', 'target_percent',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('month_day', 6), ('month_end_pos', 7), ('historical_mean_return', 8), ('historical_std_return', 9),
        ('historical_count', 10), ('historical_t_stat', 11), ('calendar_signal', 12), ('signal_strength', 13), ('target_percent', 14),
    )


class GoldCalendarEffectStrategy(bt.Strategy):
    params = dict(
        hold_days=2,
        stop_loss_pct=0.015,
        take_profit_pct=0.01,
        month_start_days=3,
        month_end_days=3,
        min_observations=8,
        t_stat_threshold=0.5,
        target_return=0.003,
        base_target_percent=0.15,
        max_target_percent=0.3,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.signal_count = 0
        self.time_exit_count = 0
        self.stop_exit_count = 0
        self.take_exit_count = 0
        self.pending_order = None
        self.entry_price = None
        self.entry_bar = None
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

        if self.position:
            holding_days = self.bar_num - (self.entry_bar or self.bar_num)
            if self.entry_price is not None and close_price <= self.entry_price * (1.0 - float(self.p.stop_loss_pct)):
                self.sell_count += 1
                self.stop_exit_count += 1
                self.pending_order = self.close()
                return
            if self.entry_price is not None and close_price >= self.entry_price * (1.0 + float(self.p.take_profit_pct)):
                self.sell_count += 1
                self.take_exit_count += 1
                self.pending_order = self.close()
                return
            if holding_days >= int(self.p.hold_days):
                self.sell_count += 1
                self.time_exit_count += 1
                self.pending_order = self.close()
                return

        if self.position:
            return

        calendar_signal = float(self.data.calendar_signal[0])
        target_percent = float(self.data.target_percent[0])
        if calendar_signal > 0.5 and target_percent > 0:
            size = self._get_position_size(target_notional_pct=target_percent)
            if size > 0:
                self.signal_count += 1
                self.buy_count += 1
                self.pending_order = self.buy(size=size)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.entry_price = float(order.executed.price)
                self.entry_bar = self.bar_num
            elif order.issell() and not self.position:
                self.entry_price = None
                self.entry_bar = None
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
