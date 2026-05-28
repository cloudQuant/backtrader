from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
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


class ExpFishingStrategy(bt.Strategy):
    params = dict(
        mm=0.1,
        mm_mode='LOT',
        price_step=300,
        pos_total=10,
        stop_loss=1000,
        take_profit=2000,
        size=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.signal_count = 0

        self.layers = []
        self.pending_order = None
        self.pending_action = None

    def log(self, text):
        dt = bt.num2date(self.data0.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _distance_unit(self):
        return self.p.point

    def _body_signal_threshold(self):
        return self.p.price_step * self._distance_unit()

    def _risk_distance(self, value):
        return value * self._distance_unit()

    def _layer_stop(self, side, entry_price):
        if self.p.stop_loss <= 0:
            return None
        dist = self._risk_distance(self.p.stop_loss)
        if side == 'buy':
            return round(entry_price - dist, self.p.price_digits)
        return round(entry_price + dist, self.p.price_digits)

    def _layer_take_profit(self, side, entry_price):
        if self.p.take_profit <= 0:
            return None
        dist = self._risk_distance(self.p.take_profit)
        if side == 'buy':
            return round(entry_price + dist, self.p.price_digits)
        return round(entry_price - dist, self.p.price_digits)

    def _position_side(self):
        if not self.position:
            return None
        return 'buy' if self.position.size > 0 else 'sell'

    def _current_price(self):
        return float(self.data0.close[0])

    def _submit_open(self, side):
        if self.pending_order is not None:
            return False
        size = float(self.p.size)
        self.signal_count += 1
        self.pending_action = {'type': 'open', 'side': side}
        self.pending_order = self.buy(size=size) if side == 'buy' else self.sell(size=size)
        self.log(f'submit {side} entry size={size:.2f}')
        return True

    def _submit_close(self, layer_indexes, reason):
        if self.pending_order is not None or not layer_indexes:
            return False
        close_size = sum(self.layers[idx]['size'] for idx in layer_indexes)
        if close_size <= 0:
            return False
        self.pending_action = {
            'type': 'close_layers',
            'indexes': sorted(layer_indexes),
            'reason': reason,
        }
        side = self._position_side()
        if side == 'buy':
            self.pending_order = self.sell(size=close_size)
        else:
            self.pending_order = self.buy(size=close_size)
        self.log(f'submit close size={close_size:.2f} reason={reason} layers={layer_indexes}')
        return True

    def _check_initial_entry(self):
        if self.layers or self.pending_order is not None:
            return False
        body = float(self.data0.close[0] - self.data0.open[0])
        threshold = self._body_signal_threshold()
        if body > threshold:
            return self._submit_open('buy')
        if -body > threshold:
            return self._submit_open('sell')
        return False

    def _check_pyramid(self):
        if not self.layers or self.pending_order is not None:
            return False
        addon_count = max(0, len(self.layers) - 1)
        if addon_count >= int(self.p.pos_total):
            return False
        last_layer = self.layers[-1]
        price = self._current_price()
        threshold = self._body_signal_threshold()
        if last_layer['side'] == 'buy' and price - last_layer['entry_price'] > threshold:
            return self._submit_open('buy')
        if last_layer['side'] == 'sell' and last_layer['entry_price'] - price > threshold:
            return self._submit_open('sell')
        return False

    def _check_layer_risk(self):
        if not self.layers or self.pending_order is not None:
            return False
        high = float(self.data0.high[0])
        low = float(self.data0.low[0])
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

    def next(self):
        self.bar_num += 1
        if len(self.data0) < 2:
            return
        if self._check_layer_risk():
            return
        if self._check_initial_entry():
            return
        self._check_pyramid()

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        action = self.pending_action if self.pending_order is not None and order.ref == self.pending_order.ref else None

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
                    f'sl={layer["stop_price"]} tp={layer["take_profit_price"]}'
                )
            elif action['type'] == 'close_layers':
                remaining = []
                closed_pnl = 0.0
                for idx, layer in enumerate(self.layers):
                    if idx in action['indexes']:
                        if layer['side'] == 'buy':
                            closed_pnl += (float(order.executed.price) - layer['entry_price']) * layer['size']
                        else:
                            closed_pnl += (layer['entry_price'] - float(order.executed.price)) * layer['size']
                    else:
                        remaining.append(layer)
                self.layers = remaining
                self.log(
                    f'partial/complete close filled price={float(order.executed.price):.2f} '
                    f'reason={action["reason"]} remaining_layers={len(self.layers)} pnl={closed_pnl:.2f}'
                )
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.log(f'order failed status={order.getstatusname()}')

        if self.pending_order is not None and order.ref == self.pending_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.pending_order = None
            self.pending_action = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
