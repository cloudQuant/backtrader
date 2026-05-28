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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume'] if 'tick_volume' in df.columns else 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_52_week_high_features(df, params):
    out = df.copy()
    lookback_days = int(params.get('lookback_days', 252))
    exclude_days = int(params.get('exclude_days', 30))
    lower_threshold = float(params.get('lower_threshold', 0.90))
    upper_threshold = float(params.get('upper_threshold', 0.95))
    holding_period = int(params.get('holding_period', 21))
    out['rolling_high_52w'] = out['close'].rolling(lookback_days).max()
    out['month_key'] = out.index.to_period('M').astype(str)
    out['month_start'] = (out['month_key'] != out['month_key'].shift(1)).astype(float)
    out['entry_signal'] = 0.0
    out['exit_signal'] = 0.0
    in_position_until = None
    for i in range(len(out)):
        current_dt = out.index[i]
        if in_position_until is not None and current_dt >= in_position_until:
            out.iloc[i, out.columns.get_loc('exit_signal')] = 1.0
            in_position_until = None
        if out['month_start'].iloc[i] <= 0.5:
            continue
        if i < max(lookback_days, exclude_days):
            continue
        if in_position_until is not None:
            continue
        high_52 = out['rolling_high_52w'].iloc[i]
        if pd.isna(high_52) or high_52 <= 0:
            continue
        current_price = out['close'].iloc[i]
        lower_bound = lower_threshold * high_52
        upper_bound = upper_threshold * high_52
        in_range = lower_bound <= current_price <= upper_bound
        recent_high = out['close'].iloc[max(0, i - exclude_days):i].max()
        recently_hit_high = recent_high >= high_52 * 0.99
        if in_range and not recently_hit_high:
            out.iloc[i, out.columns.get_loc('entry_signal')] = 1.0
            exit_idx = min(len(out) - 1, i + holding_period)
            in_position_until = out.index[exit_idx]
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'rolling_high_52w', 'month_start', 'entry_signal', 'exit_signal']].copy()
    return out.dropna()


class Mt552WeekHighFeed(bt.feeds.PandasData):
    lines = ('rolling_high_52w', 'month_start', 'entry_signal', 'exit_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('rolling_high_52w', 6), ('month_start', 7), ('entry_signal', 8), ('exit_signal', 9),
    )


class Gold52WeekHighEffectStrategy(bt.Strategy):
    params = dict(
        lot_size=1.0,
        lower_threshold=0.9,
        upper_threshold=0.95,
        lookback_days=252,
        exclude_days=30,
        holding_period=21,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
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
        if self.pending_order is not None:
            return
        if self.position:
            if float(self.data.exit_signal[0]) > 0.5:
                self.sell_count += 1
                self.pending_order = self.close()
            return
        if float(self.data.entry_signal[0]) > 0.5:
            self.buy_count += 1
            self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
