from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import numpy as np
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = '\n'.join(lines)
    sep = '\t' if '\t' in lines[0] else ','
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    if 'time' in df.columns:
        df['datetime'] = pd.to_datetime(df['time'], errors='coerce', utc=True).dt.tz_convert(None)
        if 'volume' not in df.columns:
            df['volume'] = df['tick_volume'] if 'tick_volume' in df.columns else 0
        df['openinterest'] = 0
        df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
        df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
        if fromdate is not None:
            df = df[df.index >= fromdate]
        if todate is not None:
            df = df[df.index <= todate]
        return df
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


def prepare_pair_data(gold_df, silver_df):
    common_index = gold_df.index.intersection(silver_df.index).sort_values()
    gold = gold_df.loc[common_index].copy()
    silver = silver_df.loc[common_index].copy()
    return gold, silver


class GoldSilverPairsTradingStrategy(bt.Strategy):
    params = dict(
        hedge_ratio=1.0,
        zscore_window=192,
        entry_threshold=2.0,
        exit_threshold=0.5,
        stop_threshold=3.0,
        max_notional_pct=0.05,
        commission_pct=0.0005,
        annualization_factor=6048,
    )

    def __init__(self):
        self.gold = self.datas[0]
        self.silver = self.datas[1]
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_log = []
        self.broker_value_series = []
        self.spread_history = []
        self.current_spread_side = 0

    def _spread(self):
        gold_price = max(float(self.gold.close[0]), 1e-6)
        silver_price = max(float(self.silver.close[0]), 1e-6)
        return math.log(gold_price) - float(self.p.hedge_ratio) * math.log(silver_price)

    def _zscore(self):
        if len(self.spread_history) < int(self.p.zscore_window):
            return None
        window = np.asarray(self.spread_history[-int(self.p.zscore_window):], dtype=float)
        std = np.std(window)
        if std <= 0:
            return None
        return float((window[-1] - np.mean(window)) / std)

    def _target_sizes(self):
        portfolio_value = float(self.broker.getvalue())
        gold_price = max(float(self.gold.close[0]), 1e-6)
        silver_price = max(float(self.silver.close[0]), 1e-6)
        leg_notional = portfolio_value * float(self.p.max_notional_pct)
        gold_size = round(leg_notional / gold_price, 2)
        silver_size = round(leg_notional / silver_price, 2)
        return max(gold_size, 0.01), max(silver_size, 0.01)

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _open_long_spread(self):
        gold_size, silver_size = self._target_sizes()
        self.buy_count += 1
        self.sell_count += 1
        self._submit(self.buy(data=self.gold, size=gold_size))
        self._submit(self.sell(data=self.silver, size=silver_size))
        self.current_spread_side = 1

    def _open_short_spread(self):
        gold_size, silver_size = self._target_sizes()
        self.sell_count += 1
        self.buy_count += 1
        self._submit(self.sell(data=self.gold, size=gold_size))
        self._submit(self.buy(data=self.silver, size=silver_size))
        self.current_spread_side = -1

    def _close_all(self):
        gold_pos = self.getposition(self.gold).size
        silver_pos = self.getposition(self.silver).size
        if gold_pos:
            self._submit(self.close(data=self.gold))
            if gold_pos > 0:
                self.sell_count += 1
            else:
                self.buy_count += 1
        if silver_pos:
            self._submit(self.close(data=self.silver))
            if silver_pos > 0:
                self.sell_count += 1
            else:
                self.buy_count += 1
        self.current_spread_side = 0

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.gold.datetime[0]), float(self.broker.getvalue())))
        self.spread_history.append(self._spread())
        zscore = self._zscore()
        if self.order_refs or zscore is None:
            return
        gold_pos = self.getposition(self.gold).size
        silver_pos = self.getposition(self.silver).size
        has_position = bool(gold_pos or silver_pos)
        if not has_position:
            if zscore <= -float(self.p.entry_threshold):
                self._open_long_spread()
            elif zscore >= float(self.p.entry_threshold):
                self._open_short_spread()
            return
        if abs(zscore) <= float(self.p.exit_threshold) or abs(zscore) >= float(self.p.stop_threshold):
            self._close_all()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trade_log.append({'pnlcomm': trade.pnlcomm})
