from __future__ import absolute_import, division, print_function, unicode_literals

import io

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


class MacdWaterlineCrossExpectatorStrategy(bt.Strategy):
    params = dict(
        fast_ema_period=12,
        slow_ema_period=26,
        signal_period=9,
        stop_loss=300,
        size=0.1,
        risk_benefit_ratio=3,
        point=0.01,
    )

    def __init__(self):
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.fast_ema_period,
            period_me2=self.p.slow_ema_period,
            period_signal=self.p.signal_period,
        )
        self.order = None
        self.stop_price = None
        self.take_price = None
        self.flag = 'buy'
        self.pending_direction = None

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

        self.addminperiod(max(self.p.slow_ema_period, self.p.signal_period) + 5)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

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

    def _submit_entry(self, direction):
        take_profit = int(float(self.p.stop_loss) * float(self.p.risk_benefit_ratio))
        point = float(self.p.point)
        size = max(float(self.p.size), 0.01)
        ask = float(self.data.close[0])
        bid = float(self.data.close[0])

        if direction < 0:
            self.stop_price = ask + float(self.p.stop_loss) * point
            self.take_price = bid - take_profit * point
            self.log(f'sell signal={float(self.macd.signal[0]):.6f} size={size:.2f}')
            self.order = self.sell(size=size)
            self.flag = 'buy'
            return

        self.stop_price = bid - float(self.p.stop_loss) * point
        self.take_price = ask + take_profit * point
        self.log(f'buy signal={float(self.macd.signal[0]):.6f} size={size:.2f}')
        self.order = self.buy(size=size)
        self.flag = 'sell'

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if self._check_exit_levels():
            return

        if not self.position and self.pending_direction is not None:
            pending_direction = int(self.pending_direction)
            self.pending_direction = None
            self._submit_entry(pending_direction)
            return

        signal_now = float(self.macd.signal[0])
        signal_prev = float(self.macd.signal[-1])

        if signal_now < 0 and signal_prev > 0 and self.flag == 'sell':
            self.signal_count += 1
            if self.position.size > 0:
                self.pending_direction = -1
                self.order = self.close()
                return
            self._submit_entry(-1)
            return

        if signal_now > 0 and signal_prev < 0 and self.flag == 'buy':
            self.signal_count += 1
            if self.position.size < 0:
                self.pending_direction = 1
                self.order = self.close()
                return
            self._submit_entry(1)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
        self.order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.stop_price = None
        self.take_price = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
