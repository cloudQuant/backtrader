from __future__ import absolute_import, division, print_function, unicode_literals

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


def prepare_unfilled_gap_features(df, params):
    min_gap_size = float(params.get('min_gap_size', 0.002))
    lookback_period = int(params.get('lookback_period', 30))
    required_gaps = int(params.get('required_unfilled_gaps', 2))
    max_gap_spacing = int(params.get('max_gap_spacing', 5))

    out = df.copy()
    out['prev_close'] = out['close'].shift(1)
    out['prev_high'] = out['high'].shift(1)
    out['opening_gap_pct'] = (out['open'] - out['prev_close']) / out['prev_close']
    out['range_gap_pct'] = (out['low'] - out['prev_high']) / out['prev_high']
    out['gap_pct'] = out['opening_gap_pct']
    out['gap_low'] = out['prev_close']
    out['gap_high'] = out['open']
    out['is_gap_up'] = (out['gap_pct'] >= min_gap_size).astype(int)

    active_gaps = []
    unfilled_gap_count = []
    latest_gap_floor = []
    second_gap_floor = []
    recent_gap_spacing = []

    for i, (idx, row) in enumerate(out.iterrows()):
        current_low = float(row['low'])
        active_gaps = [gap for gap in active_gaps if current_low > gap['gap_low']]
        if int(row['is_gap_up']) == 1:
            active_gaps.append({'index': i, 'gap_low': float(row['gap_low']), 'gap_high': float(row['gap_high'])})
        active_gaps = active_gaps[-required_gaps:]
        unfilled_gap_count.append(len(active_gaps))
        latest_gap_floor.append(active_gaps[-1]['gap_low'] if len(active_gaps) >= 1 else float('nan'))
        second_gap_floor.append(active_gaps[-2]['gap_low'] if len(active_gaps) >= 2 else float('nan'))
        if len(active_gaps) >= 2:
            recent_gap_spacing.append(active_gaps[-1]['index'] - active_gaps[-2]['index'])
        else:
            recent_gap_spacing.append(float('nan'))

    out['unfilled_gap_count'] = unfilled_gap_count
    out['latest_gap_floor'] = latest_gap_floor
    out['second_gap_floor'] = second_gap_floor
    out['recent_gap_spacing'] = recent_gap_spacing
    out['rolling_high'] = out['high'].rolling(lookback_period).max().shift(1)
    out['is_new_high'] = (out['close'] >= out['rolling_high']).astype(float)
    out['entry_signal'] = (
        (out['unfilled_gap_count'] >= required_gaps)
        & (out['recent_gap_spacing'] <= max_gap_spacing)
        & (out['is_new_high'] > 0)
    ).astype(float)

    out = out[[
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'gap_pct', 'unfilled_gap_count', 'latest_gap_floor', 'second_gap_floor',
        'recent_gap_spacing', 'rolling_high', 'is_new_high', 'entry_signal',
    ]].copy()
    return out.dropna()


class Mt5UnfilledGapFeed(bt.feeds.PandasData):
    lines = (
        'gap_pct', 'unfilled_gap_count', 'latest_gap_floor', 'second_gap_floor',
        'recent_gap_spacing', 'rolling_high', 'is_new_high', 'entry_signal',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('gap_pct', 6), ('unfilled_gap_count', 7), ('latest_gap_floor', 8), ('second_gap_floor', 9),
        ('recent_gap_spacing', 10), ('rolling_high', 11), ('is_new_high', 12), ('entry_signal', 13),
    )


class UnfilledGapStrategy(bt.Strategy):
    params = dict(
        holding_days=5,
        stop_loss=0.02,
        take_profit=0.03,
        position_size=0.95,
        gap_type='opening',
        min_gap_size=0.002,
        lookback_period=30,
        required_unfilled_gaps=2,
        max_gap_spacing=5,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.entry_bar = 0
        self.stop_price = None
        self.take_profit_price = None
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
        high = float(self.data.high[0])
        close = float(self.data.close[0])

        if self.position:
            if self.stop_price is not None and low <= self.stop_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.bar_num - self.entry_bar >= int(self.p.holding_days):
                self.sell_count += 1
                self.pending_order = self.close()
                return
            return

        if float(self.data.entry_signal[0]) > 0.5:
            self.buy_count += 1
            self.entry_bar = self.bar_num
            gap_floor = float(self.data.second_gap_floor[0]) if self.data.second_gap_floor[0] == self.data.second_gap_floor[0] else close * (1.0 - float(self.p.stop_loss))
            self.stop_price = max(gap_floor, close * (1.0 - float(self.p.stop_loss)))
            self.take_profit_price = close * (1.0 + float(self.p.take_profit))
            self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.position_size)))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.stop_price = None
            self.take_profit_price = None
