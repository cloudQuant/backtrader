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


class BillyTradingSystemStrategy(bt.Strategy):
    params = dict(
        lots=0.01,
        stop_loss=0,
        take_profit=32,
        max_positions=6,
        point=0.01,
        price_digits=2,
        timeframe_current_minutes=15,
        timeframe1_minutes=5,
        timeframe2_minutes=6,
    )

    def __init__(self):
        self.source = self.datas[0]
        self.current_tf = self.datas[1]
        self.sto_tf_1 = self.datas[2]
        self.sto_tf_2 = self.datas[3]
        self.sto_1 = bt.ind.Stochastic(self.sto_tf_1, period=5, period_dfast=3, period_dslow=3)
        self.sto_2 = bt.ind.Stochastic(self.sto_tf_2, period=5, period_dfast=3, period_dslow=3)
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.last_signal_dt = None
        self.open_orders = {}
        self.active_tranches = []
        self.sequence = 0

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
        order = self.close(data=self.source, size=total_size)
        self.open_orders[order.ref] = {'kind': 'exit', 'ids': list(tranche_ids)}

    def _manage_exits(self):
        if not self.active_tranches or self.open_orders:
            return
        high = float(self.source.high[0])
        low = float(self.source.low[0])
        hit_ids = []
        for tranche in self.active_tranches:
            if tranche['take_profit'] is not None and high >= float(tranche['take_profit']):
                hit_ids.append(tranche['id'])
            elif tranche['stop_loss'] is not None and low <= float(tranche['stop_loss']):
                hit_ids.append(tranche['id'])
        self._submit_close(hit_ids)

    def _pattern(self):
        if len(self.current_tf) < 5:
            return False
        high_1 = float(self.current_tf.high[-1])
        high_2 = float(self.current_tf.high[-2])
        high_3 = float(self.current_tf.high[-3])
        high_4 = float(self.current_tf.high[-4])
        open_1 = float(self.current_tf.open[-1])
        open_2 = float(self.current_tf.open[-2])
        open_3 = float(self.current_tf.open[-3])
        open_4 = float(self.current_tf.open[-4])
        return high_1 < high_2 < high_3 < high_4 and open_1 < open_2 < open_3 < open_4

    def _stochastic_ok(self):
        if len(self.sto_tf_1) < 3 or len(self.sto_tf_2) < 3:
            return False
        return float(self.sto_1.percK[-1]) > float(self.sto_1.percD[-1]) and float(self.sto_1.percK[0]) > float(self.sto_1.percD[0]) and float(self.sto_2.percK[-1]) > float(self.sto_2.percD[-1]) and float(self.sto_2.percK[0]) > float(self.sto_2.percD[0])

    def next(self):
        self.bar_num += 1
        self._manage_exits()
        if self.open_orders:
            return
        if len(self.current_tf) < 5 or len(self.sto_tf_1) < 3 or len(self.sto_tf_2) < 3:
            return
        current_dt = self.current_tf.datetime.datetime(0)
        if self.last_signal_dt == current_dt:
            return
        self.last_signal_dt = current_dt
        if len(self.active_tranches) >= int(self.p.max_positions):
            return
        if not self._pattern():
            return
        if not self._stochastic_ok():
            return
        price = float(self.source.close[0])
        sl_dist = float(self.p.stop_loss) * self._point()
        tp_dist = float(self.p.take_profit) * self._point()
        order = self.buy(data=self.source, size=float(self.p.lots))
        self.open_orders[order.ref] = {
            'kind': 'entry',
            'tranche': {
                'id': self.sequence,
                'size': float(self.p.lots),
                'stop_loss': self._round(price - sl_dist) if sl_dist > 0 else None,
                'take_profit': self._round(price + tp_dist) if tp_dist > 0 else None,
            },
        }
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
                self.buy_count += 1
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
