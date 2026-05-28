from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd

ASSET_ORDER = ['GLD', 'GDX']


def load_mt5_csv(filepath, fromdate=None, todate=None):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = '\n'.join(lines)
    sep = '\t' if '\t' in lines[0] else ','
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = df['<DATE>'].astype(str) + ' ' + df['<TIME>'].astype(str)
    parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M:%S', errors='coerce')
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M', errors='coerce')
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


def prepare_hedge_inputs(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    aligned = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}

    momentum_lookback = int(params.get('momentum_lookback', 5))
    sqrt_signal_threshold = float(params.get('sqrt_signal_threshold', 1.0))
    long_target_percent = float(params.get('long_target_percent', 0.50))
    short_target_percent = float(params.get('short_target_percent', -0.50))

    gld = aligned['GLD']
    gdx = aligned['GDX']
    ivv = aligned['IVV']
    idu = aligned['IDU']

    sqrt_hl = np.sqrt(gld['high'] * gld['low'])
    gld_sqrt_signal = (sqrt_hl / sqrt_hl.shift(1) > sqrt_signal_threshold).astype(float)
    ivv_momentum = ivv['close'] / ivv['close'].shift(momentum_lookback) - 1.0
    idu_momentum = idu['close'] / idu['close'].shift(momentum_lookback) - 1.0
    spy_signal = (ivv_momentum > 0.0).astype(float)
    xlu_signal = (idu_momentum < 0.0).astype(float)

    gdx_short_signal = (gld_sqrt_signal * spy_signal > 0.5).astype(float)
    gld_long_signal = xlu_signal.astype(float)

    gold_target = gld_long_signal * long_target_percent
    miner_target = gdx_short_signal * short_target_percent
    signal_change = (gold_target.ne(gold_target.shift(1)) | miner_target.ne(miner_target.shift(1))).astype(float)

    signal_df = gld[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['gld_sqrt_signal'] = gld_sqrt_signal
    signal_df['spy_signal'] = spy_signal
    signal_df['xlu_signal'] = xlu_signal
    signal_df['gld_long_signal'] = gld_long_signal
    signal_df['gdx_short_signal'] = gdx_short_signal
    signal_df['gold_target'] = gold_target
    signal_df['miner_target'] = miner_target
    signal_df['signal_change'] = signal_change
    signal_df = signal_df[[
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'gld_sqrt_signal', 'spy_signal', 'xlu_signal', 'gld_long_signal',
        'gdx_short_signal', 'gold_target', 'miner_target', 'signal_change',
    ]]
    return {'signal_df': signal_df.dropna(), 'asset_frames': {'GLD': gld, 'GDX': gdx}}


class HedgeSignalFeed(bt.feeds.PandasData):
    lines = (
        'gld_sqrt_signal', 'spy_signal', 'xlu_signal', 'gld_long_signal',
        'gdx_short_signal', 'gold_target', 'miner_target', 'signal_change',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('gld_sqrt_signal', 6), ('spy_signal', 7), ('xlu_signal', 8), ('gld_long_signal', 9),
        ('gdx_short_signal', 10), ('gold_target', 11), ('miner_target', 12), ('signal_change', 13),
    )


class GoldMultiMarketHedgeStrategy(bt.Strategy):
    params = dict(
        momentum_lookback=5,
        sqrt_signal_threshold=1.0,
        long_target_percent=0.5,
        short_target_percent=-0.5,
    )

    def __init__(self):
        self.signal_data = self.datas[0]
        self.asset_data = {data._name: data for data in self.datas[1:]}
        self.pending_orders = []
        self.bar_num = 0
        self.signal_change_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal_data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_orders:
            return
        if float(self.signal_data.signal_change[0]) <= 0.5:
            return
        self.signal_change_count += 1
        target_map = {
            'GLD': float(self.signal_data.gold_target[0]),
            'GDX': float(self.signal_data.miner_target[0]),
        }
        for symbol, target in target_map.items():
            order = self.order_target_percent(data=self.asset_data[symbol], target=target)
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
