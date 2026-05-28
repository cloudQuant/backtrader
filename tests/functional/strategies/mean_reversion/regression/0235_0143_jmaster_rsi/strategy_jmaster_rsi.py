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
    lines = ('spread',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6),
    )


class SmoothedRsi(bt.Indicator):
    lines = ('value',)
    params = dict(period=14, smoothing=6)

    def __init__(self):
        rsi = bt.indicators.RSI(self.data, period=self.p.period)
        self.lines.value = bt.indicators.SimpleMovingAverage(rsi, period=self.p.smoothing)


class JMasterRsiStrategy(bt.Strategy):
    params = dict(
        fixed_lot=1.0,
        long_timeframe_period=10,
        short_timeframe_period=4,
        long_buy_level=25,
        short_buy_level=25,
        long_sell_level=75,
        short_sell_level=75,
        long_trend_spread=4,
        linreg_len=5,
        linreg_trade_pips=40,
        trade_trend=True,
        point_size=0.01,
        verbose=False,
    )

    def __init__(self):
        self.data_m5 = self.datas[0]
        self.data_m15 = self.datas[1]
        self.data_h4 = self.datas[2]
        self.long_rsi = SmoothedRsi(self.data_m15.close, period=self.p.long_timeframe_period)
        self.short_rsi = SmoothedRsi(self.data_m5.close, period=self.p.short_timeframe_period)
        self.last_bar_dt = None
        self.entry_order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        if not self.p.verbose:
            return
        dt = bt.num2date(self.data_m5.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _new_bar(self):
        current = bt.num2date(self.data_m5.datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _linear_regression_slope_abs(self):
        length = int(self.p.linreg_len)
        if len(self.data_h4) < length:
            return None
        closes = [float(self.data_h4.close[-i]) for i in range(length)]
        sumy = 0.0
        sumxy = 0.0
        sumx = 0.0
        sumx2 = 0.0
        for i, close in enumerate(closes):
            sumy += close
            sumxy += close * i
            sumx += i
            sumx2 += i * i
        c = sumx2 * length - sumx * sumx
        if c == 0.0:
            return None
        b = (sumxy * length - sumx * sumy) / c
        a = (sumy - sumx * b) / length
        first = a
        last = a + b * (length - 1)
        return abs(first - last)

    def _signal_ready(self):
        trend_spread = max(2, int(self.p.long_trend_spread))
        return len(self.data_h4) >= self.p.linreg_len and len(self.long_rsi) > trend_spread and len(self.short_rsi) > 2

    def _build_signals(self):
        trend_spread = max(2, int(self.p.long_trend_spread))
        long_now = float(self.long_rsi[0])
        long_prev = float(self.long_rsi[-trend_spread])
        short_now = float(self.short_rsi[0])
        short_prev = float(self.short_rsi[-1])
        c_sell = int(long_now) < self.p.long_sell_level and int(short_now) > self.p.short_sell_level and long_now < long_prev and short_now < short_prev
        c_buy = int(long_now) > self.p.long_buy_level and int(short_now) < self.p.short_buy_level and long_now > long_prev and short_now > short_prev
        return c_buy, c_sell

    def next(self):
        self.bar_num += 1
        if not self._new_bar():
            return
        if not self._signal_ready():
            return
        if self.entry_order is not None:
            return
        c_buy, c_sell = self._build_signals()
        if self.position:
            if self.position.size > 0 and c_sell:
                self.close()
                self.log('CLOSE LONG BY OPPOSITE SIGNAL')
            elif self.position.size < 0 and c_buy:
                self.close()
                self.log('CLOSE SHORT BY OPPOSITE SIGNAL')
            return
        slope_abs = self._linear_regression_slope_abs()
        if slope_abs is None:
            return
        if self.p.trade_trend and slope_abs <= float(self.p.linreg_trade_pips) * float(self.p.point_size):
            return
        size = max(0.01, float(self.p.fixed_lot))
        if c_buy:
            self.entry_order = self.buy(size=size)
            self.buy_count += 1
            self.log(f'OPEN LONG slope={slope_abs:.5f}')
            return
        if c_sell:
            self.entry_order = self.sell(size=size)
            self.sell_count += 1
            self.log(f'OPEN SHORT slope={slope_abs:.5f}')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order == self.entry_order:
            if order.status == order.Completed:
                self.entry_order = None
                return
            if order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.entry_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
