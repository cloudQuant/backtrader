from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

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


def _simulate_put_write_series(price_df, params):
    roll_days = int(params.get('put_roll_days', 21))
    vol_window = int(params.get('put_vol_window', 21))
    premium_factor = float(params.get('put_premium_factor', 0.32))
    moneyness = float(params.get('put_moneyness', 1.0))

    frame = price_df.copy()
    frame['returns'] = frame['close'].pct_change().fillna(0.0)
    frame['realized_vol'] = frame['returns'].rolling(vol_window).std().fillna(0.0) * math.sqrt(252.0)
    nav = [100.0]
    day_counter = 0
    premium_bucket = 0.0
    strike = None

    for i in range(1, len(frame)):
        spot_prev = float(frame['close'].iloc[i - 1])
        spot = float(frame['close'].iloc[i])
        realized_vol = max(float(frame['realized_vol'].iloc[i - 1]), 0.05)
        ret = (spot / spot_prev - 1.0) if spot_prev > 0 else 0.0

        if day_counter <= 0 or strike is None:
            strike = spot_prev * moneyness
            premium_bucket = realized_vol * math.sqrt(max(roll_days, 1) / 252.0) * premium_factor
            day_counter = roll_days

        theta_income = premium_bucket / max(day_counter, 1)
        intrinsic_loss = min(ret, 0.0)
        daily_return = theta_income + intrinsic_loss
        nav.append(nav[-1] * (1.0 + daily_return))
        day_counter -= 1

    series = pd.Series(nav, index=frame.index, name='close')
    out = pd.DataFrame(index=frame.index)
    out['close'] = series
    out['open'] = out['close'].shift(1).fillna(out['close'])
    out['high'] = out[['open', 'close']].max(axis=1)
    out['low'] = out[['open', 'close']].min(axis=1)
    out['volume'] = 0.0
    out['openinterest'] = 0.0
    return out[['open', 'high', 'low', 'close', 'volume', 'openinterest']]


def prepare_low_vol_options_inputs(asset_map, params):
    fromdate_index = None
    prepared_map = {}
    for symbol, df in asset_map.items():
        prepared_map[symbol] = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy().sort_index()
        fromdate_index = prepared_map[symbol].index if fromdate_index is None else fromdate_index.intersection(prepared_map[symbol].index)
    if fromdate_index is None or len(fromdate_index) == 0:
        raise ValueError('No overlapping data available for low volatility options strategy')
    fromdate_index = fromdate_index.sort_values()
    prepared_map = {symbol: frame.loc[fromdate_index].copy() for symbol, frame in prepared_map.items()}

    put_write_frame = _simulate_put_write_series(prepared_map['equity_proxy'], params)
    prepared_map['put_write'] = put_write_frame.loc[fromdate_index].copy()

    close_df = pd.concat(
        [prepared_map['low_vol'][['close']].rename(columns={'close': 'low_vol'}),
         prepared_map['covered_call'][['close']].rename(columns={'close': 'covered_call'}),
         prepared_map['put_write'][['close']].rename(columns={'close': 'put_write'})],
        axis=1,
    ).dropna(how='any')
    aligned_index = close_df.index
    prepared_map = {symbol: frame.loc[aligned_index].copy() for symbol, frame in prepared_map.items() if symbol in ('low_vol', 'covered_call', 'put_write')}
    return prepared_map, close_df, aligned_index


class LowVolatilityOptionsStrategy(bt.Strategy):
    params = dict(
        weights=None,
        rebalance_interval_days=63,
        rebalance_threshold=0.05,
        max_drawdown=0.20,
        drawdown_risk_scale=0.50,
        vol_target=0.12,
        put_moneyness=1.0,
        put_premium_factor=0.32,
        put_roll_days=21,
        put_vol_window=21,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.rebalance_count = 0
        self.pending_orders = []
        self.broker_value_series = []
        self.peak_value = float(self.broker.getvalue())
        self.target_weights = dict(self.p.weights or {})
        total = sum(self.target_weights.values()) or 1.0
        self.target_weights = {key: float(value) / total for key, value in self.target_weights.items()}
        self.data_by_name = {data._name: data for data in self.datas}

    def _cancel_pending(self):
        for order in self.pending_orders:
            if order is not None:
                self.cancel(order)
        self.pending_orders = []

    def _current_weights(self):
        portfolio_value = float(self.broker.getvalue())
        if portfolio_value <= 0:
            return {name: 0.0 for name in self.target_weights}
        weights = {}
        for name, data in self.data_by_name.items():
            position = self.getposition(data)
            weights[name] = float(position.size) * float(data.close[0]) / portfolio_value if position.size else 0.0
        return weights

    def _risk_scaled_weights(self):
        current_value = float(self.broker.getvalue())
        self.peak_value = max(self.peak_value, current_value)
        drawdown = (self.peak_value - current_value) / self.peak_value if self.peak_value > 0 else 0.0
        scale = 1.0
        if drawdown > float(self.p.max_drawdown):
            scale = float(self.p.drawdown_risk_scale)
        return {name: weight * scale for name, weight in self.target_weights.items()}

    def _needs_rebalance(self, weights):
        current_weights = self._current_weights()
        for name, target in weights.items():
            if abs(current_weights.get(name, 0.0) - target) > float(self.p.rebalance_threshold):
                return True
        return False

    def _rebalance(self, weights):
        for name, target in weights.items():
            data = self.data_by_name[name]
            position = self.getposition(data)
            if position.size and target <= 0:
                self.sell_count += 1
            elif target > 0 and not position.size:
                self.buy_count += 1
            self.pending_orders.append(self.order_target_percent(data=data, target=target))
        self.rebalance_count += 1

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.datas[0].datetime[0]), float(self.broker.getvalue())))
        if self.pending_orders:
            return
        if self.bar_num == 1 or self.bar_num % int(self.p.rebalance_interval_days) == 0:
            weights = self._risk_scaled_weights()
            if self.bar_num == 1 or self._needs_rebalance(weights):
                for name, target in weights.items():
                    data = self.data_by_name[name]
                    current_position = self.getposition(data)
                    current_value = float(current_position.size) * float(data.close[0]) if current_position.size else 0.0
                    current_weight = current_value / float(self.broker.getvalue()) if float(self.broker.getvalue()) > 0 else 0.0
                    if target > current_weight:
                        self.buy_count += 1
                    elif current_position.size and target < current_weight:
                        self.sell_count += 1
                    self.pending_orders.append(self.order_target_percent(data=data, target=target))
                self.rebalance_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_orders = [pending for pending in self.pending_orders if pending.ref != order.ref]
