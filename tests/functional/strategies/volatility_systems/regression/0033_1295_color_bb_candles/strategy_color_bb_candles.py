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


class ColorBBCandlesIndicator(bt.Indicator):
    lines = ('state', 'price_line', 'mid',)
    params = dict(
        period=100,
        deviation1=1.0,
        deviation2=1.5,
        deviation3=2.0,
        deviation4=2.5,
        deviation5=3.0,
        ma_method='ema',
        applied_price='close',
    )

    def __init__(self):
        ma_cls = bt.indicators.EMA if str(self.p.ma_method).lower() == 'ema' else bt.indicators.SMA
        self.price = self._price_line()
        self.lines.price_line = self.price
        self.lines.mid = ma_cls(self.price, period=self.p.period)
        self.stddev = bt.indicators.StandardDeviation(self.price, period=self.p.period)
        self.addminperiod(self.p.period + 5)

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

    def next(self):
        price = float(self.price[0])
        mid = float(self.lines.mid[0])
        stdev = float(self.stddev[0])
        up1 = mid + stdev * self.p.deviation1
        up2 = mid + stdev * self.p.deviation2
        up3 = mid + stdev * self.p.deviation3
        up4 = mid + stdev * self.p.deviation4
        up5 = mid + stdev * self.p.deviation5
        dn1 = mid - stdev * self.p.deviation1
        dn2 = mid - stdev * self.p.deviation2
        dn3 = mid - stdev * self.p.deviation3
        dn4 = mid - stdev * self.p.deviation4
        dn5 = mid - stdev * self.p.deviation5
        state = 5.0
        if price > up5:
            state = 10.0
        elif price > up4:
            state = 9.0
        elif price > up3:
            state = 8.0
        elif price > up2:
            state = 7.0
        elif price > up1:
            state = 6.0
        elif price < dn5:
            state = 0.0
        elif price < dn4:
            state = 1.0
        elif price < dn3:
            state = 2.0
        elif price < dn2:
            state = 3.0
        elif price < dn1:
            state = 4.0
        self.lines.state[0] = state


class ColorBBCandlesStrategy(bt.Strategy):
    params = dict(
        period=100,
        deviation1=1.0,
        deviation2=1.5,
        deviation3=2.0,
        deviation4=2.5,
        deviation5=3.0,
        ma_method='ema',
        applied_price='close',
        signal_bar=1,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.signal = ColorBBCandlesIndicator(
            self.data,
            period=self.p.period,
            deviation1=self.p.deviation1,
            deviation2=self.p.deviation2,
            deviation3=self.p.deviation3,
            deviation4=self.p.deviation4,
            deviation5=self.p.deviation5,
            ma_method=self.p.ma_method,
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

    def _state_values(self):
        base = -int(self.p.signal_bar)
        return float(self.signal.state[base - 1]), float(self.signal.state[base])

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.p.period + self.p.signal_bar + 5:
            return

        prev_state, curr_state = self._state_values()
        buy_signal = curr_state > 5.0 and prev_state < 6.0
        sell_signal = curr_state < 5.0 and prev_state > 4.0
        if not buy_signal and not sell_signal and not self.position:
            buy_signal = curr_state > 5.0
            sell_signal = curr_state < 5.0
        flat_signal = curr_state == 5.0

        if flat_signal and self.position:
            self.log(f'close neutral state={curr_state:.0f}')
            self.close()
            return

        if self.position:
            if self.position.size > 0 and sell_signal:
                self.log(f'close long & sell state={curr_state:.0f}')
                self.close()
                self.sell(size=self.p.lot)
                return
            if self.position.size < 0 and buy_signal:
                self.log(f'close short & buy state={curr_state:.0f}')
                self.close()
                self.buy(size=self.p.lot)
                return
        else:
            if buy_signal:
                self.log(f'buy state={curr_state:.0f}')
                self.buy(size=self.p.lot)
                return
            if sell_signal:
                self.log(f'sell state={curr_state:.0f}')
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
