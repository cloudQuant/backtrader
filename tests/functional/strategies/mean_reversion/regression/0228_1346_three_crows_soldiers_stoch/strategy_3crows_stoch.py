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


class ThreeCrowsSoldiersStochStrategy(bt.Strategy):
    """
    3 Black Crows / 3 White Soldiers + Stochastic confirmation.

    Open long: 3 White Soldiers pattern AND Stochastic %D < 30
    Close long: Stochastic %D crosses down through 80 or up through 20
    Open short: 3 Black Crows pattern AND Stochastic %D > 70
    Close short: Stochastic %D crosses up through 20 or up through 80
    """
    params = dict(
        stoch_period_k=47,
        stoch_period_d=9,
        stoch_period_slow=13,
        ma_period=5,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.stoch = bt.indicators.StochasticSlow(
            self.data,
            period=self.p.stoch_period_k,
            period_dfast=self.p.stoch_period_slow,
            period_dslow=self.p.stoch_period_d,
        )
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
        if len(self.data) < max(self.p.stoch_period_k, self.p.ma_period) + 5:
            return

        stoch_d_1 = float(self.stoch.percD[-1])
        stoch_d_2 = float(self.stoch.percD[-2]) if len(self.stoch.percD) > 2 else stoch_d_1

        if self.position:
            if self.position.size > 0:
                # Close long: %D crosses down through 80 or up through 20
                if ((stoch_d_1 < 80 and stoch_d_2 > 80) or
                        (stoch_d_1 < 20 and stoch_d_2 > 20)):
                    self.log(f'close long stoch_d={stoch_d_1:.2f}')
                    self.close()
                    return
            elif self.position.size < 0:
                # Close short: %D crosses up through 20 or up through 80
                if ((stoch_d_1 > 20 and stoch_d_2 < 20) or
                        (stoch_d_1 > 80 and stoch_d_2 < 80)):
                    self.log(f'close short stoch_d={stoch_d_1:.2f}')
                    self.close()
                    return
        else:
            # Open long: 3 White Soldiers + Stochastic %D < 30
            if self._three_white_soldiers() and stoch_d_1 < 30:
                self.log(f'buy signal price={self.data.close[0]:.2f} stoch_d={stoch_d_1:.2f}')
                self.buy(size=self.p.lot)
                return
            # Open short: 3 Black Crows + Stochastic %D > 70
            if self._three_black_crows() and stoch_d_1 > 70:
                self.log(f'sell signal price={self.data.close[0]:.2f} stoch_d={stoch_d_1:.2f}')
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
