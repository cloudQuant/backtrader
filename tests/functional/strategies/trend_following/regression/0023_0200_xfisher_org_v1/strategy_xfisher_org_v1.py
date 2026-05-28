from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
import sys
from pathlib import Path

import pandas as pd

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
LOCAL_BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(LOCAL_BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(LOCAL_BACKTRADER_REPO))

import backtrader as bt


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


class XFisherIndicator(bt.Indicator):
    lines = ('xfisher', 'signal')
    params = dict(
        flength=7,
        ma_length=5,
    )

    def __init__(self):
        self.addminperiod(self.p.flength + self.p.ma_length + 2)
        self._value_prev = 0.0
        self._fish_prev = 0.0
        self._smooth_prev = None
        self._alpha = 2.0 / (self.p.ma_length + 1.0)

    def next(self):
        highs = [float(self.data.high[-i]) for i in range(self.p.flength)]
        lows = [float(self.data.low[-i]) for i in range(self.p.flength)]
        smax = max(highs)
        smin = min(lows)
        spread = smax - smin
        if spread == 0:
            spread = 1e-12

        price = float(self.data.close[0])
        wpr = (price - smin) / spread
        value = (wpr - 0.5) + 0.67 * self._value_prev
        value = max(min(value, 0.999), -0.999)

        ratio = (1.0 + value) / (1.0 - value)
        ratio = max(ratio, 1e-7)
        fish = 0.5 * math.log(ratio) + 0.5 * self._fish_prev
        smooth = fish if self._smooth_prev is None else self._smooth_prev + self._alpha * (fish - self._smooth_prev)

        prev_smooth = smooth if len(self) <= 1 else float(self.lines.xfisher[-1])
        self.lines.xfisher[0] = smooth
        self.lines.signal[0] = prev_smooth

        self._value_prev = value
        self._fish_prev = fish
        self._smooth_prev = smooth


class XFisherOrgV1Strategy(bt.Strategy):
    params = dict(
        flength=7,
        ma_length=5,
        lot=0.1,
        point=0.01,
        price_digits=2,
        stop_loss_points=1000,
        take_profit_points=2000,
    )

    def __init__(self):
        self.xfisher = XFisherIndicator(
            self.data,
            flength=self.p.flength,
            ma_length=self.p.ma_length,
        )
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._entry_price = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _long_stop_hit(self):
        if self._entry_price is None or self.p.stop_loss_points <= 0:
            return False
        stop_price = self._entry_price - self.p.stop_loss_points * self.p.point
        return float(self.data.low[0]) <= stop_price

    def _long_take_profit_hit(self):
        if self._entry_price is None or self.p.take_profit_points <= 0:
            return False
        take_profit_price = self._entry_price + self.p.take_profit_points * self.p.point
        return float(self.data.high[0]) >= take_profit_price

    def _short_stop_hit(self):
        if self._entry_price is None or self.p.stop_loss_points <= 0:
            return False
        stop_price = self._entry_price + self.p.stop_loss_points * self.p.point
        return float(self.data.high[0]) >= stop_price

    def _short_take_profit_hit(self):
        if self._entry_price is None or self.p.take_profit_points <= 0:
            return False
        take_profit_price = self._entry_price - self.p.take_profit_points * self.p.point
        return float(self.data.low[0]) <= take_profit_price

    def next(self):
        self.bar_num += 1
        warmup = self.p.flength + self.p.ma_length + 5
        if len(self.data) < warmup:
            return

        ind0 = float(self.xfisher.xfisher[0])
        sig0 = float(self.xfisher.signal[0])
        ind1 = float(self.xfisher.xfisher[-1])
        sig1 = float(self.xfisher.signal[-1])

        bullish_now = ind0 > sig0
        bearish_now = ind0 < sig0
        bullish_cross = ind1 <= sig1 and bullish_now
        bearish_cross = ind1 >= sig1 and bearish_now

        if self.position.size > 0:
            if self._long_stop_hit():
                self.log(f'close long stop ind={ind0:.4f} signal={sig0:.4f}')
                self.close()
                return
            if self._long_take_profit_hit():
                self.log(f'close long take_profit ind={ind0:.4f} signal={sig0:.4f}')
                self.close()
                return
            if bearish_now:
                if bearish_cross:
                    self.log(f'close long & sell ind={ind0:.4f} signal={sig0:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                else:
                    self.log(f'close long regime ind={ind0:.4f} signal={sig0:.4f}')
                    self.close()
                return

        if self.position.size < 0:
            if self._short_stop_hit():
                self.log(f'close short stop ind={ind0:.4f} signal={sig0:.4f}')
                self.close()
                return
            if self._short_take_profit_hit():
                self.log(f'close short take_profit ind={ind0:.4f} signal={sig0:.4f}')
                self.close()
                return
            if bullish_now:
                if bullish_cross:
                    self.log(f'close short & buy ind={ind0:.4f} signal={sig0:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                else:
                    self.log(f'close short regime ind={ind0:.4f} signal={sig0:.4f}')
                    self.close()
                return

        if not self.position:
            if bullish_cross:
                self.log(f'buy ind={ind0:.4f} signal={sig0:.4f}')
                self.buy(size=self.p.lot)
                return
            if bearish_cross:
                self.log(f'sell ind={ind0:.4f} signal={sig0:.4f}')
                self.sell(size=self.p.lot)
                return

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            self._position_was_open = True
            self._entry_price = trade.price
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self._entry_price = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
