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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
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


def prepare_pairs_inputs(asset_map):
    aligned_index = None
    prepared = {}
    for symbol, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in asset_map.items():
        prepared[symbol] = frame.loc[aligned_index][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    close_df = pd.DataFrame({symbol: frame.loc[aligned_index, 'close'] for symbol, frame in asset_map.items()}, index=aligned_index)
    return prepared, close_df, aligned_index


class CADCrudePairsStrategy(bt.Strategy):
    params = dict(
        formation_period=252,
        lookback=60,
        entry_z=2.0,
        exit_z=0.25,
        position_size=0.5,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.broker_value_series = []
        self.signal_count = 0
        self.last_zscore = 0.0

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _target_size(self, data, target_pct):
        broker_value = float(self.broker.getvalue())
        price = float(data.close[0])
        if broker_value <= 0 or price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * abs(float(target_pct)) / (price * multiplier)
        size = max(0.01, round(size, 2))
        return size if target_pct >= 0 else -size

    def next(self):
        self.bar_num += 1
        cad = self.datas[0]
        crude = self.datas[1]
        self.broker_value_series.append((bt.num2date(cad.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        required = max(int(self.p.formation_period), int(self.p.lookback))
        if len(cad) <= required or len(crude) <= required:
            return
        cad_prices = np.array([float(cad.close[-i]) for i in range(required - 1, -1, -1)], dtype=float)
        crude_prices = np.array([float(crude.close[-i]) for i in range(required - 1, -1, -1)], dtype=float)
        if np.any(cad_prices <= 0) or np.any(crude_prices <= 0):
            return
        log_cad = np.log(cad_prices)
        log_crude = np.log(crude_prices)
        hedge_ratio = float(np.polyfit(log_crude, log_cad, 1)[0]) if np.std(log_crude) > 0 else 1.0
        spread = pd.Series(log_cad - hedge_ratio * log_crude)
        lookback = int(self.p.lookback)
        mean = float(spread.iloc[-lookback:].mean())
        std = float(spread.iloc[-lookback:].std())
        if std <= 0:
            return
        zscore = float((spread.iloc[-1] - mean) / std)
        self.last_zscore = zscore
        current_cad = float(self.getposition(cad).size)
        current_crude = float(self.getposition(crude).size)
        cad_target_pct = 0.0
        crude_target_pct = 0.0
        if zscore > float(self.p.entry_z):
            cad_target_pct = -float(self.p.position_size)
            crude_target_pct = float(self.p.position_size)
            self.signal_count += 1
        elif zscore < -float(self.p.entry_z):
            cad_target_pct = float(self.p.position_size)
            crude_target_pct = -float(self.p.position_size)
            self.signal_count += 1
        elif abs(zscore) < float(self.p.exit_z):
            cad_target_pct = 0.0
            crude_target_pct = 0.0
        else:
            cad_target_pct = float(current_cad > 0) * float(self.p.position_size) - float(current_cad < 0) * float(self.p.position_size)
            crude_target_pct = float(current_crude > 0) * float(self.p.position_size) - float(current_crude < 0) * float(self.p.position_size)
        cad_target_size = self._target_size(cad, cad_target_pct)
        crude_target_size = self._target_size(crude, crude_target_pct)
        if abs(cad_target_size - current_cad) >= 0.01:
            if cad_target_size > current_cad:
                self.buy_count += 1
            elif cad_target_size < current_cad:
                self.sell_count += 1
            self._submit(self.order_target_size(data=cad, target=cad_target_size))
        if abs(crude_target_size - current_crude) >= 0.01:
            if crude_target_size > current_crude:
                self.buy_count += 1
            elif crude_target_size < current_crude:
                self.sell_count += 1
            self._submit(self.order_target_size(data=crude, target=crude_target_size))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
