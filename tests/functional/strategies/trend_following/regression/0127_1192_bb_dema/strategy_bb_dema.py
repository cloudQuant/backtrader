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


class BBDemaStrategy(bt.Strategy):
    """
    Bollinger Bands + DEMA trend-following strategy.
    Buy: DEMA rising AND bullish candle crosses BB lower band from below to above.
    Sell: DEMA falling AND bearish candle crosses BB upper band from above to below.
    Close long: bearish candle crosses BB upper band from above to below.
    Close short: bullish candle crosses BB lower band from below to above.
    """
    params = dict(
        bb_period=20,
        bb_dev=2.0,
        dema_period=14,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.bb = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bb_period, devfactor=self.p.bb_dev)
        self.dema = bt.indicators.DEMA(self.data.close, period=self.p.dema_period)
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
        if len(self.data) < max(self.p.bb_period, self.p.dema_period) + 5:
            return

        o = float(self.data.open[0])
        c = float(self.data.close[0])
        bb_top = float(self.bb.top[0])
        bb_bot = float(self.bb.bot[0])
        dema0 = float(self.dema[0])
        dema1 = float(self.dema[-1])

        bullish = c > o
        bearish = c < o
        dema_rising = dema0 > dema1
        dema_falling = dema0 < dema1

        cross_above_lower = float(self.data.low[0]) < bb_bot and c > bb_bot
        cross_below_upper = float(self.data.high[0]) > bb_top and c < bb_top

        if self.position:
            if self.position.size > 0:
                if bearish and cross_below_upper:
                    self.log(f'close long bb_top={bb_top:.2f} c={c:.2f}')
                    self.close()
                    if dema_falling:
                        self.sell(size=self.p.lot)
                    return
            elif self.position.size < 0:
                if bullish and cross_above_lower:
                    self.log(f'close short bb_bot={bb_bot:.2f} c={c:.2f}')
                    self.close()
                    if dema_rising:
                        self.buy(size=self.p.lot)
                    return
        else:
            if dema_rising and bullish and cross_above_lower:
                self.log(f'buy dema={dema0:.2f} bb_bot={bb_bot:.2f}')
                self.buy(size=self.p.lot)
                return
            if dema_falling and bearish and cross_below_upper:
                self.log(f'sell dema={dema0:.2f} bb_top={bb_top:.2f}')
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
