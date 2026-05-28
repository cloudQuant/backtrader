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


class SuperTrendIndicator(bt.Indicator):
    """
    SuperTrend indicator based on ATR.
    upper_band = (high + low) / 2 + multiplier * ATR
    lower_band = (high + low) / 2 - multiplier * ATR
    Trend flips when price crosses the band.
    """
    lines = ('supertrend', 'direction',)
    params = (
        ('atr_period', 10),
        ('multiplier', 3.0),
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self._upper = None
        self._lower = None
        self._dir = 1  # 1=up (bullish), -1=down (bearish)

    def next(self):
        hl2 = (float(self.data.high[0]) + float(self.data.low[0])) / 2.0
        atr_val = float(self.atr[0])
        up = hl2 + self.p.multiplier * atr_val
        dn = hl2 - self.p.multiplier * atr_val

        if self._upper is not None:
            up = min(up, self._upper) if float(self.data.close[-1]) > self._upper else up
            dn = max(dn, self._lower) if float(self.data.close[-1]) < self._lower else dn

        close = float(self.data.close[0])
        if self._dir == 1:
            if close < dn:
                self._dir = -1
        else:
            if close > up:
                self._dir = 1

        self._upper = up
        self._lower = dn
        self.lines.supertrend[0] = dn if self._dir == 1 else up
        self.lines.direction[0] = float(self._dir)


class SuperTrendStrategy(bt.Strategy):
    """
    SuperTrend strategy: buy when trend flips bullish, sell when trend flips bearish.
    """
    params = dict(
        atr_period=10,
        multiplier=3.0,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.st = SuperTrendIndicator(
            self.data, atr_period=self.p.atr_period, multiplier=self.p.multiplier)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._prev_dir = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.p.atr_period + 5:
            return

        d = float(self.st.direction[0])
        if self._prev_dir is None:
            self._prev_dir = d
            return

        flipped_bull = self._prev_dir < 0 and d > 0
        flipped_bear = self._prev_dir > 0 and d < 0
        self._prev_dir = d

        if self.position:
            if self.position.size > 0 and flipped_bear:
                self.log(f'close long & sell st={float(self.st.supertrend[0]):.2f}')
                self.close()
                self.sell(size=self.p.lot)
                return
            elif self.position.size < 0 and flipped_bull:
                self.log(f'close short & buy st={float(self.st.supertrend[0]):.2f}')
                self.close()
                self.buy(size=self.p.lot)
                return
        else:
            if flipped_bull:
                self.log(f'buy st={float(self.st.supertrend[0]):.2f}')
                self.buy(size=self.p.lot)
                return
            if flipped_bear:
                self.log(f'sell st={float(self.st.supertrend[0]):.2f}')
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
