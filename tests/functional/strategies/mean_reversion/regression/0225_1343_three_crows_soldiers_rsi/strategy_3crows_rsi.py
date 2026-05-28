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


class ThreeCrowsSoldiersRSIStrategy(bt.Strategy):
    """
    3 Black Crows / 3 White Soldiers + RSI confirmation.

    Open long: 3 White Soldiers AND RSI < 40
    Close long: RSI crosses up through 30 or up through 70
    Open short: 3 Black Crows AND RSI > 60
    Close short: RSI crosses down through 70 or down through 30
    """
    params = dict(
        rsi_period=37,
        ma_period=51,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
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
        count = min(self.p.ma_period, len(self.data) - 1)
        if count <= 0:
            return 0.0
        for i in range(-count, 0):
            total += abs(float(self.data.close[i]) - float(self.data.open[i]))
        return total / count

    def _mid_point(self, idx):
        return (float(self.data.high[idx]) + float(self.data.low[idx])) / 2.0

    def _three_white_soldiers(self):
        if len(self.data) < 4:
            return False
        avg = self._avg_body()
        if avg <= 0:
            return False
        return (
            (float(self.data.close[-3]) - float(self.data.open[-3]) > avg) and
            (float(self.data.close[-2]) - float(self.data.open[-2]) > avg) and
            (float(self.data.close[-1]) - float(self.data.open[-1]) > avg) and
            (self._mid_point(-2) > self._mid_point(-3)) and
            (self._mid_point(-1) > self._mid_point(-2))
        )

    def _three_black_crows(self):
        if len(self.data) < 4:
            return False
        avg = self._avg_body()
        if avg <= 0:
            return False
        return (
            (float(self.data.open[-3]) - float(self.data.close[-3]) > avg) and
            (float(self.data.open[-2]) - float(self.data.close[-2]) > avg) and
            (float(self.data.open[-1]) - float(self.data.close[-1]) > avg) and
            (self._mid_point(-2) < self._mid_point(-3)) and
            (self._mid_point(-1) < self._mid_point(-2))
        )

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(self.p.rsi_period, self.p.ma_period) + 5:
            return

        rsi_1 = float(self.rsi[-1])
        rsi_2 = float(self.rsi[-2]) if len(self.rsi) > 2 else rsi_1

        if self.position:
            if self.position.size > 0:
                if ((rsi_1 > 30 and rsi_2 < 30) or (rsi_1 > 70 and rsi_2 < 70)):
                    self.log(f'close long rsi={rsi_1:.2f}')
                    self.close()
                    return
            elif self.position.size < 0:
                if ((rsi_1 < 70 and rsi_2 > 70) or (rsi_1 < 30 and rsi_2 > 30)):
                    self.log(f'close short rsi={rsi_1:.2f}')
                    self.close()
                    return
        else:
            if self._three_white_soldiers() and rsi_1 < 40:
                self.log(f'buy signal price={self.data.close[0]:.2f} rsi={rsi_1:.2f}')
                self.buy(size=self.p.lot)
                return
            if self._three_black_crows() and rsi_1 > 60:
                self.log(f'sell signal price={self.data.close[0]:.2f} rsi={rsi_1:.2f}')
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
