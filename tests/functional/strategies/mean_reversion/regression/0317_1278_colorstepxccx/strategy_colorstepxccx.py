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


def resolve_ma_class(name):
    mode = str(name).lower()
    if mode in {'sma', 'mode_sma'}:
        return bt.indicators.SMA
    if mode in {'ema', 'mode_ema'}:
        return bt.indicators.EMA
    if mode in {'smma', 'mode_smma'}:
        return bt.indicators.SmoothedMovingAverage
    return bt.indicators.WeightedMovingAverage


def resolve_price_line(data, mode):
    price_mode = str(mode).lower()
    if price_mode in {'price_open', 'open'}:
        return data.open
    if price_mode in {'price_high', 'high'}:
        return data.high
    if price_mode in {'price_low', 'low'}:
        return data.low
    if price_mode in {'price_median', 'median'}:
        return (data.high + data.low) / 2.0
    if price_mode in {'price_typical', 'typical'}:
        return (data.high + data.low + data.close) / 3.0
    if price_mode in {'price_weighted', 'weighted'}:
        return (data.high + data.low + data.close + data.close) / 4.0
    return data.close


class ColorStepXCCXIndicator(bt.Indicator):
    lines = ('mplus', 'mminus',)
    params = dict(
        dsmooth_method='jjma',
        dperiod=30,
        dphase=100,
        msmooth_method='t3',
        mperiod=7,
        mphase=15,
        ipc='price_typical',
        step_size_fast=5,
        step_size_slow=30,
    )

    def __init__(self):
        price_line = resolve_price_line(self.data, self.p.ipc)
        self._base = resolve_ma_class(self.p.dsmooth_method)(price_line, period=self.p.dperiod)
        self._up = resolve_ma_class(self.p.msmooth_method)(price_line - self._base, period=self.p.mperiod)
        self._dn = resolve_ma_class(self.p.msmooth_method)(abs(price_line - self._base), period=self.p.mperiod)
        self._fmin1 = 999999.0
        self._fmax1 = -999999.0
        self._smin1 = 999999.0
        self._smax1 = -999999.0
        self._ftrend = 0
        self._strend = 0
        self.addminperiod(self.p.dperiod + self.p.mperiod + 5)

    def next(self):
        xupccx = float(self._up[0])
        xdnccx = float(self._dn[0])
        xccx = 100.0 * xupccx / xdnccx if xupccx != 0.0 and xdnccx != 0.0 else 0.0
        fmax0 = xccx + 2 * float(self.p.step_size_fast)
        fmin0 = xccx - 2 * float(self.p.step_size_fast)
        if xccx > self._fmax1:
            self._ftrend = 1
        if xccx < self._fmin1:
            self._ftrend = -1
        if self._ftrend > 0 and fmin0 < self._fmin1:
            fmin0 = self._fmin1
        if self._ftrend < 0 and fmax0 > self._fmax1:
            fmax0 = self._fmax1
        smax0 = xccx + 2 * float(self.p.step_size_slow)
        smin0 = xccx - 2 * float(self.p.step_size_slow)
        if xccx > self._smax1:
            self._strend = 1
        if xccx < self._smin1:
            self._strend = -1
        if self._strend > 0 and smin0 < self._smin1:
            smin0 = self._smin1
        if self._strend < 0 and smax0 > self._smax1:
            smax0 = self._smax1
        self.lines.mplus[0] = fmin0 + float(self.p.step_size_fast) if self._ftrend > 0 else fmax0 - float(self.p.step_size_fast)
        self.lines.mminus[0] = smin0 + float(self.p.step_size_slow) if self._strend > 0 else smax0 - float(self.p.step_size_slow)
        self._fmin1 = fmin0
        self._fmax1 = fmax0
        self._smin1 = smin0
        self._smax1 = smax0

    def once(self, start, end):
        up_array = self._up.array
        dn_array = self._dn.array
        mplus_line = self.lines.mplus.array
        mminus_line = self.lines.mminus.array
        for line in (mplus_line, mminus_line):
            while len(line) < end:
                line.append(float('nan'))

        fmin1 = 999999.0
        fmax1 = -999999.0
        smin1 = 999999.0
        smax1 = -999999.0
        ftrend = 0
        strend = 0
        fast_step = float(self.p.step_size_fast)
        slow_step = float(self.p.step_size_slow)
        actual_end = min(end, len(up_array), len(dn_array))
        for i in range(start, actual_end):
            xupccx = float(up_array[i])
            xdnccx = float(dn_array[i])
            xccx = 100.0 * xupccx / xdnccx if xupccx != 0.0 and xdnccx != 0.0 else 0.0
            fmax0 = xccx + 2.0 * fast_step
            fmin0 = xccx - 2.0 * fast_step
            if xccx > fmax1:
                ftrend = 1
            if xccx < fmin1:
                ftrend = -1
            if ftrend > 0 and fmin0 < fmin1:
                fmin0 = fmin1
            if ftrend < 0 and fmax0 > fmax1:
                fmax0 = fmax1

            smax0 = xccx + 2.0 * slow_step
            smin0 = xccx - 2.0 * slow_step
            if xccx > smax1:
                strend = 1
            if xccx < smin1:
                strend = -1
            if strend > 0 and smin0 < smin1:
                smin0 = smin1
            if strend < 0 and smax0 > smax1:
                smax0 = smax1

            mplus_line[i] = fmin0 + fast_step if ftrend > 0 else fmax0 - fast_step
            mminus_line[i] = smin0 + slow_step if strend > 0 else smax0 - slow_step
            fmin1 = fmin0
            fmax1 = fmax0
            smin1 = smin0
            smax1 = smax0

        self._fmin1 = fmin1
        self._fmax1 = fmax1
        self._smin1 = smin1
        self._smax1 = smax1
        self._ftrend = ftrend
        self._strend = strend


