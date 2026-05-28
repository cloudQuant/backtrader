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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
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


class DailyBreakpointStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        stop_loss=0,
        take_profit=30,
        close_by_signal=True,
        break_point=20,
        last_bar_size_min=5,
        last_bar_size_max=50,
        require_break_inside_body=True,
        trailing_stop=2,
        trailing_step=2,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.data_h1 = self.datas[1]
        self.data_d1 = self.datas[2]
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.open_orders = {}
        self.active_tranches = []
        self.sequence = 0
        self.last_signal_dt = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _submit_close(self, tranche_ids):
        if self.open_orders or not tranche_ids:
            return
        tranches = [t for t in self.active_tranches if t['id'] in tranche_ids]
        if not tranches:
            return
        total_size = sum(float(t['size']) for t in tranches)
        order = self.close(data=self.data, size=total_size)
        self.open_orders[order.ref] = {'kind': 'exit', 'ids': list(tranche_ids)}

    def _close_direction(self, direction):
        ids = [t['id'] for t in self.active_tranches if t['direction'] == direction]
        self._submit_close(ids)

    def _trailing(self):
        if not self.active_tranches:
            return
        current = float(self.data.close[0])
        trail_stop = float(self.p.trailing_stop) * self._point()
        trail_step = float(self.p.trailing_step) * self._point()
        if trail_stop <= 0:
            return
        for tranche in self.active_tranches:
            if tranche['direction'] == 'buy':
                if current - float(tranche['entry_price']) > trail_stop + trail_step:
                    threshold = current - (trail_stop + trail_step)
                    if tranche['stop_loss'] is None or float(tranche['stop_loss']) < threshold:
                        tranche['stop_loss'] = self._round(current - trail_stop)
            else:
                if float(tranche['entry_price']) - current > trail_stop + trail_step:
                    threshold = current + (trail_stop + trail_step)
                    if tranche['stop_loss'] is None or float(tranche['stop_loss']) > threshold:
                        tranche['stop_loss'] = self._round(current + trail_stop)

    def _manage_exits(self):
        if not self.active_tranches or self.open_orders:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        hit_ids = []
        for tranche in self.active_tranches:
            if tranche['direction'] == 'buy':
                if tranche['take_profit'] is not None and high >= float(tranche['take_profit']):
                    hit_ids.append(tranche['id'])
                elif tranche['stop_loss'] is not None and low <= float(tranche['stop_loss']):
                    hit_ids.append(tranche['id'])
            else:
                if tranche['take_profit'] is not None and low <= float(tranche['take_profit']):
                    hit_ids.append(tranche['id'])
                elif tranche['stop_loss'] is not None and high >= float(tranche['stop_loss']):
                    hit_ids.append(tranche['id'])
        self._submit_close(hit_ids)

    def next(self):
        self.bar_num += 1
        self._trailing()
        self._manage_exits()
        if self.open_orders:
            return
        if len(self.data_h1) < 2 or len(self.data_d1) < 2:
            return
        signal_dt = self.data_h1.datetime.datetime(0)
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        day_open = float(self.data_d1.open[-1])
        last_open = float(self.data_h1.open[-1])
        last_close = float(self.data_h1.close[-1])
        current_price = float(self.data.close[0])
        is_bull_bar = last_close > last_open
        break_buy = day_open + float(self.p.break_point) * self._point()
        break_sell = day_open - float(self.p.break_point) * self._point()
        sl_dist = float(self.p.stop_loss) * self._point()
        tp_dist = float(self.p.take_profit) * self._point()
        body = abs(last_close - last_open)
        body_ok = float(self.p.last_bar_size_min) * self._point() <= body <= float(self.p.last_bar_size_max) * self._point()
        buy_break_in_body = break_buy >= min(last_open, last_close) and break_buy <= max(last_open, last_close)
        sell_break_in_body = break_sell <= max(last_open, last_close) and break_sell >= min(last_open, last_close)
        require_inside = bool(self.p.require_break_inside_body)
        if is_bull_bar and current_price - day_open >= float(self.p.break_point) * self._point() and body_ok and (buy_break_in_body or not require_inside):
            if bool(self.p.close_by_signal):
                self._close_direction('buy')
                if self.open_orders:
                    return
                order = self.sell(size=float(self.p.lots))
                direction = 'sell'
            else:
                order = self.buy(size=float(self.p.lots))
                direction = 'buy'
            self.open_orders[order.ref] = {'kind': 'entry', 'tranche': {'id': self.sequence, 'direction': direction, 'size': float(self.p.lots), 'stop_loss': self._round(current_price + sl_dist) if direction == 'sell' and sl_dist > 0 else self._round(current_price - sl_dist) if direction == 'buy' and sl_dist > 0 else None, 'take_profit': self._round(current_price - tp_dist) if direction == 'sell' and tp_dist > 0 else self._round(current_price + tp_dist) if direction == 'buy' and tp_dist > 0 else None}}
            self.sequence += 1
            self.signal_count += 1
            return
        if (not is_bull_bar) and day_open - current_price >= float(self.p.break_point) * self._point() and body_ok and (sell_break_in_body or not require_inside):
            if bool(self.p.close_by_signal):
                self._close_direction('sell')
                if self.open_orders:
                    return
                order = self.buy(size=float(self.p.lots))
                direction = 'buy'
            else:
                order = self.sell(size=float(self.p.lots))
                direction = 'sell'
            self.open_orders[order.ref] = {'kind': 'entry', 'tranche': {'id': self.sequence, 'direction': direction, 'size': float(self.p.lots), 'stop_loss': self._round(current_price - sl_dist) if direction == 'buy' and sl_dist > 0 else self._round(current_price + sl_dist) if direction == 'sell' and sl_dist > 0 else None, 'take_profit': self._round(current_price + tp_dist) if direction == 'buy' and tp_dist > 0 else self._round(current_price - tp_dist) if direction == 'sell' and tp_dist > 0 else None}}
            self.sequence += 1
            self.signal_count += 1

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        meta = self.open_orders.pop(order.ref, None)
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if meta and meta.get('kind') == 'entry':
                tranche = meta['tranche']
                tranche['size'] = abs(float(order.executed.size))
                tranche['entry_price'] = float(order.executed.price)
                self.active_tranches.append(tranche)
                if tranche['direction'] == 'buy':
                    self.buy_count += 1
                else:
                    self.sell_count += 1
            elif meta and meta.get('kind') == 'exit':
                exit_ids = set(meta.get('ids', []))
                self.active_tranches = [t for t in self.active_tranches if t['id'] not in exit_ids]
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
