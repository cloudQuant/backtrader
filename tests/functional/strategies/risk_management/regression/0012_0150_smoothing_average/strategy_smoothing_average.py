from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import backtrader.feeds as btfeeds
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(btfeeds.PandasData):
    lines = ('spread', 'typical')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6), ('typical', 7),
    )


class TypicalPrice(bt.Indicator):
    lines = ('typical',)

    def next(self):
        self.lines.typical[0] = (self.data.high[0] + self.data.low[0] + self.data.close[0]) / 3.0


class SmoothingAverageStrategy(bt.Strategy):
    params = dict(
        fixed_lot=1.0,
        ma_period=60,
        ma_shift=3,
        ma_method='sma',
        delta_pips=60,
        delta_close_coefficient=1.0,
        reverse_signals=False,
        point_size=0.01,
    )

    def __init__(self):
        typical = TypicalPrice(self.datas[0])
        method = str(self.p.ma_method).lower()
        if method == 'ema':
            self.ma = bt.indicators.EMA(typical, period=self.p.ma_period)
        elif method == 'smma':
            self.ma = bt.indicators.SmoothedMovingAverage(typical, period=self.p.ma_period)
        elif method == 'wma':
            self.ma = bt.indicators.WeightedMovingAverage(typical, period=self.p.ma_period)
        else:
            self.ma = bt.indicators.SimpleMovingAverage(typical, period=self.p.ma_period)
        self.last_bar_dt = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.datas[0].datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _new_bar(self):
        current = bt.num2date(self.datas[0].datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _ma_value(self):
        shift = int(self.p.ma_shift)
        if len(self.ma) <= shift:
            return None
        return float(self.ma[-shift]) if shift > 0 else float(self.ma[0])

    def next(self):
        self.bar_num += 1
        if len(self) < self.p.ma_period + max(1, self.p.ma_shift):
            return
        if not self._new_bar():
            return
        ma_value = self._ma_value()
        if ma_value is None:
            return
        delta = self.p.delta_pips * self.p.point_size
        close_delta = delta * self.p.delta_close_coefficient
        ask_proxy = float(self.datas[0].close[0])
        bid_proxy = float(self.datas[0].close[0])
        if not self.position:
            if ask_proxy > ma_value - delta:
                if not self.p.reverse_signals:
                    self.buy(size=max(0.01, float(self.p.fixed_lot)))
                    self.buy_count += 1
                    self.log(f'OPEN LONG ma={ma_value:.5f} ask={ask_proxy:.5f}')
                else:
                    self.sell(size=max(0.01, float(self.p.fixed_lot)))
                    self.sell_count += 1
                    self.log(f'OPEN SHORT reverse ma={ma_value:.5f} ask={ask_proxy:.5f}')
                return
            if bid_proxy < ma_value + delta:
                if not self.p.reverse_signals:
                    self.sell(size=max(0.01, float(self.p.fixed_lot)))
                    self.sell_count += 1
                    self.log(f'OPEN SHORT ma={ma_value:.5f} bid={bid_proxy:.5f}')
                else:
                    self.buy(size=max(0.01, float(self.p.fixed_lot)))
                    self.buy_count += 1
                    self.log(f'OPEN LONG reverse ma={ma_value:.5f} bid={bid_proxy:.5f}')
                return
        else:
            if not self.p.reverse_signals:
                if self.position.size < 0 and bid_proxy > ma_value + close_delta:
                    self.close()
                    self.log(f'CLOSE SHORT ma={ma_value:.5f} bid={bid_proxy:.5f}')
                elif self.position.size > 0 and ask_proxy < ma_value - close_delta:
                    self.close()
                    self.log(f'CLOSE LONG ma={ma_value:.5f} ask={ask_proxy:.5f}')
            else:
                if self.position.size > 0 and ask_proxy < ma_value - close_delta:
                    self.close()
                    self.log(f'CLOSE LONG reverse ma={ma_value:.5f} ask={ask_proxy:.5f}')
                elif self.position.size < 0 and bid_proxy > ma_value + close_delta:
                    self.close()
                    self.log(f'CLOSE SHORT reverse ma={ma_value:.5f} bid={bid_proxy:.5f}')

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
