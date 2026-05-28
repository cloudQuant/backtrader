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


def prepare_asset_data(asset_map):
    aligned_index = None
    prepared = {}
    for symbol, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in asset_map.items():
        prepared[symbol] = frame.loc[aligned_index][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    return prepared, aligned_index


class EquityBondAllocationStrategy(bt.Strategy):
    params = dict(
        signal_lookback=63,
        signal_threshold=0.5,
        equity_high=0.65,
        equity_low=0.20,
        equity_neutral=0.45,
        gold_risk_on=0.05,
        gold_risk_off=0.25,
        gold_neutral=0.15,
        rebalance_interval_days=63,
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
        self.rebalance_count = 0
        self.risk_on_days = 0
        self.risk_off_days = 0
        self.neutral_days = 0

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

    def _survey_signal_proxy(self):
        equity = self.datas[0]
        bond = self.datas[1]
        lookback = int(self.p.signal_lookback)
        if len(equity) <= lookback or len(bond) <= lookback:
            return None
        equity_ret = float(equity.close[0] / equity.close[-lookback] - 1.0)
        bond_ret = float(bond.close[0] / bond.close[-lookback] - 1.0)
        signal = equity_ret - bond_ret
        history = []
        for offset in range(lookback, 2 * lookback):
            if len(equity) <= offset or len(bond) <= offset:
                continue
            history.append(float(equity.close[-offset] / equity.close[-offset + lookback] - 1.0) - float(bond.close[-offset] / bond.close[-offset + lookback] - 1.0))
        history_series = pd.Series(history, dtype=float)
        if history_series.empty or history_series.std() == 0:
            return None
        zscore = (signal - history_series.mean()) / history_series.std()
        return float(zscore)

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.datas[0].datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        signal_value = self._survey_signal_proxy()
        if signal_value is None:
            return
        threshold = float(self.p.signal_threshold)
        if signal_value > threshold:
            equity_weight = float(self.p.equity_high)
            gold_weight = float(self.p.gold_risk_on)
            self.risk_on_days += 1
        elif signal_value < -threshold:
            equity_weight = float(self.p.equity_low)
            gold_weight = float(self.p.gold_risk_off)
            self.risk_off_days += 1
        else:
            equity_weight = float(self.p.equity_neutral)
            gold_weight = float(self.p.gold_neutral)
            self.neutral_days += 1
        bond_weight = max(0.0, 1.0 - equity_weight - gold_weight)
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        target_map = {
            self.datas[0]._name: equity_weight,
            self.datas[1]._name: bond_weight,
            self.datas[2]._name: gold_weight,
        }
        self.rebalance_count += 1
        for data in self.datas:
            target_pct = target_map.get(data._name, 0.0)
            current_pos = float(self.getposition(data).size)
            target_size = self._target_size(data, target_pct)
            if abs(target_size - current_pos) < 0.01:
                continue
            if target_size > current_pos:
                self.buy_count += 1
            elif target_size < current_pos:
                self.sell_count += 1
            self._submit(self.order_target_size(data=data, target=target_size))

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
