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


class NCandlesV5Strategy(bt.Strategy):
    params = dict(
        n_candles=3,
        lot=0.01,
        take_profit=50,
        stop_loss=50,
        trailing_stop=10,
        trailing_step=4,
        max_positions=2,
        max_position_volume=2.0,
        use_trade_hours=True,
        start_hour=11,
        end_hour=18,
        point=0.01,
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
        self.open_orders = {}
        self.active_tranches = []
        self.sequence = 0
        self.last_bar_dt = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _is_trade_time(self):
        if not bool(self.p.use_trade_hours):
            return True
        dt = bt.num2date(self.data.datetime[0])
        return int(self.p.start_hour) <= dt.hour < int(self.p.end_hour)

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
                if current - float(tranche['entry_price']) > trail_stop:
                    candidate = current - trail_stop
                    if tranche['stop_loss'] is None:
                        tranche['stop_loss'] = self._round(float(tranche['entry_price']))
                    elif candidate - float(tranche['stop_loss']) > trail_step:
                        tranche['stop_loss'] = self._round(candidate)
            else:
                if float(tranche['entry_price']) - current > trail_stop:
                    candidate = current + trail_stop
                    if tranche['stop_loss'] is None:
                        tranche['stop_loss'] = self._round(float(tranche['entry_price']))
                    elif float(tranche['stop_loss']) - candidate > trail_step:
                        tranche['stop_loss'] = self._round(candidate)

    def _submit_close(self, tranche_ids):
        if self.open_orders or not tranche_ids:
            return
        tranches = [t for t in self.active_tranches if t['id'] in tranche_ids]
        if not tranches:
            return
        total_size = sum(float(t['size']) for t in tranches)
        order = self.close(size=total_size)
        self.open_orders[order.ref] = {'kind': 'exit', 'ids': list(tranche_ids)}

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

    def _counts(self):
        buy_count = sum(1 for t in self.active_tranches if t['direction'] == 'buy')
        sell_count = sum(1 for t in self.active_tranches if t['direction'] == 'sell')
        total_volume = sum(float(t['size']) for t in self.active_tranches)
        return buy_count, sell_count, total_volume

    def _pattern(self):
        n = int(self.p.n_candles)
        if len(self) < n + 2:
            return 0
        direction = 0
        for idx in range(1, n + 1):
            o = float(self.data.open[-idx])
            c = float(self.data.close[-idx])
            current_dir = 1 if o < c else -1 if o > c else 0
            if idx == 1:
                direction = current_dir
                if direction == 0:
                    return 0
            elif current_dir != direction:
                return 0
        return direction

    def next(self):
        self.bar_num += 1
        current_bar_dt = self.data.datetime.datetime(0)
        if self.last_bar_dt == current_bar_dt:
            return
        self.last_bar_dt = current_bar_dt
        self._trailing()
        self._manage_exits()
        if self.open_orders or not self._is_trade_time():
            return
        direction = self._pattern()
        if direction == 0:
            return
        buy_count, sell_count, total_volume = self._counts()
        if total_volume + float(self.p.lot) > float(self.p.max_position_volume):
            return
        price = float(self.data.close[0])
        sl_dist = float(self.p.stop_loss) * self._point()
        tp_dist = float(self.p.take_profit) * self._point()
        if direction == 1 and buy_count < int(self.p.max_positions):
            order = self.buy(size=float(self.p.lot))
            self.open_orders[order.ref] = {'kind': 'entry', 'tranche': {'id': self.sequence, 'direction': 'buy', 'size': float(self.p.lot), 'stop_loss': self._round(price - sl_dist) if sl_dist > 0 else None, 'take_profit': self._round(price + tp_dist) if tp_dist > 0 else None}}
            self.sequence += 1
            self.signal_count += 1
            return
        if direction == -1 and sell_count < int(self.p.max_positions):
            order = self.sell(size=float(self.p.lot))
            self.open_orders[order.ref] = {'kind': 'entry', 'tranche': {'id': self.sequence, 'direction': 'sell', 'size': float(self.p.lot), 'stop_loss': self._round(price + sl_dist) if sl_dist > 0 else None, 'take_profit': self._round(price - tp_dist) if tp_dist > 0 else None}}
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
