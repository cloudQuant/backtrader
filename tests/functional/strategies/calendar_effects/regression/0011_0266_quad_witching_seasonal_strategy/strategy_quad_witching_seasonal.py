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


def prepare_quad_witching_features(df, params):
    bearish_months = set(int(v) for v in params.get('bearish_months', [3, 6]))
    bullish_months = set(int(v) for v in params.get('bullish_months', [9, 12]))
    holding_days = int(params.get('holding_days', 5))
    out = df.copy()
    in_window = []
    entry_signal = []
    exit_signal = []
    direction = []
    event_month = []
    day_in_window = []
    for idx in out.index:
        third_friday = _third_friday(idx.year, idx.month)
        current_direction = 0.0
        current_day = 0.0
        current_month = float(idx.month)
        active = False
        if third_friday is not None:
            quad_date = pd.Timestamp(year=idx.year, month=idx.month, day=third_friday)
            entry_start = quad_date + pd.offsets.BDay(1)
            exit_end = quad_date + pd.offsets.BDay(holding_days)
            if entry_start <= idx <= exit_end:
                active = True
                current_day = float(len(pd.bdate_range(entry_start, idx)))
                if idx.month in bearish_months:
                    current_direction = -1.0
                elif idx.month in bullish_months:
                    current_direction = 1.0
                else:
                    current_direction = 0.0
        in_window.append(1.0 if active else 0.0)
        entry_signal.append(1.0 if active and current_day == 1.0 and current_direction != 0.0 else 0.0)
        exit_signal.append(1.0 if active and current_day >= float(holding_days) else 0.0)
        direction.append(current_direction)
        event_month.append(current_month)
        day_in_window.append(current_day)
    out['in_window'] = in_window
    out['entry_signal'] = entry_signal
    out['exit_signal'] = exit_signal
    out['direction'] = direction
    out['event_month'] = event_month
    out['day_in_window'] = day_in_window
    return out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'in_window', 'entry_signal', 'exit_signal', 'direction', 'event_month', 'day_in_window']].dropna()


class QuadWitchingFeed(bt.feeds.PandasData):
    lines = ('in_window', 'entry_signal', 'exit_signal', 'direction', 'event_month', 'day_in_window',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('in_window', 6), ('entry_signal', 7), ('exit_signal', 8), ('direction', 9), ('event_month', 10), ('day_in_window', 11),
    )


class QuadWitchingSeasonalStrategy(bt.Strategy):
    params = dict(
        stop_loss=0.02,
        take_profit=0.03,
        position_size=0.90,
        bearish_months=[3, 6],
        bullish_months=[9, 12],
        holding_days=5,
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
        close = float(self.data.close[0])
        low = float(self.data.low[0])
        high = float(self.data.high[0])
        if self.position:
            if self.trade_direction > 0:
                if low <= self.entry_price * (1.0 - float(self.p.stop_loss)):
                    self.sell_count += 1
                    self.pending_order = self.close()
                    return
                if high >= self.entry_price * (1.0 + float(self.p.take_profit)):
                    self.sell_count += 1
                    self.pending_order = self.close()
                    return
            elif self.trade_direction < 0:
                if high >= self.entry_price * (1.0 + float(self.p.stop_loss)):
                    self.buy_count += 1
                    self.pending_order = self.close()
                    return
                if low <= self.entry_price * (1.0 - float(self.p.take_profit)):
                    self.buy_count += 1
                    self.pending_order = self.close()
                    return
            if exit_now:
                if self.trade_direction > 0:
                    self.sell_count += 1
                else:
                    self.buy_count += 1
                self.pending_order = self.close()
                return
            return
        if entry and direction != 0:
            self.entry_price = close
            self.trade_direction = direction
            target_size = self._get_position_size(target_notional_pct=float(self.p.position_size) * direction)
            if target_size > 0:
                self.buy_count += 1
            else:
                self.sell_count += 1
            self.pending_order = self.order_target_size(target=target_size)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.trade_direction = 0
