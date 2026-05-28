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


class MeetingLinesStochStrategy(bt.Strategy):
    """
    Meeting Lines candlestick pattern + Stochastic confirmation.
    Buy: Bullish Meeting Lines AND Stoch %D < 30
    Sell: Bearish Meeting Lines AND Stoch %D > 70
    Exit long: Stoch %D crosses above 20 or crosses above 80
    Exit short: Stoch %D crosses below 80 or crosses below 20
    """
    params = dict(
        stoch_k=6,
        stoch_d=3,
        stoch_slow=36,
        ma_period=3,
        stoch_entry_long=30,
        stoch_entry_short=70,
        stoch_exit_upper=80,
        stoch_exit_lower=20,
        lot=0.1,
        point=0.01,
        price_digits=2,
        body_multiplier=1.0,
        close_tolerance_multiplier=0.1,
    )

    def __init__(self):
        self.stoch = bt.indicators.StochasticSlow(
            self.data,
            period=self.p.stoch_k,
            period_dfast=self.p.stoch_d,
            period_dslow=self.p.stoch_slow)
        self.sma_body = bt.indicators.SMA(
            abs(self.data.close - self.data.open), period=self.p.ma_period)
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
        return float(self.sma_body[0])

    def _is_bullish_meeting_lines(self):
        """Two candles: long bearish followed by long bullish, closes nearly equal"""
        o2, c2 = float(self.data.open[-2]), float(self.data.close[-2])
        o1, c1 = float(self.data.open[-1]), float(self.data.close[-1])
        avg = self._avg_body()
        if avg < self.p.point:
            return False
        return ((o2 - c2) > float(self.p.body_multiplier) * avg and
                (c1 - o1) > float(self.p.body_multiplier) * avg and
                abs(c1 - c2) < float(self.p.close_tolerance_multiplier) * avg)

    def _is_bearish_meeting_lines(self):
        """Two candles: long bullish followed by long bearish, closes nearly equal"""
        o2, c2 = float(self.data.open[-2]), float(self.data.close[-2])
        o1, c1 = float(self.data.open[-1]), float(self.data.close[-1])
        avg = self._avg_body()
        if avg < self.p.point:
            return False
        return ((c2 - o2) > float(self.p.body_multiplier) * avg and
                (o1 - c1) > float(self.p.body_multiplier) * avg and
                abs(c1 - c2) < float(self.p.close_tolerance_multiplier) * avg)

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.stoch_k + self.p.stoch_slow, self.p.ma_period) + 5
        if len(self.data) < warmup:
            return

        sd0 = float(self.stoch.percD[0])
        sd1 = float(self.stoch.percD[-1])

        if self.position:
            if self.position.size > 0:
                if ((sd0 > self.p.stoch_exit_lower and sd1 < self.p.stoch_exit_lower) or
                    (sd0 > self.p.stoch_exit_upper and sd1 < self.p.stoch_exit_upper)):
                    self.log(f'close long stoch_d={sd0:.1f}')
                    self.close()
                    return
            elif self.position.size < 0:
                if ((sd0 < self.p.stoch_exit_upper and sd1 > self.p.stoch_exit_upper) or
                    (sd0 < self.p.stoch_exit_lower and sd1 > self.p.stoch_exit_lower)):
                    self.log(f'close short stoch_d={sd0:.1f}')
                    self.close()
                    return
        else:
            if self._is_bullish_meeting_lines() and sd0 < self.p.stoch_entry_long:
                self.log(f'buy meeting_lines stoch_d={sd0:.1f}')
                self.buy(size=self.p.lot)
                return
            if self._is_bearish_meeting_lines() and sd0 > self.p.stoch_entry_short:
                self.log(f'sell meeting_lines stoch_d={sd0:.1f}')
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
