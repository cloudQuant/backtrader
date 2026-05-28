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
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'tick_volume', 'real_volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def build_setka_frame(df):
    out = df.copy()
    session = out.index.normalize()
    out['day_high'] = out.groupby(session)['high'].cummax()
    out['day_low'] = out.groupby(session)['low'].cummin()
    out['volume'] = out['tick_volume']
    return out


class SetkaFeed(bt.feeds.PandasData):
    lines = ('day_high', 'day_low')
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('day_high', 6),
        ('day_low', 7),
    )


class VrSetka3Strategy(bt.Strategy):
    params = dict(
        plus_points=5,
        take_profit_points=30,
        distance_points=30,
        step_distance_points=5,
        lots=0.0,
        percent=1.0,
        martin=True,
        proc=True,
        procent=1.3,
        point=0.01,
        digits_adjust=10,
        lot_step=0.01,
        min_lot=0.01,
        margin_per_lot=250.0,
        spread_points=0.0,
        price_digits=2,
    )

    def __init__(self):
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
        self.order = None
        self.pending_action = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _spread_value(self):
        return float(self.p.spread_points) * float(self.p.point)

    def _round_lot(self, size):
        step = max(float(self.p.lot_step), 1e-8)
        rounded = math.floor(size / step) * step
        return round(max(rounded, float(self.p.min_lot)), 8)

    def _base_lot(self):
        if float(self.p.lots) > 0:
            return self._round_lot(float(self.p.lots))
        free_cash = max(float(self.broker.getcash()), 0.0)
        margin = max(float(self.p.margin_per_lot), 1e-8)
        raw = free_cash * float(self.p.percent) / 100.0 / margin
        return self._round_lot(raw)

    def _next_lot(self):
        base = self._base_lot()
        if not bool(self.p.martin):
            return base
        factor = max(len(self.layers), 1)
        return self._round_lot(base * factor)

    def _side(self):
        if not self.layers:
            return None
        return self.layers[0]['side']

    def _op_buy(self):
        if not self.layers:
            return None
        buys = [layer['entry_price'] for layer in self.layers if layer['side'] == 'buy']
        return min(buys) if buys else None

    def _op_sell(self):
        if not self.layers:
            return None
        sells = [layer['entry_price'] for layer in self.layers if layer['side'] == 'sell']
        return max(sells) if sells else None

    def _weighted_avg(self):
        if not self.layers:
            return None
        notional = sum(layer['entry_price'] * layer['size'] for layer in self.layers)
        volume = sum(layer['size'] for layer in self.layers)
        return notional / volume if volume else None

    def _target_price(self):
        if not self.layers:
            return None
        side = self._side()
        spread = self._spread_value()
        if len(self.layers) == 1:
            entry = self.layers[0]['entry_price']
            tp_dist = float(self.p.take_profit_points) * self._unit()
            return round(entry + spread + tp_dist, int(self.p.price_digits)) if side == 'buy' else round(entry - spread - tp_dist, int(self.p.price_digits))
        avg = self._weighted_avg()
        plus = float(self.p.plus_points) * self._unit()
        return round(avg + plus, int(self.p.price_digits)) if side == 'buy' else round(avg - plus, int(self.p.price_digits))

    def _check_take_profit(self):
        if not self.layers or self.order is not None:
            return False
        target = self._target_price()
        if target is None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        side = self._side()
        hit = high >= target if side == 'buy' else low <= target
        if not hit:
            return False
        self.pending_action = {'type': 'close_all', 'reason': 'basket_tp'}
        self.order = self.close()
        self.log(f'close basket target={target:.2f} layers={len(self.layers)}')
        return True

    def _compute_signal(self):
        if len(self) < 2 or not bool(self.p.proc):
            return 0, 0
        close_now = float(self.data.close[0])
        day_high = float(self.data.day_high[0])
        day_low = float(self.data.day_low[0])
        prev_bull = float(self.data.close[-1]) > float(self.data.open[-1])
        prev_bear = float(self.data.close[-1]) < float(self.data.open[-1])
        x = 0.0
        y = 0.0
        if close_now > day_low:
            x = round(close_now * 100.0 / day_low - 100.0, 2)
        if close_now < day_high:
            y = round(close_now * 100.0 / day_high - 100.0, 2)
        sigup = 1 if (-float(self.p.procent) <= y and prev_bull) else 0
        sigdw = 1 if (float(self.p.procent) >= x and prev_bear) else 0
        return sigup, sigdw

    def _submit_open(self, side, reason):
        if self.order is not None:
            return False
        size = self._next_lot()
        self.pending_action = {'type': 'open', 'side': side, 'size': size, 'reason': reason}
        self.order = self.buy(size=size) if side == 'buy' else self.sell(size=size)
        self.signal_count += 1
        self.log(f'submit {side} size={size:.2f} reason={reason}')
        return True

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if self._check_take_profit():
            return
        sigup, sigdw = self._compute_signal()
        n = len(self.layers)
        dis = (float(self.p.distance_points) + float(self.p.step_distance_points) * n) * self._unit()
        spread = self._spread_value()
        ask = float(self.data.close[0])
        bid = float(self.data.close[0])
        buy_side = self._side() == 'buy'
        sell_side = self._side() == 'sell'
        op_b = self._op_buy()
        op_s = self._op_sell()

        if (n == 0 and sigup == 1) or (buy_side and op_b is not None and ask < op_b - dis + spread):
            self._submit_open('buy', 'signal' if n == 0 else 'grid_add')
            return
        if (n == 0 and sigdw == 1) or (sell_side and op_s is not None and bid > op_s + dis + spread):
            self._submit_open('sell', 'signal' if n == 0 else 'grid_add')

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        action = self.pending_action if self.order is not None and order.ref == self.order.ref else None
        if order.status == bt.Order.Completed and action is not None:
            self.completed_order_count += 1
            if action['type'] == 'open':
                layer = {
                    'side': action['side'],
                    'size': abs(float(order.executed.size)),
                    'entry_price': float(order.executed.price),
                }
                self.layers.append(layer)
                if action['side'] == 'buy':
                    self.buy_count += 1
                else:
                    self.sell_count += 1
                self.log(f'{action["side"]} filled price={layer["entry_price"]:.2f} size={layer["size"]:.2f} basket_layers={len(self.layers)}')
            elif action['type'] == 'close_all':
                self.layers = []
                self.log('basket fully closed')
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
            self.log(f'order failed status={order.getstatusname()}')
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None
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
