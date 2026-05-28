from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import backtrader.feeds as btfeeds
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


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class RockTraderNeuroStrategy(bt.Strategy):
    params = dict(
        stop_loss=30,
        take_profit=100,
        lot=1.0,
        point=0.01,
        bb_period=20,
        bb_devfactor=2.0,
        w0=0.8,
        w1=0.4,
        w2=-0.9,
        w3=0.0,
        w4=0.7,
        w5=-0.2,
        w6=0.9,
        w7=0.7,
        w8=-1.0,
        w9=0.3,
        w10=0.5,
        w11=0.5,
        w12=0.0,
        w13=1.0,
    )

    def __init__(self):
        self.bb = bt.indicators.BollingerBands(
            self.data.close,
            period=self.p.bb_period,
            devfactor=self.p.bb_devfactor,
        )
        self.order = None
        self.pending_side = None
        self.stop_price = None
        self.take_price = None
        self.out_value = None
        self.weights = [
            self.p.w0, self.p.w1, self.p.w2, self.p.w3, self.p.w4, self.p.w5, self.p.w6,
            self.p.w7, self.p.w8, self.p.w9, self.p.w10, self.p.w11, self.p.w12, self.p.w13,
        ]

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.addminperiod(60)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _band_arrays(self):
        upper = [float(self.bb.top[-i]) for i in range(7)]
        lower = [float(self.bb.bot[-i]) for i in range(7)]
        base = [float(self.bb.mid[-i]) for i in range(7)]
        return upper, lower, base

    def _compute_neuron_output(self):
        upper, lower, base = self._band_arrays()
        x_min = min(min(lower), min(upper))
        x_minn = min(base)
        x_max = max(max(lower), max(upper))
        x_maxx = max(base)
        denom = (x_maxx + x_max) - (x_min + x_minn)
        if denom == 0:
            return 0.0
        inputs = [0.0] * 14
        d1 = -1.0
        d2 = 1.0
        for i in range(7):
            inputs[i * 2] = ((((upper[i] - lower[i]) / base[i]) - (x_min + x_minn) * (d2 - d1)) / denom) + d1
        net = 0.0
        for value, weight in zip(inputs, self.weights):
            net += value * weight
        net *= 2.0
        return math.tanh(net)

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and high >= self.take_price:
                self.log(f'close long by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and low <= self.take_price:
                self.log(f'close short by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if self.position and self._check_exit_levels():
            return

        out = self._compute_neuron_output()
        self.out_value = out
        target = 0.0
        side = None
        if out < 0:
            target = float(self.p.lot)
            side = 'long'
        elif out > 0:
            target = -float(self.p.lot)
            side = 'short'
        else:
            return

        if float(self.position.size) == target:
            return

        self.signal_count += 1
        if target > 0:
            self.buy_count += 1
        else:
            self.sell_count += 1
        self.pending_side = side
        self.log(f'signal side={side} out={out:.6f}')
        self.order = self.order_target_size(target=target)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed and self.pending_side is not None:
            entry_price = float(order.executed.price)
            if self.pending_side == 'long':
                self.stop_price = entry_price - float(self.p.stop_loss) * float(self.p.point)
                self.take_price = entry_price + float(self.p.take_profit) * float(self.p.point)
            else:
                self.stop_price = entry_price + float(self.p.stop_loss) * float(self.p.point)
                self.take_price = entry_price - float(self.p.take_profit) * float(self.p.point)
            self.log(f'entry filled side={self.pending_side} price={entry_price:.5f}')
            self.pending_side = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
            self.pending_side = None
        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        pnl = float(trade.pnlcomm)
        self.trade_count += 1
        if pnl >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.stop_price = None
        self.take_price = None
        self.log(f'trade closed pnl={pnl:.2f}')
