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


class ElderImpulseStrategy(bt.Strategy):
    """
    Elder Impulse System:
    - Green bar (bullish): EMA rising AND MACD histogram rising → buy
    - Red bar (bearish): EMA falling AND MACD histogram falling → sell
    - Blue bar (neutral): mixed signals → no new entry, close existing
    """
    params = dict(
        ema_period=13,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.ema_period)
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.macd_fast,
            period_me2=self.p.macd_slow,
            period_signal=self.p.macd_signal)
        self.macd_histo = self.macd.macd - self.macd.signal
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

    def _impulse_color(self):
        ema0 = float(self.ema[0])
        ema1 = float(self.ema[-1])
        histo0 = float(self.macd_histo[0])
        histo1 = float(self.macd_histo[-1])

        ema_rising = ema0 > ema1
        ema_falling = ema0 < ema1
        histo_rising = histo0 > histo1
        histo_falling = histo0 < histo1

        if ema_rising and histo_rising:
            return 'green'
        elif ema_falling and histo_falling:
            return 'red'
        else:
            return 'blue'

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.ema_period, self.p.macd_slow + self.p.macd_signal) + 5
        if len(self.data) < warmup:
            return

        color = self._impulse_color()

        if self.position:
            if self.position.size > 0:
                if color == 'red':
                    self.log(f'close long & sell impulse={color}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
                elif color == 'blue':
                    self.log(f'close long impulse={color}')
                    self.close()
                    return
            elif self.position.size < 0:
                if color == 'green':
                    self.log(f'close short & buy impulse={color}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
                elif color == 'blue':
                    self.log(f'close short impulse={color}')
                    self.close()
                    return
        else:
            if color == 'green':
                self.log(f'buy impulse={color}')
                self.buy(size=self.p.lot)
                return
            if color == 'red':
                self.log(f'sell impulse={color}')
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
