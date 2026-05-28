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
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class SimplestHedgingEaStrategy(bt.Strategy):
    params = dict(
        lots=1.0,
        stop_loss=76,
        take_profit=750,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.entry_cycle_count = 0

        self.order = None
        self.pending_orders = []
        self.layers = []
        self.last_bar_dt = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _submit_pair(self):
        if self.pending_orders:
            return False
        self.pending_orders = [
            {'side': 'buy', 'order': self.buy(size=self.p.lots)},
            {'side': 'sell', 'order': self.sell(size=self.p.lots)},
        ]
        self.entry_cycle_count += 1
        self.log(f'submit hedged pair lot={self.p.lots:.2f}')
        return True

    def _check_layer_exits(self):
        if not self.layers or self.pending_orders:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        to_close = []
        for idx, layer in enumerate(self.layers):
            if layer['side'] == 'buy':
                stop_hit = layer['stop_price'] is not None and low <= layer['stop_price']
                take_hit = layer['take_profit_price'] is not None and high >= layer['take_profit_price']
            else:
                stop_hit = layer['stop_price'] is not None and high >= layer['stop_price']
                take_hit = layer['take_profit_price'] is not None and low <= layer['take_profit_price']
            if stop_hit or take_hit:
                close_order = self.sell(size=layer['size']) if layer['side'] == 'buy' else self.buy(size=layer['size'])
                to_close.append({'index': idx, 'side': layer['side'], 'order': close_order, 'reason': 'take_profit' if take_hit and not stop_hit else 'stop_loss'})
        if to_close:
            self.pending_orders = to_close
            self.log(f'submit {len(to_close)} hedge leg exits')
            return True
        return False

    def next(self):
        self.bar_num += 1
        curr_dt = bt.num2date(self.data.datetime[0])
        if self._check_layer_exits():
            return
        if self.pending_orders:
            return
        if self.last_bar_dt == curr_dt:
            return
        self.last_bar_dt = curr_dt
        if not self.layers:
            self._submit_pair()

    def _create_layer(self, side, price, size):
        unit = self._unit()
        if side == 'buy':
            stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None
        else:
            stop_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None
            take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None
        return {
            'side': side,
            'size': abs(float(size)),
            'entry_price': float(price),
            'stop_price': stop_price,
            'take_profit_price': take_profit_price,
        }

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        matched = None
        for item in self.pending_orders:
            pending_order = item['order']
            if pending_order.ref == order.ref:
                matched = item
                break
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if matched is not None and 'index' not in matched:
                layer = self._create_layer(matched['side'], order.executed.price, order.executed.size)
                self.layers.append(layer)
                if matched['side'] == 'buy':
                    self.buy_count += 1
                else:
                    self.sell_count += 1
                self.log(f'{matched["side"]} filled price={layer["entry_price"]:.2f} sl={layer["stop_price"]} tp={layer["take_profit_price"]}')
            elif matched is not None:
                idx = matched['index']
                if 0 <= idx < len(self.layers):
                    self.log(f'{self.layers[idx]["side"]} leg closed reason={matched["reason"]} price={order.executed.price:.2f}')
                    self.layers[idx] = None
                self.layers = [layer for layer in self.layers if layer is not None]
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
            self.log(f'order failed status={order.getstatusname()}')
        if matched is not None and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.pending_orders = [item for item in self.pending_orders if item['order'].ref != order.ref]

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
