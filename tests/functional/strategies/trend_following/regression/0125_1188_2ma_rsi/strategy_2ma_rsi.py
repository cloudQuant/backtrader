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


class TwoMaRsiStrategy(bt.Strategy):
    """
    Two MA + RSI strategy.
    Buy: fast MA crosses above slow MA AND RSI < oversold level.
    Sell: fast MA crosses below slow MA AND RSI > overbought level.
    Exit: opposite MA cross or RSI reversal.
    """
    params = dict(
        fast_period=10,
        slow_period=25,
        rsi_period=14,
        rsi_overbought=70,
        rsi_oversold=30,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.ma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
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
        warmup = max(self.p.fast_period, self.p.slow_period, self.p.rsi_period) + 5
        if len(self.data) < warmup:
            return

        mf0 = float(self.ma_fast[0])
        ms0 = float(self.ma_slow[0])
        mf1 = float(self.ma_fast[-1])
        ms1 = float(self.ma_slow[-1])
        rsi0 = float(self.rsi[0])

        bull_cross = mf1 <= ms1 and mf0 > ms0
        bear_cross = mf1 >= ms1 and mf0 < ms0
        ma_bull = mf0 > ms0
        ma_bear = mf0 < ms0

        if self.position:
            if self.position.size > 0:
                if bear_cross or rsi0 > self.p.rsi_overbought:
                    self.log(f'close long maf={mf0:.2f} mas={ms0:.2f} rsi={rsi0:.1f}')
                    self.close()
                    if bear_cross and rsi0 > self.p.rsi_overbought:
                        self.sell(size=self.p.lot)
                    return
            elif self.position.size < 0:
                if bull_cross or rsi0 < self.p.rsi_oversold:
                    self.log(f'close short maf={mf0:.2f} mas={ms0:.2f} rsi={rsi0:.1f}')
                    self.close()
                    if bull_cross and rsi0 < self.p.rsi_oversold:
                        self.buy(size=self.p.lot)
                    return
        else:
            if bull_cross and rsi0 < self.p.rsi_oversold:
                self.log(f'buy maf={mf0:.2f} mas={ms0:.2f} rsi={rsi0:.1f}')
                self.buy(size=self.p.lot)
                return
            if bear_cross and rsi0 > self.p.rsi_overbought:
                self.log(f'sell maf={mf0:.2f} mas={ms0:.2f} rsi={rsi0:.1f}')
                self.sell(size=self.p.lot)
                return
            if ma_bull and rsi0 < self.p.rsi_oversold:
                self.log(f'buy pullback maf={mf0:.2f} mas={ms0:.2f} rsi={rsi0:.1f}')
                self.buy(size=self.p.lot)
                return
            if ma_bear and rsi0 > self.p.rsi_overbought:
                self.log(f'sell pullback maf={mf0:.2f} mas={ms0:.2f} rsi={rsi0:.1f}')
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
