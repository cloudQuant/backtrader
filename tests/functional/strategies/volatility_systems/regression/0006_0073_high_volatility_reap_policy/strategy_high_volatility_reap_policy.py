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


def prepare_rebalancing_inputs(gold_df, benchmark_df, params):
    common_index = gold_df.index.intersection(benchmark_df.index).sort_values()
    gold = gold_df.loc[common_index].copy()
    benchmark = benchmark_df.loc[common_index].copy()
    signal_df = gold[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['month'] = signal_df.index.month
    signal_df['quarter'] = signal_df.index.quarter
    frequency = str(params.get('rebalance_frequency', 'monthly')).lower()
    if frequency == 'quarterly':
        signal_df['rebalance_signal'] = (signal_df['quarter'] != signal_df['quarter'].shift(1)).astype(float)
    else:
        signal_df['rebalance_signal'] = (signal_df['month'] != signal_df['month'].shift(1)).astype(float)
    signal_df['gold_return_1d'] = gold['close'].pct_change().fillna(0.0)
    signal_df['benchmark_return_1d'] = benchmark['close'].pct_change().fillna(0.0)
    signal_df['target_gold_weight'] = float(params.get('target_gold_weight', 0.15))
    signal_df['target_benchmark_weight'] = float(params.get('target_benchmark_weight', 0.85))
    return gold, benchmark, signal_df


class RebalancingSignalFeed(bt.feeds.PandasData):
    lines = ('month', 'quarter', 'rebalance_signal', 'gold_return_1d', 'benchmark_return_1d', 'target_gold_weight', 'target_benchmark_weight')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('month', 6), ('quarter', 7), ('rebalance_signal', 8), ('gold_return_1d', 9), ('benchmark_return_1d', 10), ('target_gold_weight', 11), ('target_benchmark_weight', 12),
    )


class HighVolatilityReapPolicyStrategy(bt.Strategy):
    params = dict(
        drift_threshold=0.05,
        single_day_stop_loss=0.10,
        portfolio_stop_drawdown=0.15,
        risk_off_cooldown_bars=5,
        target_gold_weight=0.15,
        target_benchmark_weight=0.85,
        rebalance_frequency='monthly',
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.gold = self.getdatabyname('XAUUSD')
        self.benchmark = self.getdatabyname('IVV')
        self.order_refs = set()
        self.bar_num = 0
        self.rebalance_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.switch_count = 0
        self.stop_loss_count = 0
        self.risk_off_bars_remaining = 0
        self.last_target_map = None
        self.peak_value = None
        self.broker_value_series = []

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _market_value(self, data):
        position = self.getposition(data)
        price = float(data.close[0])
        if price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        return float(position.size) * price * multiplier

    def _current_weight(self, data):
        broker_value = float(self.broker.getvalue())
        if broker_value <= 0:
            return 0.0
        return self._market_value(data) / broker_value

    def _target_size(self, data, target_pct):
        broker_value = float(self.broker.getvalue())
        price = float(data.close[0])
        if broker_value <= 0 or price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        raw_size = broker_value * float(target_pct) / (price * multiplier)
        return round(raw_size, 2)

    def _target_map(self):
        if self.risk_off_bars_remaining > 0:
            return {'XAUUSD': 0.0, 'IVV': 0.0}
        return {
            'XAUUSD': float(self.signal.target_gold_weight[0]),
            'IVV': float(self.signal.target_benchmark_weight[0]),
        }

    def _drift_triggered(self):
        targets = self._target_map()
        gold_drift = abs(self._current_weight(self.gold) - targets['XAUUSD'])
        benchmark_drift = abs(self._current_weight(self.benchmark) - targets['IVV'])
        return max(gold_drift, benchmark_drift) >= float(self.p.drift_threshold)

    def _risk_stop_triggered(self):
        gold_ret = float(self.signal.gold_return_1d[0])
        benchmark_ret = float(self.signal.benchmark_return_1d[0])
        broker_value = float(self.broker.getvalue())
        total_exposure = abs(self._market_value(self.gold)) + abs(self._market_value(self.benchmark))
        if total_exposure <= 0:
            self.peak_value = broker_value
            return False
        self.peak_value = broker_value if self.peak_value is None else max(self.peak_value, broker_value)
        drawdown = 0.0 if not self.peak_value else (broker_value / self.peak_value - 1.0)
        if gold_ret <= -float(self.p.single_day_stop_loss):
            return True
        if benchmark_ret <= -float(self.p.single_day_stop_loss):
            return True
        if drawdown <= -float(self.p.portfolio_stop_drawdown):
            return True
        return False

    def next(self):
        self.bar_num += 1
        broker_value = float(self.broker.getvalue())
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), broker_value))
        if self.risk_off_bars_remaining > 0:
            self.risk_off_bars_remaining -= 1
        if self.order_refs:
            return
        if self._risk_stop_triggered():
            self.stop_loss_count += 1
            self.risk_off_bars_remaining = int(self.p.risk_off_cooldown_bars)
            targets = {'XAUUSD': 0.0, 'IVV': 0.0}
            self.rebalance_count += 1
            self.last_target_map = dict(targets)
            self.peak_value = broker_value
            self._submit(self.order_target_size(data=self.gold, target=0.0))
            self._submit(self.order_target_size(data=self.benchmark, target=0.0))
            return
        if float(self.signal.rebalance_signal[0]) <= 0.5 and not self._drift_triggered():
            return
        targets = self._target_map()
        if self.last_target_map is not None and self.last_target_map != targets:
            self.switch_count += 1
        self.last_target_map = dict(targets)
        self.rebalance_count += 1
        current_gold = float(self.getposition(self.gold).size)
        current_benchmark = float(self.getposition(self.benchmark).size)
        gold_order = self.order_target_size(data=self.gold, target=self._target_size(self.gold, targets['XAUUSD']))
        benchmark_order = self.order_target_size(data=self.benchmark, target=self._target_size(self.benchmark, targets['IVV']))
        self._submit(gold_order)
        self._submit(benchmark_order)
        if gold_order is not None:
            if targets['XAUUSD'] > 0 and current_gold <= 0:
                self.buy_count += 1
            elif targets['XAUUSD'] <= 0 and current_gold > 0:
                self.sell_count += 1
        if benchmark_order is not None:
            if targets['IVV'] > 0 and current_benchmark <= 0:
                self.buy_count += 1
            elif targets['IVV'] <= 0 and current_benchmark > 0:
                self.sell_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)
