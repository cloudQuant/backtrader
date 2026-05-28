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


class XMACDIndicator(bt.Indicator):
    lines = ('macd', 'signal',)
    params = dict(
        ma_method='ema',
        signal_method='sma',
        fast_period=12,
        slow_period=26,
        signal_period=9,
        applied_price='close',
    )

    def __init__(self):
        ma_cls = bt.indicators.EMA if str(self.p.ma_method).lower() == 'ema' else bt.indicators.SMA
        signal_cls = bt.indicators.EMA if str(self.p.signal_method).lower() == 'ema' else bt.indicators.SMA
        price = self._price_line()
        fast = ma_cls(price, period=self.p.fast_period)
        slow = ma_cls(price, period=self.p.slow_period)
        self.lines.macd = fast - slow
        self.lines.signal = signal_cls(self.lines.macd, period=self.p.signal_period)
        self.addminperiod(max(self.p.fast_period, self.p.slow_period) + self.p.signal_period + 5)

    def _price_line(self):
        mode = str(self.p.applied_price).lower()
        if mode == 'open':
            return self.data.open
        if mode == 'high':
            return self.data.high
        if mode == 'low':
            return self.data.low
        if mode == 'median':
            return (self.data.high + self.data.low) / 2.0
        if mode == 'typical':
            return (self.data.high + self.data.low + self.data.close) / 3.0
        if mode == 'weighted':
            return (self.data.high + self.data.low + self.data.close + self.data.close) / 4.0
        if mode == 'simpl':
            return (self.data.open + self.data.close) / 2.0
        if mode == 'quarter':
            return (self.data.high + self.data.low + self.data.open + self.data.close) / 4.0
        return self.data.close


class XMACDStrategy(bt.Strategy):
    params = dict(
        mode='MACDdisposition',
        signal_bar=1,
        ma_method='ema',
        signal_method='sma',
        fast_period=12,
        slow_period=26,
        signal_period=9,
        applied_price='close',
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.xmacd = XMACDIndicator(
            self.data,
            ma_method=self.p.ma_method,
            signal_method=self.p.signal_method,
            fast_period=self.p.fast_period,
            slow_period=self.p.slow_period,
            signal_period=self.p.signal_period,
            applied_price=self.p.applied_price,
        )
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

    def _series_values(self, line):
        base = -int(self.p.signal_bar)
        return float(line[base - 1]), float(line[base]), float(line[base + 1])

    def _signals(self):
        mode = str(self.p.mode).lower()
        m2, m1, m0 = self._series_values(self.xmacd.macd)
        s2, s1, s0 = self._series_values(self.xmacd.signal)
        if mode == 'breakdown':
            buy = m1 > 0 and m2 <= 0
            sell = m1 < 0 and m2 >= 0
        elif mode == 'macdtwist':
            buy = m1 < m2 and m0 > m1
            sell = m1 > m2 and m0 < m1
        elif mode == 'signaltwist':
            buy = s1 < s2 and s0 > s1
            sell = s1 > s2 and s0 < s1
        else:
            buy = m1 > s1 and m2 <= s2
            sell = m1 < s1 and m2 >= s2
        return buy, sell, m1, s1, m0, s0

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(self.p.fast_period, self.p.slow_period) + self.p.signal_period + self.p.signal_bar + 5:
            return

        buy_signal, sell_signal, macd_signal_bar, signal_signal_bar, macd_latest, signal_latest = self._signals()

        if self.position:
            if self.position.size > 0 and sell_signal:
                self.log(f'close long & sell macd={macd_signal_bar:.2f} signal={signal_signal_bar:.2f} latest={macd_latest:.2f}/{signal_latest:.2f}')
                self.close()
                self.sell(size=self.p.lot)
                return
            if self.position.size < 0 and buy_signal:
                self.log(f'close short & buy macd={macd_signal_bar:.2f} signal={signal_signal_bar:.2f} latest={macd_latest:.2f}/{signal_latest:.2f}')
                self.close()
                self.buy(size=self.p.lot)
                return
        else:
            if buy_signal:
                self.log(f'buy macd={macd_signal_bar:.2f} signal={signal_signal_bar:.2f}')
                self.buy(size=self.p.lot)
                return
            if sell_signal:
                self.log(f'sell macd={macd_signal_bar:.2f} signal={signal_signal_bar:.2f}')
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
