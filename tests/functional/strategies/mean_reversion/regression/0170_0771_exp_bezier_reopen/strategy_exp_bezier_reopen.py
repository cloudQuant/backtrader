from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class BezierFeed(bt.feeds.PandasData):
    lines = ('bezier',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('bezier', 6),
    )


def build_resampled_frame(df, indicator_minutes):
    rule = f'{int(indicator_minutes)}min'
    signal_df = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    signal_df = signal_df.dropna(subset=['open', 'high', 'low', 'close']).copy()
    signal_df['openinterest'] = signal_df['openinterest'].fillna(0)
    return signal_df


def factorial(value):
    result = 1
    for i in range(2, int(value) + 1):
        result *= i
    return result


def applied_price(df, code):
    open_ = df['open'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)

    code = int(code)
    if code == 1:
        return close
    if code == 2:
        return open_
    if code == 3:
        return high
    if code == 4:
        return low
    if code == 5:
        return (high + low) / 2.0
    if code == 6:
        return (close + high + low) / 3.0
    if code == 7:
        return (2.0 * close + high + low) / 4.0
    if code == 8:
        return (open_ + close) / 2.0
    if code == 9:
        return (open_ + close + high + low) / 4.0
    if code == 10:
        return pd.Series(
            [high.iloc[i] if close.iloc[i] > open_.iloc[i] else low.iloc[i] if close.iloc[i] < open_.iloc[i] else close.iloc[i] for i in range(len(df))],
            index=df.index,
            dtype=float,
        )
    if code == 11:
        return pd.Series(
            [
                (high.iloc[i] + close.iloc[i]) / 2.0 if close.iloc[i] > open_.iloc[i]
                else (low.iloc[i] + close.iloc[i]) / 2.0 if close.iloc[i] < open_.iloc[i]
                else close.iloc[i]
                for i in range(len(df))
            ],
            index=df.index,
            dtype=float,
        )
    return close


def build_bezier_frame(df, indicator_minutes, bperiod, t, ipc, price_shift_points=0, point=0.01):
    signal_df = build_resampled_frame(df, indicator_minutes)
    period = int(bperiod)
    t = min(max(float(t), 0.0), 1.0)
    price_shift = float(point) * float(price_shift_points)
    src = applied_price(signal_df, ipc)
    bezier_values = [math.nan] * len(signal_df)

    period_factorial = factorial(period)
    weights = []
    for iii in range(period, -1, -1):
        weight = (period_factorial / (factorial(iii) * factorial(period - iii))) * (t ** iii) * ((1.0 - t) ** (period - iii))
        weights.append(weight)

    src_values = src.astype(float).tolist()
    for idx in range(len(signal_df)):
        if idx < period + 1:
            continue
        value = 0.0
        start = idx - period
        for offset, weight in enumerate(weights):
            value += src_values[start + offset] * weight + price_shift
        bezier_values[idx] = value

    signal_df = signal_df.copy()
    signal_df['bezier'] = bezier_values
    return signal_df


