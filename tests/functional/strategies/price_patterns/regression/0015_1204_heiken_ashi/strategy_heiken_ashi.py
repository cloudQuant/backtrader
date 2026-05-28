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


class HeikenAshiStrategy(bt.Strategy):
    """
    Heiken Ashi candle color change strategy.
    HA_Close = (O+H+L+C)/4
    HA_Open  = (prev_HA_Open + prev_HA_Close)/2
    Buy: HA turns bullish (HA_Close > HA_Open) after bearish
    Sell: HA turns bearish (HA_Close < HA_Open) after bullish
    """
    params = dict(
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self.ha_open = 0.0
        self.ha_close = 0.0
        self.prev_ha_bullish = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        self.bar_num += 1
        o = float(self.data.open[0])
        h = float(self.data.high[0])
        l = float(self.data.low[0])
        c = float(self.data.close[0])

        self.ha_close = (o + h + l + c) / 4.0
        if self.bar_num == 1:
            self.ha_open = (o + c) / 2.0
        else:
            self.ha_open = (self.ha_open + self.ha_close) / 2.0

        ha_bullish = self.ha_close > self.ha_open

        if self.prev_ha_bullish is not None and self.bar_num > 2:
            if ha_bullish and not self.prev_ha_bullish:
                if self.position.size < 0:
                    self.close()
                if self.position.size <= 0:
                    self.buy(size=self.p.lot)
            elif not ha_bullish and self.prev_ha_bullish:
                if self.position.size > 0:
                    self.close()
                if self.position.size >= 0:
                    self.sell(size=self.p.lot)

        self.prev_ha_bullish = ha_bullish

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
