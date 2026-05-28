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


class WprBbAtrStrategy(bt.Strategy):
    """
    WPR + Bollinger Bands + ATR strategy.
    Buy: WPR exits oversold (crosses above -80) AND open < BB middle line.
    Sell: WPR exits overbought (crosses below -20) AND open > BB middle line.
    SL = BB width / 2, TP = ATR value (both scaled by multipliers).
    """
    params = dict(
        wpr_period=14,
        wpr_overbought=-20,
        wpr_oversold=-80,
        bb_period=20,
        bb_dev=2.0,
        atr_period=14,
        sl_mult=1.0,
        tp_mult=1.0,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.wpr = bt.indicators.WilliamsR(
            self.data, period=self.p.wpr_period)
        self.bb = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bb_period, devfactor=self.p.bb_dev)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
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
        warmup = max(self.p.wpr_period, self.p.bb_period, self.p.atr_period) + 5
        if len(self.data) < warmup:
            return

        wpr0 = float(self.wpr[0])
        wpr1 = float(self.wpr[-1])
        bb_mid = float(self.bb.mid[0])
        bb_top = float(self.bb.top[0])
        bb_bot = float(self.bb.bot[0])
        atr_val = float(self.atr[0])
        o = float(self.data.open[0])

        wpr_exit_oversold = wpr1 <= self.p.wpr_oversold and wpr0 > self.p.wpr_oversold
        wpr_exit_overbought = wpr1 >= self.p.wpr_overbought and wpr0 < self.p.wpr_overbought

        if self.position:
            if self.position.size > 0:
                if wpr_exit_overbought:
                    self.log(f'close long wpr={wpr0:.1f}')
                    self.close()
                    if o > bb_mid:
                        self.sell(size=self.p.lot)
                    return
            elif self.position.size < 0:
                if wpr_exit_oversold:
                    self.log(f'close short wpr={wpr0:.1f}')
                    self.close()
                    if o < bb_mid:
                        self.buy(size=self.p.lot)
                    return
        else:
            if wpr_exit_oversold and o < bb_mid:
                self.log(f'buy wpr={wpr0:.1f} bb_mid={bb_mid:.2f} atr={atr_val:.2f}')
                self.buy(size=self.p.lot)
                return
            if wpr_exit_overbought and o > bb_mid:
                self.log(f'sell wpr={wpr0:.1f} bb_mid={bb_mid:.2f} atr={atr_val:.2f}')
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
