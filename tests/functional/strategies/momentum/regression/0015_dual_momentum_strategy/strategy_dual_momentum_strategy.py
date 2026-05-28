from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
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
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_dual_momentum_features(gold_df, benchmark_df, params):
    merged = gold_df[['open', 'high', 'low', 'close', 'volume', 'openinterest']].join(
        benchmark_df[['close']].rename(columns={'close': 'benchmark_close'}),
        how='inner'
    )
    month_end_index = merged.index.to_period('M').to_timestamp('M')
    gold_monthly = merged['close'].groupby(month_end_index).last()
    benchmark_monthly = merged['benchmark_close'].groupby(month_end_index).last()
    formation_period = int(params.get('formation_period_months', 12))
    threshold = float(params.get('absolute_momentum_threshold', 0.0))
    gold_momentum = gold_monthly / gold_monthly.shift(formation_period) - 1.0
    benchmark_momentum = benchmark_monthly / benchmark_monthly.shift(formation_period) - 1.0
    gold_selected = ((gold_momentum > benchmark_momentum) & (gold_momentum > threshold)).astype(float)
    active_gold_selected = gold_selected.shift(1).reindex(month_end_index).fillna(0.0)
    merged['gold_momentum'] = gold_momentum.reindex(month_end_index).to_numpy()
    merged['benchmark_momentum'] = benchmark_momentum.reindex(month_end_index).to_numpy()
    merged['gold_selected'] = active_gold_selected.to_numpy()
    target_percent = float(params.get('target_percent', 0.95))
    merged['target_pct'] = merged['gold_selected'] * target_percent
    merged = merged[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'benchmark_close', 'gold_momentum', 'benchmark_momentum', 'gold_selected', 'target_pct']].copy()
    monthly_table = pd.DataFrame({
        'gold_close': gold_monthly,
        'benchmark_close': benchmark_monthly,
        'gold_momentum': gold_momentum,
        'benchmark_momentum': benchmark_momentum,
        'gold_selected': gold_selected,
    }).dropna(subset=['gold_close', 'benchmark_close'])
    return merged, monthly_table


class Mt5DualMomentumFeed(bt.feeds.PandasData):
    lines = ('benchmark_close', 'gold_momentum', 'benchmark_momentum', 'gold_selected', 'target_pct',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('benchmark_close', 6),
        ('gold_momentum', 7),
        ('benchmark_momentum', 8),
        ('gold_selected', 9),
        ('target_pct', 10),
    )


class DualMomentumStrategy(bt.Strategy):
    params = dict(
        formation_period_months=12,
        absolute_momentum_threshold=0.0,
        target_percent=0.95,
    )

    def __init__(self):
        self.bar_num = 0
        self.rebalance_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.gold_month_count = 0
        self.cash_month_count = 0
        self.switch_count = 0
        self.pending_order = None
        self.current_month = None
        self.last_target_pct = None
        self.broker_value_series = []

    def _month_key(self):
        dt = bt.num2date(self.data.datetime[0])
        return dt.year, dt.month


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


    def _current_position_pct(self):
        broker_value = float(self.broker.getvalue())
        if broker_value <= 0:
            return 0.0
        price = float(self.data.close[0])
        if price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        return float(self.position.size) * price * multiplier / broker_value


    def _order_target_notional_pct(self, target_pct):
        target_size = self._get_position_size(target_notional_pct=target_pct)
        return self.order_target_size(target=target_size)

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        month_key = self._month_key()
        if month_key == self.current_month:
            return
        self.current_month = month_key
        target_pct = float(self.data.target_pct[0])
        gold_selected = int(round(float(self.data.gold_selected[0])))
        if gold_selected == 1:
            self.gold_month_count += 1
        else:
            self.cash_month_count += 1
        if self.last_target_pct is not None and abs(target_pct - self.last_target_pct) > 1e-9:
            self.switch_count += 1
        self.last_target_pct = target_pct
        if self.pending_order is not None:
            return
        current_pct = self._current_position_pct()
        if abs(current_pct - target_pct) < 0.02:
            return
        self.rebalance_count += 1
        self.pending_order = self._order_target_notional_pct(target_pct)
        if target_pct > current_pct:
            self.buy_count += 1
        elif target_pct < current_pct:
            self.sell_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        # 无论订单状态如何，都清除挂单引用
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