class ColorStepXCCXStrategy(bt.Strategy):
    params = dict(
        dsmooth_method='jjma',
        dperiod=30,
        dphase=100,
        msmooth_method='t3',
        mperiod=7,
        mphase=15,
        ipc='price_typical',
        step_size_fast=5,
        step_size_slow=30,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = ColorStepXCCXIndicator(
            self.data,
            dsmooth_method=self.p.dsmooth_method,
            dperiod=self.p.dperiod,
            dphase=self.p.dphase,
            msmooth_method=self.p.msmooth_method,
            mperiod=self.p.mperiod,
            mphase=self.p.mphase,
            ipc=self.p.ipc,
            step_size_fast=self.p.step_size_fast,
            step_size_slow=self.p.step_size_slow,
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

    def _signals(self):
        shift = max(1, int(self.p.signal_bar))
        plus_prev = float(self.indicator.mplus[-shift])
        minus_prev = float(self.indicator.mminus[-shift])
        plus_cur = float(self.indicator.mplus[-shift + 1]) if shift > 1 else float(self.indicator.mplus[0])
        minus_cur = float(self.indicator.mminus[-shift + 1]) if shift > 1 else float(self.indicator.mminus[0])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if plus_prev > minus_prev:
            if plus_cur <= minus_cur:
                buy_open = True
            sell_close = True
        if plus_prev < minus_prev:
            if plus_cur >= minus_cur:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = int(self.p.dperiod) + int(self.p.mperiod) + int(self.p.signal_bar) + 10
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        plus = float(self.indicator.mplus[0])
        minus = float(self.indicator.mminus[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long mplus={plus:.4f} mminus={minus:.4f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell mplus={plus:.4f} mminus={minus:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short mplus={plus:.4f} mminus={minus:.4f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy mplus={plus:.4f} mminus={minus:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy mplus={plus:.4f} mminus={minus:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell mplus={plus:.4f} mminus={minus:.4f}')
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
