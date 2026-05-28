from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3] / 'backtrader'
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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


class EngulfingStochStrategy(bt.Strategy):
    """
    Bullish/Bearish Engulfing + Stochastic confirmation.
    Buy: Bullish Engulfing AND Stoch %D < stoch_entry_long
    Sell: Bearish Engulfing AND Stoch %D > stoch_entry_short
    Exit: Stoch %D crosses overbought/oversold levels
    """
    params = dict(
        stoch_k=8, stoch_d=3, stoch_slow=3,
        ma_period=5,
        stoch_entry_long=30, stoch_entry_short=70,
        stoch_exit_upper=80, stoch_exit_lower=20,
        lot=0.1, point=0.01, price_digits=2,
    )

    def __init__(self):
        self.stoch = bt.indicators.StochasticSlow(
            self.data, period=self.p.stoch_k,
            period_dfast=self.p.stoch_d, period_dslow=self.p.stoch_slow)
        self.close_avg = bt.indicators.SMA(self.data.close, period=self.p.ma_period)
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

    def _bullish_engulfing(self):
        o2, c2 = float(self.data.open[-2]), float(self.data.close[-2])
        o1, c1 = float(self.data.open[-1]), float(self.data.close[-1])
        avg = self._avg_body()
        if avg <= 0: return False
        mid2 = (o2 + c2) / 2.0
        cavg = float(self.close_avg[-2])
        return (o2 > c2 and (c1 - o1) > avg and c1 > o2 and mid2 < cavg and o1 < c2)

    def _bearish_engulfing(self):
        o2, c2 = float(self.data.open[-2]), float(self.data.close[-2])
        o1, c1 = float(self.data.open[-1]), float(self.data.close[-1])
        avg = self._avg_body()
        if avg <= 0: return False
        mid2 = (o2 + c2) / 2.0
        cavg = float(self.close_avg[-2])
        return (o2 < c2 and (o1 - c1) > avg and c1 < o2 and mid2 > cavg and o1 > c2)

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
                    self.log(f'close long stoch={sd0:.1f}')
                    self.close()
                    return
            elif self.position.size < 0:
                if ((sd0 < self.p.stoch_exit_upper and sd1 > self.p.stoch_exit_upper) or
                    (sd0 < self.p.stoch_exit_lower and sd1 > self.p.stoch_exit_lower)):
                    self.log(f'close short stoch={sd0:.1f}')
                    self.close()
                    return
        else:
            if self._bullish_engulfing() and sd0 < self.p.stoch_entry_long:
                self.log(f'buy engulfing+stoch stoch={sd0:.1f}')
                self.buy(size=self.p.lot)
                return
            if self._bearish_engulfing() and sd0 > self.p.stoch_entry_short:
                self.log(f'sell engulfing+stoch stoch={sd0:.1f}')
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
