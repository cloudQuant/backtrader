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


def prepare_grid_data(frame):
    return frame[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()


class GridTradingDeltaHedgeStrategy(bt.Strategy):
    params = dict(
        grid_range_pct=0.08,
        num_grids=12,
        size_per_grid=0.08,
        base_position_pct=0.5,
        stop_loss_pct=0.15,
        reset_after_bars=96,
        commission_pct=0.0005,
        lot=0.1,
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
        self.grid_reset_count = 0
        self.center_price = None
        self.grid_levels = []
        self.entry_price = None
        self.last_grid_index = None
        self.bars_since_reset = 0

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

    def _setup_grid(self, price):
        lower = price * (1.0 - float(self.p.grid_range_pct))
        upper = price * (1.0 + float(self.p.grid_range_pct))
        self.center_price = price
        self.grid_levels = list(np.linspace(lower, upper, int(self.p.num_grids) + 1))
        self.entry_price = price
        self.last_grid_index = self._grid_index(price)
        self.bars_since_reset = 0
        self.grid_reset_count += 1

    def _grid_index(self, price):
        if not self.grid_levels:
            return None
        return int(np.searchsorted(self.grid_levels, price, side='right') - 1)

    def next(self):
        self.bar_num += 1
        data = self.datas[0]
        price = float(data.close[0])
        self.broker_value_series.append((bt.num2date(data.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        if self.center_price is None or self.bars_since_reset >= int(self.p.reset_after_bars):
            self._setup_grid(price)
        self.bars_since_reset += 1
        if self.entry_price and abs(price / self.entry_price - 1.0) > float(self.p.stop_loss_pct):
            self._setup_grid(price)
        current_grid_index = self._grid_index(price)
        if current_grid_index is None:
            return
        grid_mid = int(self.p.num_grids) // 2
        grid_offset = current_grid_index - grid_mid
        target_pct = float(self.p.base_position_pct) - grid_offset * float(self.p.size_per_grid)
        target_pct = max(0.0, min(1.0, target_pct))
        current_pos = float(self.getposition(data).size)
        target_size = self._target_size(data, target_pct)
        if abs(target_size - current_pos) < 0.01:
            self.last_grid_index = current_grid_index
            return
        if target_size > current_pos:
            self.buy_count += 1
        elif target_size < current_pos:
            self.sell_count += 1
        self._submit(self.order_target_size(data=data, target=target_size))
        self.last_grid_index = current_grid_index

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