class ExpBezierReopenStrategy(bt.Strategy):
    params = dict(
        signal_bar=1,
        size=0.1,
        price_step=300,
        pos_total=10,
        stop_loss_points=1000,
        take_profit_points=2000,
        point=0.01,
        price_digits=2,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=240,
        bperiod=8,
        t=0.5,
        ipc=7,
        price_shift_points=0,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal = self.datas[1]
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.layers = []
        self.pending_order = None
        self.pending_action = None
        self._last_signal_len = 0

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _distance(self, points):
        return float(points) * float(self.p.point)

    def _pyramid_threshold(self):
        return self._distance(self.p.price_step)

    def _layer_stop(self, side, entry_price):
        if float(self.p.stop_loss_points) <= 0:
            return None
        dist = self._distance(self.p.stop_loss_points)
        if side == 'buy':
            return round(entry_price - dist, int(self.p.price_digits))
        return round(entry_price + dist, int(self.p.price_digits))

    def _layer_take_profit(self, side, entry_price):
        if float(self.p.take_profit_points) <= 0:
            return None
        dist = self._distance(self.p.take_profit_points)
        if side == 'buy':
            return round(entry_price + dist, int(self.p.price_digits))
        return round(entry_price - dist, int(self.p.price_digits))

    def _position_side(self):
        if self.layers:
            return self.layers[-1]['side']
        if not self.position:
            return None
        return 'buy' if self.position.size > 0 else 'sell'

    def _current_price(self):
        return float(self.base.close[0])

    def _line_value(self, line, ago):
        return float(line[-ago]) if ago else float(line[0])

    def _has_value(self, value):
        return math.isfinite(value) and not math.isnan(value)

    def _submit_open(self, side, trigger):
        if self.pending_order is not None:
            return False
        size = float(self.p.size)
        if size <= 0:
            return False
        self.pending_action = {'type': 'open', 'side': side, 'trigger': trigger}
        self.pending_order = self.buy(size=size) if side == 'buy' else self.sell(size=size)
        self.log(f'submit {side} entry size={size:.2f} trigger={trigger}')
        return True

    def _submit_close(self, layer_indexes, reason, reopen_side=None):
        if self.pending_order is not None or not layer_indexes:
            return False
        close_size = sum(self.layers[idx]['size'] for idx in layer_indexes)
        if close_size <= 0:
            return False
        self.pending_action = {
            'type': 'close_layers',
            'indexes': sorted(layer_indexes),
            'reason': reason,
            'reopen_side': reopen_side,
        }
        if self._position_side() == 'buy':
            self.pending_order = self.sell(size=close_size)
        else:
            self.pending_order = self.buy(size=close_size)
        self.log(f'submit close size={close_size:.2f} reason={reason} layers={layer_indexes}')
        return True

    def _check_layer_risk(self):
        if not self.layers or self.pending_order is not None:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        to_close = []
        reason = None
        for idx, layer in enumerate(self.layers):
            if layer['side'] == 'buy':
                stop_hit = layer['stop_price'] is not None and low <= layer['stop_price']
                take_hit = layer['take_profit_price'] is not None and high >= layer['take_profit_price']
            else:
                stop_hit = layer['stop_price'] is not None and high >= layer['stop_price']
                take_hit = layer['take_profit_price'] is not None and low <= layer['take_profit_price']
            if stop_hit or take_hit:
                to_close.append(idx)
                if reason is None:
                    reason = 'take_profit' if take_hit and not stop_hit else 'stop_loss'
        if to_close:
            return self._submit_close(to_close, reason or 'risk_exit')
        return False

    def _check_indicator_signal(self):
        signal_bar = max(int(self.p.signal_bar), 1)
        if len(self.signal) < signal_bar + 2:
            return False
        current_signal_len = len(self.signal)
        if current_signal_len == self._last_signal_len:
            return False
        self._last_signal_len = current_signal_len

        recent_ago = signal_bar - 1
        mid_ago = signal_bar
        old_ago = signal_bar + 1
        recent = self._line_value(self.signal.bezier, recent_ago)
        mid = self._line_value(self.signal.bezier, mid_ago)
        old = self._line_value(self.signal.bezier, old_ago)
        if not self._has_value(recent) or not self._has_value(mid) or not self._has_value(old):
            return False

        buy_signal = old > mid and recent > mid
        sell_signal = old < mid and recent < mid
        side = self._position_side()

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal old={old:.2f} mid={mid:.2f} recent={recent:.2f}')
            if side == 'sell' and self.p.sell_pos_close:
                reopen_side = 'buy' if self.p.buy_pos_open else None
                return self._submit_close(list(range(len(self.layers))), 'reverse_to_buy', reopen_side=reopen_side)
            if not self.layers and self.p.buy_pos_open:
                return self._submit_open('buy', 'signal')
            return False

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal old={old:.2f} mid={mid:.2f} recent={recent:.2f}')
            if side == 'buy' and self.p.buy_pos_close:
                reopen_side = 'sell' if self.p.sell_pos_open else None
                return self._submit_close(list(range(len(self.layers))), 'reverse_to_sell', reopen_side=reopen_side)
            if not self.layers and self.p.sell_pos_open:
                return self._submit_open('sell', 'signal')
        return False

    def _check_pyramid(self):
        if not self.layers or self.pending_order is not None:
            return False
        addon_count = max(0, len(self.layers) - 1)
        if addon_count >= int(self.p.pos_total):
            return False
        last_layer = self.layers[-1]
        price = self._current_price()
        threshold = self._pyramid_threshold()
        if last_layer['side'] == 'buy' and price - last_layer['entry_price'] > threshold:
            return self._submit_open('buy', 'pyramid')
        if last_layer['side'] == 'sell' and last_layer['entry_price'] - price > threshold:
            return self._submit_open('sell', 'pyramid')
        return False

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return
        if self._check_layer_risk():
            return
        if self._check_indicator_signal():
            return
        self._check_pyramid()

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        action = self.pending_action if self.pending_order is not None and order.ref == self.pending_order.ref else None
        reopen_side = None

        if order.status == bt.Order.Completed and action is not None:
            if action['type'] == 'open':
                side = action['side']
                entry_price = float(order.executed.price)
                layer = {
                    'side': side,
                    'size': abs(float(order.executed.size)),
                    'entry_price': entry_price,
                    'stop_price': self._layer_stop(side, entry_price),
                    'take_profit_price': self._layer_take_profit(side, entry_price),
                }
                self.layers.append(layer)
                if side == 'buy':
                    self.buy_count += 1
                else:
                    self.sell_count += 1
                self.log(
                    f'{side} filled price={entry_price:.2f} size={layer["size"]:.2f} '
                    f'sl={layer["stop_price"]} tp={layer["take_profit_price"]} trigger={action["trigger"]}'
                )
            elif action['type'] == 'close_layers':
                remaining = []
                closed_pnl = 0.0
                reopen_side = action.get('reopen_side')
                exit_price = float(order.executed.price)
                for idx, layer in enumerate(self.layers):
                    if idx in action['indexes']:
                        if layer['side'] == 'buy':
                            closed_pnl += (exit_price - layer['entry_price']) * layer['size']
                        else:
                            closed_pnl += (layer['entry_price'] - exit_price) * layer['size']
                    else:
                        remaining.append(layer)
                self.layers = remaining
                self.log(
                    f'partial/complete close filled price={exit_price:.2f} '
                    f'reason={action["reason"]} remaining_layers={len(self.layers)} pnl={closed_pnl:.2f}'
                )
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.log(f'order failed status={order.getstatusname()}')

        if self.pending_order is not None and order.ref == self.pending_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.pending_order = None
            self.pending_action = None
            if reopen_side is not None and not self.layers:
                self._submit_open(reopen_side, 'signal_reopen')

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
