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


class DarkCloudRsiStrategy(bt.Strategy):
    """
    Dark Cloud Cover / Piercing Line + RSI confirmation.
    """
    params = dict(
        rsi_period=11,
        rsi_entry_long=40,
        rsi_entry_short=60,
        rsi_exit_upper=70,
        rsi_exit_lower=30,
        ma_period=5,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
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

    def _is_dark_cloud_cover(self):
        o2, h2, c2 = float(self.data.open[-2]), float(self.data.high[-2]), float(self.data.close[-2])
        o1, c1 = float(self.data.open[-1]), float(self.data.close[-1])
        avg = self._avg_body()
        mid2 = (o2 + c2) / 2.0
        cavg = float(self.close_avg[-1])
        return ((c2 - o2) > avg and
                c1 < c2 and c1 > o2 and
                mid2 > cavg and
                o1 > h2)

    def _is_piercing_line(self):
        o2, l2, c2 = float(self.data.open[-2]), float(self.data.low[-2]), float(self.data.close[-2])
        o1, c1 = float(self.data.open[-1]), float(self.data.close[-1])
        avg = self._avg_body()
        mid2 = (o2 + c2) / 2.0
        cavg = float(self.close_avg[-2])
        return ((c1 - o1) > avg and
                (o2 - c2) > avg and
                c1 > c2 and c1 < o2 and
                mid2 < cavg and
                o1 < l2)

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.rsi_period, self.p.ma_period) + 5
        if len(self.data) < warmup:
            return

        rsi0 = float(self.rsi[0])
        rsi1 = float(self.rsi[-1])

        if self.position:
            if self.position.size > 0:
                if ((rsi0 < self.p.rsi_exit_upper and rsi1 > self.p.rsi_exit_upper) or
                    (rsi0 < self.p.rsi_exit_lower and rsi1 > self.p.rsi_exit_lower)):
                    self.log(f'close long rsi={rsi0:.1f}')
                    self.close()
                    return
            elif self.position.size < 0:
                if ((rsi0 > self.p.rsi_exit_lower and rsi1 < self.p.rsi_exit_lower) or
                    (rsi0 > self.p.rsi_exit_upper and rsi1 < self.p.rsi_exit_upper)):
                    self.log(f'close short rsi={rsi0:.1f}')
                    self.close()
                    return
        else:
            if self._is_piercing_line() and rsi0 < self.p.rsi_entry_long:
                self.log(f'buy piercing+rsi rsi={rsi0:.1f}')
                self.buy(size=self.p.lot)
                return
            if self._is_dark_cloud_cover() and rsi0 > self.p.rsi_entry_short:
                self.log(f'sell darkcloud+rsi rsi={rsi0:.1f}')
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
