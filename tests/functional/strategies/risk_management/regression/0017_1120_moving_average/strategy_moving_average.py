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


class MovingAverageStrategy(bt.Strategy):
    params = dict(
        maximum_risk=0.02,
        decrease_factor=3.0,
        moving_period=12,
        moving_shift=6,
        margin_per_lot=250.0,
        min_volume=0.01,
        max_volume=100.0,
        volume_step=0.01,
    )

    def __init__(self):
        self.ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.moving_period)
        self.order = None
        self.closed_trade_pnls = []

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.addminperiod(self.p.moving_period + self.p.moving_shift + 2)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalized_volume(self, volume):
        step = max(float(self.p.volume_step), 1e-9)
        min_vol = float(self.p.min_volume)
        max_vol = float(self.p.max_volume)
        volume = max(min_vol, min(max_vol, volume))
        volume = step * round(volume / step)
        volume = max(min_vol, min(max_vol, volume))
        return float(f'{volume:.4f}')

    def trade_size_optimized(self):
        price = float(self.data.close[0])
        if price <= 0 or float(self.p.margin_per_lot) <= 0:
            return self._normalized_volume(float(self.p.min_volume))
        lot = self.broker.getcash() * float(self.p.maximum_risk) / float(self.p.margin_per_lot)
        if float(self.p.decrease_factor) > 0:
            losses = 0
            for pnl in reversed(self.closed_trade_pnls):
                if pnl > 0:
                    break
                if pnl < 0:
                    losses += 1
            if losses > 1:
                lot = lot - lot * losses / float(self.p.decrease_factor)
        return self._normalized_volume(lot)

    def crossed_down(self):
        return float(self.data.open[0]) > float(self.ma[0]) and float(self.data.close[0]) < float(self.ma[0])

    def crossed_up(self):
        return float(self.data.open[0]) < float(self.ma[0]) and float(self.data.close[0]) > float(self.ma[0])

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if len(self) <= max(self.p.moving_period, self.p.moving_shift) + 1:
            return

        if self.position:
            close_signal = False
            if self.position.size > 0 and self.crossed_down():
                close_signal = True
            if self.position.size < 0 and self.crossed_up():
                close_signal = True
            if close_signal:
                self.log('close signal')
                self.order = self.close()
            return

        signal = None
        if self.crossed_down():
            signal = 'sell'
        elif self.crossed_up():
            signal = 'buy'

        if signal is None:
            return

        size = self.trade_size_optimized()
        self.signal_count += 1
        if signal == 'buy':
            self.buy_count += 1
            self.log(f'buy signal size={size:.2f}')
            self.order = self.buy(size=size)
        else:
            self.sell_count += 1
            self.log(f'sell signal size={size:.2f}')
            self.order = self.sell(size=size)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        pnl = float(trade.pnlcomm)
        self.closed_trade_pnls.append(pnl)
        self.trade_count += 1
        if pnl >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={pnl:.2f}')
