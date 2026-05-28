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


class BullsBearsStrategy(bt.Strategy):
    """
    Bulls/Bears Power trend indicator.
    Computes bull_power = high - EMA, bear_power = low - EMA.
    Combined = bull_power + bear_power.
    Buy: combined flips from negative to positive (color change)
    Sell: combined flips from positive to negative
    """
    params = dict(
        ema_period=13,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.ema_period)
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

    def _combined(self, idx):
        bull = float(self.data.high[idx]) - float(self.ema[idx])
        bear = float(self.data.low[idx]) - float(self.ema[idx])
        return bull + bear

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.p.ema_period + 5:
            return

        c1 = self._combined(-1)
        c2 = self._combined(-2)

        buy_signal = c2 < 0 and c1 > 0
        sell_signal = c2 > 0 and c1 < 0

        if self.position:
            if self.position.size > 0 and sell_signal:
                self.log(f'close long & sell combined={c1:.2f}')
                self.close()
                self.sell(size=self.p.lot)
                return
            elif self.position.size < 0 and buy_signal:
                self.log(f'close short & buy combined={c1:.2f}')
                self.close()
                self.buy(size=self.p.lot)
                return
        else:
            if buy_signal:
                self.log(f'buy combined={c1:.2f}')
                self.buy(size=self.p.lot)
                return
            if sell_signal:
                self.log(f'sell combined={c1:.2f}')
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
