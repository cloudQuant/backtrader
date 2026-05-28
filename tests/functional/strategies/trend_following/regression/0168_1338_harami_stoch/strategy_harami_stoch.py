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


class HaramiStochStrategy(bt.Strategy):
    """
    Bullish/Bearish Harami + Stochastic confirmation.
    Buy: Bullish Harami + Stochastic %D < 30
    Sell: Bearish Harami + Stochastic %D > 70
    Exit: Stochastic %D crosses critical levels (20/80)
    """
    params = dict(
        stoch_k=14,
        stoch_d=3,
        stoch_slow=3,
        ma_period=5,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.stoch = bt.indicators.StochasticSlow(
            self.data, period=self.p.stoch_k, period_dfast=self.p.stoch_d,
            period_dslow=self.p.stoch_slow)
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.ma_period)
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

    def _avg_body(self):
        total = 0.0
        for i in range(-5, 0):
            total += abs(float(self.data.close[i]) - float(self.data.open[i]))
        return total / 5.0

    def _bullish_harami(self):
        o2 = float(self.data.open[-2])
        c2 = float(self.data.close[-2])
        o1 = float(self.data.open[-1])
        c1 = float(self.data.close[-1])
        avg = self._avg_body()
        mid2 = (float(self.data.high[-2]) + float(self.data.low[-2])) / 2.0
        close_avg = float(self.sma[-2])
        return (c1 > o1 and
                (o2 - c2) > avg and
                c1 < o2 and
                o1 > c2 and
                mid2 < close_avg)

    def _bearish_harami(self):
        o2 = float(self.data.open[-2])
        c2 = float(self.data.close[-2])
        o1 = float(self.data.open[-1])
        c1 = float(self.data.close[-1])
        avg = self._avg_body()
        mid2 = (float(self.data.high[-2]) + float(self.data.low[-2])) / 2.0
        close_avg = float(self.sma[-2])
        return (c1 < o1 and
                (c2 - o2) > avg and
                c1 > o2 and
                o1 < c2 and
                mid2 > close_avg)

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(self.p.stoch_k, self.p.ma_period) + 5:
            return

        stoch_d1 = float(self.stoch.percD[-1])
        stoch_d2 = float(self.stoch.percD[-2]) if len(self.stoch.percD) > 2 else stoch_d1

        bull = self._bullish_harami()
        bear = self._bearish_harami()

        if self.position:
            if self.position.size > 0:
                exit_long = ((stoch_d1 > 20 and stoch_d2 < 20) or (stoch_d1 > 80 and stoch_d2 < 80))
                if exit_long or (bear and stoch_d1 > 70):
                    self.log(f'close long stoch={stoch_d1:.1f}')
                    self.close()
                    if bear and stoch_d1 > 70:
                        self.sell(size=self.p.lot)
                    return
            elif self.position.size < 0:
                exit_short = ((stoch_d1 < 80 and stoch_d2 > 80) or (stoch_d1 < 20 and stoch_d2 > 20))
                if exit_short or (bull and stoch_d1 < 30):
                    self.log(f'close short stoch={stoch_d1:.1f}')
                    self.close()
                    if bull and stoch_d1 < 30:
                        self.buy(size=self.p.lot)
                    return
        else:
            if bull and stoch_d1 < 30:
                self.log(f'buy harami stoch={stoch_d1:.1f}')
                self.buy(size=self.p.lot)
                return
            if bear and stoch_d1 > 70:
                self.log(f'sell harami stoch={stoch_d1:.1f}')
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
