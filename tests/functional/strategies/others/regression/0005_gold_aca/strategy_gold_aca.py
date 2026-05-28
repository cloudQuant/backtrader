from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd

ASSET_ORDER = ['GLD', 'IEF', 'BIL', 'GOVT']
DEFENSIVE_SLEEVES = ['IEF', 'BIL', 'GOVT']


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
    df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_aca_inputs(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    aligned = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}
    close_df = pd.DataFrame({name: frame['close'] for name, frame in aligned.items()}, index=common_index).dropna()
    aligned = {name: frame.loc[close_df.index].copy() for name, frame in aligned.items()}

    lookback_days = int(params.get('lookback_days', 126))
    rebalance_on_year_end = bool(params.get('rebalance_on_year_end', True))

    signal_df = aligned['GLD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['gld_upper'] = close_df['GLD'].rolling(lookback_days).max().shift(1)
    signal_df['gld_lower'] = close_df['GLD'].rolling(lookback_days).min().shift(1)

    sleeve_states = {name: 0 for name in DEFENSIVE_SLEEVES}
    prev_weights = None
    weights_records = []
    for i, dt in enumerate(close_df.index):
        gld_close = close_df['GLD'].iloc[i]
        upper = signal_df['gld_upper'].iloc[i]
        lower = signal_df['gld_lower'].iloc[i]
        signal_changed = False
        if pd.notna(upper) and gld_close > upper:
            new_states = {name: 1 for name in DEFENSIVE_SLEEVES}
            signal_changed = new_states != sleeve_states
            sleeve_states = new_states
        elif pd.notna(lower) and gld_close < lower:
            new_states = {name: 0 for name in DEFENSIVE_SLEEVES}
            signal_changed = new_states != sleeve_states
            sleeve_states = new_states

        weights = {name: 0.0 for name in ASSET_ORDER}
        for sleeve in DEFENSIVE_SLEEVES:
            if sleeve_states[sleeve] == 1:
                weights['GLD'] += 1.0 / 3.0
            else:
                weights[sleeve] += 1.0 / 3.0

        is_year_end = False
        if rebalance_on_year_end and i > 0:
            prev_dt = close_df.index[i - 1]
            is_year_end = dt.year != prev_dt.year

        rebalance_flag = signal_changed or is_year_end or prev_weights is None
        prev_weights = weights.copy()
        weights_records.append((dt, rebalance_flag, weights))

    weights_df = pd.DataFrame(
        {
            'rebalance_flag': [1.0 if row[1] else 0.0 for row in weights_records],
            'gld_weight': [row[2]['GLD'] for row in weights_records],
            'ief_weight': [row[2]['IEF'] for row in weights_records],
            'bil_weight': [row[2]['BIL'] for row in weights_records],
            'govt_weight': [row[2]['GOVT'] for row in weights_records],
        },
        index=close_df.index,
    )
    signal_df = signal_df.join(weights_df)
    signal_df = signal_df[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'rebalance_flag', 'gld_weight', 'ief_weight', 'bil_weight', 'govt_weight']]
    return {'signal_df': signal_df.dropna(), 'asset_frames': aligned}


class ACASignalFeed(bt.feeds.PandasData):
    lines = ('rebalance_flag', 'gld_weight', 'ief_weight', 'bil_weight', 'govt_weight')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('rebalance_flag', 6), ('gld_weight', 7), ('ief_weight', 8), ('bil_weight', 9), ('govt_weight', 10),
    )


class GoldACAStrategy(bt.Strategy):
    params = dict(
        lot_size=1.0,
        lookback_days=126,
        rebalance_on_year_end=True,
    )

    def __init__(self):
        self.signal_data = self.datas[0]
        self.asset_data = {data._name: data for data in self.datas[1:]}
        self.bar_num = 0
        self.rebalance_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.broker_value_series = []
        self.pending_orders = []

    def _target_weight_map(self):
        return {
            'GLD': float(self.signal_data.gld_weight[0]),
            'IEF': float(self.signal_data.ief_weight[0]),
            'BIL': float(self.signal_data.bil_weight[0]),
            'GOVT': float(self.signal_data.govt_weight[0]),
        }

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal_data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_orders:
            return
        if float(self.signal_data.rebalance_flag[0]) <= 0.5:
            return
        target_weights = self._target_weight_map()
        self.rebalance_count += 1
        for symbol, target_weight in target_weights.items():
            data = self.asset_data[symbol]
            order = self.order_target_percent(data=data, target=target_weight * float(self.p.lot_size))
            if order is not None:
                self.pending_orders.append(order)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_orders = [o for o in self.pending_orders if o.ref != order.ref]

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
