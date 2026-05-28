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


class PuriaMethodStrategy(bt.Strategy):
    """
    Puria Method: 3 Moving Averages + MACD confirmation.
    MA1 (red): LWMA 85, applied to Low
    MA2 (red): LWMA 75, applied to Low
    MA3 (blue): EMA 5, applied to Close
    MACD: fast=15, slow=26, signal=1
    Buy: blue MA crosses above both red MAs AND MACD > 0
    Sell: blue MA crosses below both red MAs AND MACD < 0
    """
    params = dict(
        lwma1_period=85,
        lwma2_period=75,
        ema_period=5,
        macd_fast=15,
        macd_slow=26,
        macd_signal=1,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.lwma1 = bt.indicators.WeightedMovingAverage(
            self.data.low, period=self.p.lwma1_period)
        self.lwma2 = bt.indicators.WeightedMovingAverage(
            self.data.low, period=self.p.lwma2_period)
        self.ema = bt.indicators.ExponentialMovingAverage(
            self.data.close, period=self.p.ema_period)
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.macd_fast,
            period_me2=self.p.macd_slow,
            period_signal=self.p.macd_signal)
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
        warmup = self.p.lwma1_period + 5
        if len(self.data) < warmup:
            return

        ema0 = float(self.ema[0])
        ema1 = float(self.ema[-1])
        lwma1_0 = float(self.lwma1[0])
        lwma2_0 = float(self.lwma2[0])
        lwma1_1 = float(self.lwma1[-1])
        lwma2_1 = float(self.lwma2[-1])
        macd_val = float(self.macd.macd[0])

        ema_above_now = ema0 > lwma1_0 and ema0 > lwma2_0
        ema_above_prev = ema1 > lwma1_1 and ema1 > lwma2_1
        ema_below_now = ema0 < lwma1_0 and ema0 < lwma2_0
        ema_below_prev = ema1 < lwma1_1 and ema1 < lwma2_1

        if ema_above_now and not ema_above_prev and macd_val > 0:
            if self.position.size < 0:
                self.close()
            if self.position.size <= 0:
                self.buy(size=self.p.lot)
        elif ema_below_now and not ema_below_prev and macd_val < 0:
            if self.position.size > 0:
                self.close()
            if self.position.size >= 0:
                self.sell(size=self.p.lot)

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0: self.buy_count += 1
            elif trade.size < 0: self.sell_count += 1
            self._position_was_open = True
            return
        if not trade.isclosed: return
        self.trade_count += 1
        if trade.pnlcomm >= 0: self.win_count += 1
        else: self.loss_count += 1
        self._position_was_open = False
