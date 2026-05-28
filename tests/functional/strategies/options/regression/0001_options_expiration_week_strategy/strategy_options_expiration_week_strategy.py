from __future__ import absolute_import, division, print_function, unicode_literals

import calendar
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


def _third_friday(year, month):
    month_calendar = calendar.monthcalendar(year, month)
    friday_col = calendar.FRIDAY
    friday_count = 0
    for week in month_calendar:
        if week[friday_col] != 0:
            friday_count += 1
            if friday_count == 3:
                return week[friday_col]
    return None


def prepare_options_expiration_week_features(df, params):
    target_months = set(int(v) for v in params.get('target_months', [3, 4, 10, 12]))
    month_weights = {int(k): float(v) for k, v in (params.get('month_weights', {}) or {}).items()}
    out = df.copy()
    expiration_monday = []
    expiration_friday = []
    in_expiration_week = []
    month_bias = []
    entry_signal = []
    exit_signal = []
    direction = []
    signal_weight = []
    for idx in out.index:
        third_friday = _third_friday(idx.year, idx.month)
        if third_friday is None:
            expiration_monday.append(float('nan'))
            expiration_friday.append(float('nan'))
            in_expiration_week.append(0.0)
            month_bias.append(0.0)
            entry_signal.append(0.0)
            exit_signal.append(0.0)
            direction.append(0.0)
            signal_weight.append(0.0)
            continue
        monday_day = third_friday - 4
        in_week = monday_day <= idx.day <= third_friday and idx.weekday() <= 4
        bullish = idx.month in target_months
        weight = month_weights.get(idx.month, 1.0 if bullish else 0.0)
        bias = 1.0 if bullish else 0.0
        expiration_monday.append(float(monday_day))
        expiration_friday.append(float(third_friday))
        in_expiration_week.append(float(in_week))
        month_bias.append(bias)
        entry_signal.append(1.0 if in_week and idx.weekday() == 0 and bullish else 0.0)
        exit_signal.append(1.0 if in_week and idx.weekday() == 4 else 0.0)
        direction.append(bias if in_week else 0.0)
        signal_weight.append(weight if in_week else 0.0)
    out['expiration_monday'] = expiration_monday
    out['expiration_friday'] = expiration_friday
    out['in_expiration_week'] = in_expiration_week
    out['month_bias'] = month_bias
    out['entry_signal'] = entry_signal
    out['exit_signal'] = exit_signal
    out['direction'] = direction
    out['signal_weight'] = signal_weight
    return out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'expiration_monday', 'expiration_friday', 'in_expiration_week', 'month_bias', 'entry_signal', 'exit_signal', 'direction', 'signal_weight']].dropna()


class OptionsExpirationWeekFeed(bt.feeds.PandasData):
    lines = ('expiration_monday', 'expiration_friday', 'in_expiration_week', 'month_bias', 'entry_signal', 'exit_signal', 'direction', 'signal_weight',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('expiration_monday', 6), ('expiration_friday', 7), ('in_expiration_week', 8), ('month_bias', 9), ('entry_signal', 10), ('exit_signal', 11), ('direction', 12), ('signal_weight', 13),
    )


class OptionsExpirationWeekStrategy(bt.Strategy):
    params = dict(
        stop_loss=0.02,
        take_profit=0.015,
        position_size=0.95,
        target_months=[3, 4, 10, 12],
        month_weights={'3': 1.0, '4': 1.0, '10': 1.2, '12': 1.2},
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.entry_price = None
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
        entry = float(self.data.entry_signal[0]) > 0.5
        exit_now = float(self.data.exit_signal[0]) > 0.5
        direction = int(float(self.data.direction[0]))
        weight = float(self.data.signal_weight[0]) if self.data.signal_weight[0] == self.data.signal_weight[0] else 0.0
        close = float(self.data.close[0])
        low = float(self.data.low[0])
        high = float(self.data.high[0])
        if self.position:
            if low <= self.entry_price * (1.0 - float(self.p.stop_loss)):
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if high >= self.entry_price * (1.0 + float(self.p.take_profit)):
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if exit_now:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            return
        if entry and direction > 0 and weight > 0:
            self.entry_price = close
            self.trade_direction = direction
            target_size = self._get_position_size(target_notional_pct=float(self.p.position_size) * weight)
            self.buy_count += 1
            self.pending_order = self.order_target_size(target=target_size)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.trade_direction = 0
