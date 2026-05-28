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


class ExpertNewsStrategy(bt.Strategy):
    params = dict(
        stoploss=10,
        takeprofit=50,
        trailing_stop=10,
        trailing_start=0,
        step_trail=2,
        no_loss=0,
        min_profit_no_loss=0,
        step=10,
        lot=0.1,
        time_modify_seconds=300,
        point=0.01,
        digits_adjust=10,
        spread_points=0.0,
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
        self.pending_trigger_count = 0

        self.order = None
        self.pending_action = None
        self.reopen_side = None

        self.buy_stop_order = None
        self.sell_stop_order = None
        self.stop_price = None
        self.take_profit_price = None
        self.position_side = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _spread(self):
        return float(self.p.spread_points) * float(self.p.point)

    def _min_modify_delta(self):
        return float(self.p.step_trail) * self._unit()

    def _elapsed_seconds(self, last_dt, curr_dt):
        if last_dt is None:
            return float('inf')
        return max((curr_dt - last_dt).total_seconds(), 0.0)

    def _make_pending(self, side, price, curr_dt):
        stoploss = float(self.p.stoploss) * self._unit()
        takeprofit = float(self.p.takeprofit) * self._unit()
        if side == 'buy':
            sl = round(price - stoploss, int(self.p.price_digits)) if self.p.stoploss > 0 else None
            tp = round(price + takeprofit, int(self.p.price_digits)) if self.p.takeprofit > 0 else None
        else:
            sl = round(price + stoploss, int(self.p.price_digits)) if self.p.stoploss > 0 else None
            tp = round(price - takeprofit, int(self.p.price_digits)) if self.p.takeprofit > 0 else None
        return {'side': side, 'price': round(price, int(self.p.price_digits)), 'sl': sl, 'tp': tp, 'last_modify': curr_dt}

    def _current_pending_price(self, side):
        spread = self._spread()
        if side == 'buy':
            return round(float(self.data.close[0]) + spread + float(self.p.step) * self._unit(), int(self.p.price_digits))
        return round(float(self.data.close[0]) - spread - float(self.p.step) * self._unit(), int(self.p.price_digits))

    def _ensure_pending_orders(self):
        curr_dt = bt.num2date(self.data.datetime[0])
        if self.position_side != 'buy' and self.buy_stop_order is None:
            self.buy_stop_order = self._make_pending('buy', self._current_pending_price('buy'), curr_dt)
            self.log(f'place virtual buy_stop price={self.buy_stop_order["price"]:.2f}')
        if self.position_side != 'sell' and self.sell_stop_order is None:
            self.sell_stop_order = self._make_pending('sell', self._current_pending_price('sell'), curr_dt)
            self.log(f'place virtual sell_stop price={self.sell_stop_order["price"]:.2f}')

    def _update_pending_order(self, order_state):
        curr_dt = bt.num2date(self.data.datetime[0])
        if order_state is None:
            return None
        if self._elapsed_seconds(order_state['last_modify'], curr_dt) < float(self.p.time_modify_seconds):
            return order_state
        target_price = self._current_pending_price(order_state['side'])
        if abs(target_price - order_state['price']) < self._min_modify_delta():
            return order_state
        updated = self._make_pending(order_state['side'], target_price, curr_dt)
        self.log(f'modify virtual {order_state["side"]}_stop {order_state["price"]:.2f}->{updated["price"]:.2f}')
        return updated

    def _update_pending_orders(self):
        if self.position_side != 'buy':
            self.buy_stop_order = self._update_pending_order(self.buy_stop_order)
        else:
            self.buy_stop_order = None
        if self.position_side != 'sell':
            self.sell_stop_order = self._update_pending_order(self.sell_stop_order)
        else:
            self.sell_stop_order = None

    def _submit_open(self, side, reason):
        if self.order is not None:
            return False
        self.pending_action = {'type': 'open', 'side': side, 'reason': reason}
        self.order = self.buy(size=self.p.lot) if side == 'buy' else self.sell(size=self.p.lot)
        self.pending_trigger_count += 1
        self.log(f'trigger {side} stop -> market open reason={reason}')
        return True

    def _submit_close(self, reason, reopen_side=None):
        if self.order is not None or not self.position:
            return False
        self.pending_action = {'type': 'close', 'reason': reason, 'reopen_side': reopen_side}
        self.order = self.close()
        self.log(f'close position reason={reason}')
        return True

    def _check_pending_triggers(self):
        if self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        buy_hit = self.buy_stop_order is not None and high >= self.buy_stop_order['price']
        sell_hit = self.sell_stop_order is not None and low <= self.sell_stop_order['price']
        if not buy_hit and not sell_hit:
            return False
        chosen = None
        if buy_hit and not sell_hit:
            chosen = 'buy'
        elif sell_hit and not buy_hit:
            chosen = 'sell'
        else:
            open_price = float(self.data.open[0])
            buy_dist = abs(self.buy_stop_order['price'] - open_price)
            sell_dist = abs(open_price - self.sell_stop_order['price'])
            chosen = 'buy' if buy_dist <= sell_dist else 'sell'
        if self.position:
            if self.position_side == chosen:
                return False
            self.reopen_side = chosen
            return self._submit_close('reverse_pending_trigger', reopen_side=chosen)
        if chosen == 'buy':
            self.buy_stop_order = None
        else:
            self.sell_stop_order = None
        return self._submit_open(chosen, 'pending_stop_trigger')

    def _update_risk_from_fill(self, side, entry_price):
        unit = self._unit()
        if side == 'buy':
            self.stop_price = round(entry_price - float(self.p.stoploss) * unit, int(self.p.price_digits)) if self.p.stoploss > 0 else None
            self.take_profit_price = round(entry_price + float(self.p.takeprofit) * unit, int(self.p.price_digits)) if self.p.takeprofit > 0 else None
        else:
            self.stop_price = round(entry_price + float(self.p.stoploss) * unit, int(self.p.price_digits)) if self.p.stoploss > 0 else None
            self.take_profit_price = round(entry_price - float(self.p.takeprofit) * unit, int(self.p.price_digits)) if self.p.takeprofit > 0 else None

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        bid = float(self.data.close[0])
        ask = float(self.data.close[0])
        entry = float(self.position.price)
        unit = self._unit()

        if self.position_side == 'buy':
            if self.stop_price is not None and low <= self.stop_price:
                return self._submit_close('stop_loss')
            if self.take_profit_price is not None and high >= self.take_profit_price:
                return self._submit_close('take_profit')
            if self.p.no_loss > 0:
                be_price = round(entry + float(self.p.min_profit_no_loss) * unit, int(self.p.price_digits))
                if bid - entry >= float(self.p.no_loss) * unit and (self.stop_price is None or be_price > self.stop_price):
                    self.stop_price = be_price
            if self.p.trailing_stop > 0 and bid - entry >= float(self.p.trailing_start) * unit:
                trail = round(bid - float(self.p.trailing_stop) * unit, int(self.p.price_digits))
                step_limit = (self.stop_price or (entry - 999999)) + float(self.p.step_trail) * unit
                if trail >= entry and trail > step_limit:
                    self.stop_price = trail
        else:
            if self.stop_price is not None and high >= self.stop_price:
                return self._submit_close('stop_loss')
            if self.take_profit_price is not None and low <= self.take_profit_price:
                return self._submit_close('take_profit')
            if self.p.no_loss > 0:
                be_price = round(entry - float(self.p.min_profit_no_loss) * unit, int(self.p.price_digits))
                if entry - ask >= float(self.p.no_loss) * unit and (self.stop_price is None or be_price < self.stop_price):
                    self.stop_price = be_price
            if self.p.trailing_stop > 0 and entry - ask >= float(self.p.trailing_start) * unit:
                trail = round(ask + float(self.p.trailing_stop) * unit, int(self.p.price_digits))
                step_limit = (self.stop_price or (entry + 999999)) - float(self.p.step_trail) * unit
                if trail <= entry and trail < step_limit:
                    self.stop_price = trail
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if self._manage_position():
            return
        self._ensure_pending_orders()
        self._update_pending_orders()
        self._check_pending_triggers()

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        action = self.pending_action if self.order is not None and order.ref == self.order.ref else None
        reopen_side = None
        if order.status == bt.Order.Completed and action is not None:
            self.completed_order_count += 1
            if action['type'] == 'open':
                self.position_side = action['side']
                self._update_risk_from_fill(action['side'], float(order.executed.price))
                if action['side'] == 'buy':
                    self.buy_count += 1
                    self.buy_stop_order = None
                else:
                    self.sell_count += 1
                    self.sell_stop_order = None
                self.log(f'{action["side"]} filled price={order.executed.price:.2f} sl={self.stop_price} tp={self.take_profit_price}')
            elif action['type'] == 'close':
                reopen_side = action.get('reopen_side')
                self.position_side = None
                self.stop_price = None
                self.take_profit_price = None
                self.log(f'position closed reason={action["reason"]}')
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
            self.log(f'order failed status={order.getstatusname()}')
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None
            self.pending_action = None
            if reopen_side is not None:
                self._submit_open(reopen_side, 'reopen_after_close')

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
