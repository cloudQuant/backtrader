from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

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
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
        '<SPREAD>': 'spread',
    })
    keep_cols = ['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']
    if 'spread' in df.columns:
        keep_cols.append('spread')
    df = df[keep_cols]
    if 'spread' not in df.columns:
        df['spread'] = 0
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('spread', 6),
    )


class EAMovingAverageStrategy(bt.Strategy):
    params = dict(
        maximum_risk=0.02,
        decrease_factor=3,
        moving_period_buy_open=30,
        moving_shift_buy_open=3,
        moving_period_buy_close=14,
        moving_shift_buy_close=3,
        moving_period_sell_open=30,
        moving_shift_sell_open=0,
        moving_period_sell_close=20,
        moving_shift_sell_close=2,
        use_buy=True,
        use_sell=True,
        consider_price_last_out=True,
        lot=0.10,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.ma_buy_open = bt.indicators.ExponentialMovingAverage(self.data0.close, period=self.p.moving_period_buy_open)
        self.ma_buy_close = bt.indicators.ExponentialMovingAverage(self.data0.close, period=self.p.moving_period_buy_close)
        self.ma_sell_open = bt.indicators.ExponentialMovingAverage(self.data0.close, period=self.p.moving_period_sell_open)
        self.ma_sell_close = bt.indicators.ExponentialMovingAverage(self.data0.close, period=self.p.moving_period_sell_close)
        self.order = None
        self.pending_action = None
        self.last_bar_dt = None
        self.price_last_deal_out = 0.0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data0.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        dt = bt.num2date(self.data0.datetime[0])
        if self.last_bar_dt == dt:
            return
        self.last_bar_dt = dt
        if len(self.data0) < 100:
            return
        if self.order is not None:
            return
        if self.position:
            self._check_for_close()
        else:
            self._check_for_open()

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.pending_action == 'open_long' and order.isbuy() and self.position.size > 0:
                self.buy_count += 1
            elif self.pending_action == 'open_short' and order.issell() and self.position.size < 0:
                self.sell_count += 1
            elif self.pending_action == 'close' and not self.position:
                self.price_last_deal_out = float(order.executed.price)
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            if order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
                self.log(f'ORDER FAILED status={order.getstatusname()}')
            self.order = None
            self.pending_action = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.price_last_deal_out = float(self.data0.close[0])
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f}')

    def _check_for_open(self):
        open_0 = float(self.data0.open[0])
        close_0 = float(self.data0.close[0])
        ask = float(self.data0.close[0])
        bid = float(self.data0.close[0])
        signal = None
        buy_open = self._shifted_value(self.ma_buy_open, int(self.p.moving_shift_buy_open))
        sell_open = self._shifted_value(self.ma_sell_open, int(self.p.moving_shift_sell_open))
        if self.p.use_buy and buy_open is not None:
            allowed = ((self.price_last_deal_out != 0.0 and self.price_last_deal_out >= ask) or self.price_last_deal_out == 0.0) if self.p.consider_price_last_out else True
            if allowed and open_0 < buy_open and close_0 > buy_open:
                signal = 'buy'
        if self.p.use_sell and sell_open is not None:
            allowed = ((self.price_last_deal_out != 0.0 and self.price_last_deal_out <= bid) or self.price_last_deal_out == 0.0) if self.p.consider_price_last_out else True
            if allowed and open_0 > sell_open and close_0 < sell_open:
                signal = 'sell'
        if signal == 'buy':
            self.pending_action = 'open_long'
            self.order = self.buy(size=float(self.p.lot))
            self.log(f'OPEN LONG ma_buy_open={buy_open:.5f} open={open_0:.5f} close={close_0:.5f}')
            return
        if signal == 'sell':
            self.pending_action = 'open_short'
            self.order = self.sell(size=float(self.p.lot))
            self.log(f'OPEN SHORT ma_sell_open={sell_open:.5f} open={open_0:.5f} close={close_0:.5f}')

    def _check_for_close(self):
        open_0 = float(self.data0.open[0])
        close_0 = float(self.data0.close[0])
        buy_close = self._shifted_value(self.ma_buy_close, int(self.p.moving_shift_buy_close))
        sell_close = self._shifted_value(self.ma_sell_close, int(self.p.moving_shift_sell_close))
        signal = False
        if self.position.size > 0 and buy_close is not None and open_0 > buy_close and close_0 < buy_close:
            signal = True
        if self.position.size < 0 and sell_close is not None and open_0 < sell_close and close_0 > sell_close:
            signal = True
        if signal:
            self.pending_action = 'close'
            self.order = self.close()
            self.log(f'CLOSE POSITION open={open_0:.5f} close={close_0:.5f}')

    @staticmethod
    def _finite(value):
        value = float(value)
        if not math.isfinite(value):
            return None
        return value

    def _shifted_value(self, line, shift):
        idx = -shift if shift else 0
        try:
            return self._finite(line[idx])
        except IndexError:
            return None
