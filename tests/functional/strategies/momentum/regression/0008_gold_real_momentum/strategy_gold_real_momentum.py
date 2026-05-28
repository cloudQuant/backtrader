from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
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


def prepare_real_momentum_features(gold_df, inflation_proxy_df, defensive_df, params):
    common_index = gold_df.index.intersection(inflation_proxy_df.index).intersection(defensive_df.index).sort_values()
    gold = gold_df.loc[common_index].copy()
    inflation_proxy = inflation_proxy_df.loc[common_index].copy()
    defensive = defensive_df.loc[common_index].copy()

    lookback_days = int(params.get('lookback_days', 252))
    threshold = float(params.get('threshold', 0.0))
    stop_loss_pct = float(params.get('stop_loss_pct', 0.10))
    volatility_window = int(params.get('volatility_window', 63))
    high_vol_threshold = float(params.get('high_vol_threshold', 0.25))
    reduced_weight = float(params.get('reduced_weight', 0.5))
    full_weight = float(params.get('full_weight', 1.0))

    signal_df = gold[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['month'] = signal_df.index.month
    signal_df['rebalance_signal'] = (signal_df['month'] != signal_df['month'].shift(1)).astype(float)
    signal_df['gold_nominal_return'] = gold['close'].pct_change(lookback_days)
    signal_df['inflation_proxy_return'] = inflation_proxy['close'].pct_change(lookback_days) - defensive['close'].pct_change(lookback_days)
    signal_df['real_momentum'] = signal_df['gold_nominal_return'] - signal_df['inflation_proxy_return']
    signal_df['gold_volatility'] = gold['close'].pct_change().rolling(volatility_window).std() * np.sqrt(252)
    rolling_peak = gold['close'].cummax()
    signal_df['drawdown'] = gold['close'] / rolling_peak - 1.0

    target_gold = []
    target_defensive = []
    for _, row in signal_df.iterrows():
        real_momentum = row['real_momentum']
        drawdown = row['drawdown']
        vol = row['gold_volatility']
        if pd.isna(real_momentum):
            target_gold.append(0.0)
            target_defensive.append(0.0)
            continue
        if real_momentum > threshold and drawdown > -stop_loss_pct:
            weight = reduced_weight if (pd.notna(vol) and vol > high_vol_threshold) else full_weight
            target_gold.append(weight)
            target_defensive.append(max(0.0, 1.0 - weight))
        else:
            target_gold.append(0.0)
            target_defensive.append(1.0)

    signal_df['target_gold_pct'] = target_gold
    signal_df['target_defensive_pct'] = target_defensive
    return gold, inflation_proxy, defensive, signal_df.dropna(subset=['real_momentum'])


class GoldRealMomentumSignalFeed(bt.feeds.PandasData):
    lines = ('month', 'rebalance_signal', 'gold_nominal_return', 'inflation_proxy_return', 'real_momentum', 'gold_volatility', 'drawdown', 'target_gold_pct', 'target_defensive_pct')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('month', 6), ('rebalance_signal', 7), ('gold_nominal_return', 8), ('inflation_proxy_return', 9), ('real_momentum', 10), ('gold_volatility', 11), ('drawdown', 12), ('target_gold_pct', 13), ('target_defensive_pct', 14),
    )


class GoldRealMomentumStrategy(bt.Strategy):
    params = dict(
        lookback_days=252,
        threshold=0.0,
        stop_loss_pct=0.1,
        rebalance_frequency='monthly',
        volatility_window=63,
        high_vol_threshold=0.25,
        reduced_weight=0.5,
        full_weight=1.0,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.gold = self.getdatabyname('XAUUSD')
        self.inflation_proxy = self.getdatabyname('GTIP')
        self.defensive = self.getdatabyname('IEF')
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_log = []
        self.broker_value_series = []

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        if float(self.signal.rebalance_signal[0]) <= 0.5:
            return
        target_gold = float(self.signal.target_gold_pct[0])
        target_defensive = float(self.signal.target_defensive_pct[0])
        current_gold = float(self.getposition(self.gold).size)
        current_defensive = float(self.getposition(self.defensive).size)
        self._submit(self.order_target_percent(data=self.gold, target=target_gold))
        self._submit(self.order_target_percent(data=self.defensive, target=target_defensive))
        if target_gold > 0 and current_gold <= 0:
            self.buy_count += 1
        elif target_gold <= 0 and current_gold > 0:
            self.sell_count += 1
        if target_defensive > 0 and current_defensive <= 0:
            self.buy_count += 1
        elif target_defensive <= 0 and current_defensive > 0:
            self.sell_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trade_log.append({'pnlcomm': trade.pnlcomm})
