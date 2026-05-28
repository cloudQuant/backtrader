from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
    })
    if '<VOL>' in df.columns:
        df['openinterest'] = df['<VOL>']
    else:
        df['openinterest'] = 0
    df['volume'] = df['tick_volume']
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
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class BackboneStrategy(bt.Strategy):
    params = dict(
        max_risk=0.5,
        ntmax=10,
        take_profit=170,
        stop_loss=40,
        trailing_stop=300,
        point=0.01,
        price_digits=2,
        contract_size=100.0,
        lot_step=0.01,
        lot_min=0.01,
        lot_max=100.0,
        leverage=100.0,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.layers = []
        self.pending_order = None
        self.pending_action = None
        self.last_position = 0
        self.bid_max = 0.0
        self.ask_min = float('inf')

    def log(self, text):
        dt = bt.num2date(self.data0.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _distance_unit(self):
        digits_adjust = 10 if int(self.p.price_digits) in (3, 5) else 1
        return float(self.p.point) * digits_adjust

    def _current_price(self):
        return float(self.data0.close[0])

    def _normalize_size(self, size):
        size = round(float(size) / float(self.p.lot_step), 0) * float(self.p.lot_step)
        size = max(size, float(self.p.lot_min))
        size = min(size, float(self.p.lot_max))
        return round(size, 2)

    def _calc_volume(self, total):
        ntmax = max(int(self.p.ntmax), 1)
        denominator = ntmax / max(float(self.p.max_risk), 1e-9) - float(total)
        if denominator <= 0:
            return 0.0
        frac = 1.0 / denominator
        stop_distance = float(self.p.stop_loss) * self._distance_unit()
        if stop_distance <= 0:
            return 0.0
        risk_budget = float(self.broker.getcash()) * frac
        risk_per_lot = stop_distance * float(self.p.contract_size)
        if risk_per_lot <= 0:
            return 0.0
        volume = risk_budget / risk_per_lot
        return self._normalize_size(volume)

    def _layer_stop(self, side, entry_price):
        if float(self.p.stop_loss) <= 0:
            return None
        distance = float(self.p.stop_loss) * self._distance_unit()
        if side == 'buy':
            return round(entry_price - distance, self.p.price_digits)
        return round(entry_price + distance, self.p.price_digits)

    def _layer_take_profit(self, side, entry_price):
        if float(self.p.take_profit) <= 0:
            return None
        distance = float(self.p.take_profit) * self._distance_unit()
        if side == 'buy':
            return round(entry_price + distance, self.p.price_digits)
        return round(entry_price - distance, self.p.price_digits)

    def _position_side(self):
        if not self.position:
            return None
        return 'buy' if self.position.size > 0 else 'sell'

    def _submit_open(self, side, size):
        if self.pending_order is not None or size <= 0:
            return False
        self.signal_count += 1
        self.pending_action = {'type': 'open', 'side': side, 'size': size}
        self.pending_order = self.buy(size=size) if side == 'buy' else self.sell(size=size)
        self.log(f'submit {side} size={size:.2f}')
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
        self.pending_order = self.sell(size=close_size) if side == 'buy' else self.buy(size=close_size)
        self.log(f'submit close size={close_size:.2f} reason={reason} layers={layer_indexes}')
        return True

    def _update_initial_extremes(self):
        price = self._current_price()
        if self.last_position != 0:
            return
        if price > self.bid_max:
            self.bid_max = price
        if price < self.ask_min:
            self.ask_min = price
        threshold = float(self.p.trailing_stop) * self._distance_unit()
        if threshold <= 0:
            return
        if price < self.bid_max - threshold:
            self.last_position = -1
        if price > self.ask_min + threshold:
            self.last_position = 1

    def _check_add_or_first_entry(self):
        total = len(self.layers)
        if total >= int(self.p.ntmax):
            return False
        size = self._calc_volume(total)
        if size <= 0:
            return False
        if (self.last_position == -1 and total == 0) or (self.last_position == 1 and total > 0):
            self.last_position = 1
            return self._submit_open('buy', size)
        if (self.last_position == 1 and total == 0) or (self.last_position == -1 and total > 0):
            self.last_position = -1
            return self._submit_open('sell', size)
        return False

    def _update_layer_trailing(self):
        if not self.layers or float(self.p.trailing_stop) <= 0:
            return
        distance = float(self.p.trailing_stop) * self._distance_unit()
        price = self._current_price()
        for layer in self.layers:
            if layer['side'] == 'buy':
                if price - layer['entry_price'] > distance:
                    candidate = round(price - distance, self.p.price_digits)
                    if layer['stop_price'] is None or candidate > layer['stop_price']:
                        layer['stop_price'] = candidate
            else:
                if layer['entry_price'] - price > distance:
                    candidate = round(price + distance, self.p.price_digits)
                    if layer['stop_price'] is None or candidate < layer['stop_price']:
                        layer['stop_price'] = candidate

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
        self._update_initial_extremes()
        self._update_layer_trailing()
        if self._check_layer_risk():
            return
        if self.pending_order is not None:
            return
        self._check_add_or_first_entry()

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        action = self.pending_action if self.pending_order is not None and order.ref == self.pending_order.ref else None
        if order.status == bt.Order.Completed and action is not None:
            self.completed_order_count += 1
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
                    self.last_position = 1
                else:
                    self.sell_count += 1
                    self.last_position = -1
                self.log(f'{side} filled price={entry_price:.2f} size={layer["size"]:.2f} sl={layer["stop_price"]} tp={layer["take_profit_price"]}')
            elif action['type'] == 'close_layers':
                remaining = []
                closed_pnl = 0.0
                fill_price = float(order.executed.price)
                for idx, layer in enumerate(self.layers):
                    if idx in action['indexes']:
                        if layer['side'] == 'buy':
                            closed_pnl += (fill_price - layer['entry_price']) * layer['size'] * float(self.p.contract_size)
                        else:
                            closed_pnl += (layer['entry_price'] - fill_price) * layer['size'] * float(self.p.contract_size)
                    else:
                        remaining.append(layer)
                self.layers = remaining
                if not self.layers:
                    self.last_position = 0
                    self.bid_max = 0.0
                    self.ask_min = float('inf')
                self.log(f'close filled price={fill_price:.2f} reason={action["reason"]} remaining_layers={len(self.layers)} pnl={closed_pnl:.2f}')
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
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
