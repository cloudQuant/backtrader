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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
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


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class TwoEMACrossStrategy(bt.Strategy):
    """
    Two EMA crossover.
    Buy: Fast EMA crosses above Slow EMA
    Sell: Fast EMA crosses below Slow EMA
    """
    params = dict(
        fast_period=12,
        slow_period=26,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.fast_ema = bt.indicators.EMA(self.data.close, period=self.p.fast_period)
        self.slow_ema = bt.indicators.EMA(self.data.close, period=self.p.slow_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.p.slow_period + 3:
            return

        diff1 = float(self.fast_ema[-1]) - float(self.slow_ema[-1])
        diff2 = float(self.fast_ema[-2]) - float(self.slow_ema[-2])

        buy_sig = diff2 < 0 and diff1 > 0
        sell_sig = diff2 > 0 and diff1 < 0

        if self.position:
            if self.position.size > 0 and sell_sig:
                self.log(f'close long & sell price={self.data.close[0]:.2f}')
                self.close()
                self.sell(size=self.p.lot)
                return
            if self.position.size < 0 and buy_sig:
                self.log(f'close short & buy price={self.data.close[0]:.2f}')
                self.close()
                self.buy(size=self.p.lot)
                return
        else:
            if buy_sig:
                self.log(f'buy signal price={self.data.close[0]:.2f}')
                self.buy(size=self.p.lot)
                return
            if sell_sig:
                self.log(f'sell signal price={self.data.close[0]:.2f}')
                self.sell(size=self.p.lot)
                return

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
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
