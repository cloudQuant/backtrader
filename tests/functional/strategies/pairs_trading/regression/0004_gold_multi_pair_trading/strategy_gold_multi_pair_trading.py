from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import numpy as np
import pandas as pd

PAIR_SYMBOLS = ('XAGUSD', 'XPTUSD', 'XPDUSD')


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


def prepare_multi_pair_inputs(gold_df, pair_frames, params):
    common_index = gold_df.index
    for frame in pair_frames.values():
        common_index = common_index.intersection(frame.index)
    common_index = common_index.sort_values()

    gold = gold_df.loc[common_index].copy()
    pairs = {name: frame.loc[common_index].copy() for name, frame in pair_frames.items()}

    hedge_window = int(params.get('hedge_window', 120))
    zscore_window = int(params.get('zscore_window', 60))
    corr_window = int(params.get('corr_window', 60))

    signal_df = gold[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    log_gold = np.log(gold['close'].clip(lower=1e-6))

    for name in PAIR_SYMBOLS:
        other = pairs[name]
        log_other = np.log(other['close'].clip(lower=1e-6))
        rolling_cov = log_gold.rolling(hedge_window).cov(log_other)
        rolling_var = log_other.rolling(hedge_window).var().replace(0, np.nan)
        hedge_ratio = (rolling_cov / rolling_var).replace([np.inf, -np.inf], np.nan)
        spread = log_gold - hedge_ratio * log_other
        spread_mean = spread.rolling(zscore_window).mean()
        spread_std = spread.rolling(zscore_window).std().replace(0, np.nan)
        zscore = ((spread - spread_mean) / spread_std).replace([np.inf, -np.inf], np.nan)
        corr = gold['close'].rolling(corr_window).corr(other['close']).replace([np.inf, -np.inf], np.nan)
        signal_df[f'{name}_hedge_ratio'] = hedge_ratio
        signal_df[f'{name}_zscore'] = zscore
        signal_df[f'{name}_corr'] = corr

    return gold, pairs, signal_df.dropna()


class MultiPairSignalFeed(bt.feeds.PandasData):
    lines = (
        'xagusd_hedge_ratio', 'xagusd_zscore', 'xagusd_corr',
        'xptusd_hedge_ratio', 'xptusd_zscore', 'xptusd_corr',
        'xpdusd_hedge_ratio', 'xpdusd_zscore', 'xpdusd_corr',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('xagusd_hedge_ratio', 6), ('xagusd_zscore', 7), ('xagusd_corr', 8),
        ('xptusd_hedge_ratio', 9), ('xptusd_zscore', 10), ('xptusd_corr', 11),
        ('xpdusd_hedge_ratio', 12), ('xpdusd_zscore', 13), ('xpdusd_corr', 14),
    )


class GoldMultiPairTradingStrategy(bt.Strategy):
    params = dict(
        min_corr=0.6,
        entry_threshold=2.0,
        exit_threshold=0.5,
        stop_threshold=4.0,
        max_notional_pct=0.20,
        hedge_window=120,
        zscore_window=60,
        corr_window=60,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.gold = self.getdatabyname('XAUUSD')
        self.asset_map = {
            'XAGUSD': self.getdatabyname('XAGUSD'),
            'XPTUSD': self.getdatabyname('XPTUSD'),
            'XPDUSD': self.getdatabyname('XPDUSD'),
        }
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_log = []
        self.broker_value_series = []
        self.active_pair = None
        self.active_side = 0

    def _line_name(self, symbol, suffix):
        return f'{symbol.lower()}_{suffix}'

    def _pair_metrics(self, symbol):
        zscore = float(getattr(self.signal, self._line_name(symbol, 'zscore'))[0])
        corr = float(getattr(self.signal, self._line_name(symbol, 'corr'))[0])
        hedge_ratio = float(getattr(self.signal, self._line_name(symbol, 'hedge_ratio'))[0])
        return zscore, corr, hedge_ratio

    def _target_sizes(self, pair_symbol, hedge_ratio):
        portfolio_value = float(self.broker.getvalue())
        gold_price = max(float(self.gold.close[0]), 1e-6)
        other_price = max(float(self.asset_map[pair_symbol].close[0]), 1e-6)
        leg_notional = portfolio_value * float(self.p.max_notional_pct)
        gold_size = max(round(leg_notional / gold_price, 2), 0.01)
        other_notional = leg_notional * max(abs(hedge_ratio), 0.5)
        other_size = max(round(other_notional / other_price, 2), 0.01)
        return gold_size, other_size

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _open_pair(self, pair_symbol, side, hedge_ratio):
        gold_size, other_size = self._target_sizes(pair_symbol, hedge_ratio)
        other = self.asset_map[pair_symbol]
        if side > 0:
            self.buy_count += 1
            self.sell_count += 1
            self._submit(self.buy(data=self.gold, size=gold_size))
            self._submit(self.sell(data=other, size=other_size))
        else:
            self.sell_count += 1
            self.buy_count += 1
            self._submit(self.sell(data=self.gold, size=gold_size))
            self._submit(self.buy(data=other, size=other_size))
        self.active_pair = pair_symbol
        self.active_side = side

    def _close_all(self):
        for data in [self.gold] + list(self.asset_map.values()):
            pos = self.getposition(data).size
            if pos:
                self._submit(self.close(data=data))
                if pos > 0:
                    self.sell_count += 1
                else:
                    self.buy_count += 1
        self.active_pair = None
        self.active_side = 0

    def _select_pair(self):
        candidate = None
        best_abs_z = 0.0
        for symbol in PAIR_SYMBOLS:
            zscore, corr, hedge_ratio = self._pair_metrics(symbol)
            if math.isnan(zscore) or math.isnan(corr) or math.isnan(hedge_ratio):
                continue
            if corr < float(self.p.min_corr):
                continue
            abs_z = abs(zscore)
            if abs_z > best_abs_z:
                best_abs_z = abs_z
                candidate = (symbol, zscore, hedge_ratio)
        return candidate

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        candidate = self._select_pair()
        has_position = any(self.getposition(data).size for data in [self.gold] + list(self.asset_map.values()))
        if not has_position:
            if candidate is None:
                return
            symbol, zscore, hedge_ratio = candidate
            if zscore <= -float(self.p.entry_threshold):
                self._open_pair(symbol, side=1, hedge_ratio=hedge_ratio)
            elif zscore >= float(self.p.entry_threshold):
                self._open_pair(symbol, side=-1, hedge_ratio=hedge_ratio)
            return
        if self.active_pair is None:
            self._close_all()
            return
        zscore, corr, _ = self._pair_metrics(self.active_pair)
        if math.isnan(zscore) or math.isnan(corr) or corr < float(self.p.min_corr):
            self._close_all()
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
