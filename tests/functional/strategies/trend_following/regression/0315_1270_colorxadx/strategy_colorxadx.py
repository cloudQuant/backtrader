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
    if mode in {'mode_t3', 't3', 'mode_ema', 'ema', 'mode_ama', 'ama', 'mode_jjma', 'jjma', 'mode_jurx', 'jurx', 'mode_vidya', 'vidya', 'mode_parma', 'parma'}:
        return bt.indicators.ExponentialMovingAverage
    if mode in {'mode_sma', 'sma'}:
        return bt.indicators.SimpleMovingAverage
    if mode in {'mode_smma', 'smma'}:
        return bt.indicators.SmoothedMovingAverage
    return bt.indicators.WeightedMovingAverage


class SmoothedADXIndicator(bt.Indicator):
    lines = ('plus_di', 'minus_di', 'adx')
    params = dict(xma_method='t3', adx_period=14, adx_phase=100)

    def __init__(self):
        ma_cls = resolve_ma_class(self.p.xma_method)
        self._plus = bt.indicators.PlusDirectionalIndicator(self.data, period=max(1, int(self.p.adx_period)))
        self._minus = bt.indicators.MinusDirectionalIndicator(self.data, period=max(1, int(self.p.adx_period)))
        self._adx_raw = bt.indicators.ADX(self.data, period=max(1, int(self.p.adx_period)))
        self._plus_smooth = ma_cls(self._plus, period=max(1, int(self.p.adx_period)))
        self._minus_smooth = ma_cls(self._minus, period=max(1, int(self.p.adx_period)))
        self._adx_smooth = ma_cls(self._adx_raw, period=max(1, int(self.p.adx_period)))
        self.lines.plus_di = self._plus_smooth
        self.lines.minus_di = self._minus_smooth
        self.lines.adx = self._adx_smooth
        self.addminperiod(int(self.p.adx_period) * 3)


class ColorXADXStrategy(bt.Strategy):
    params = dict(
        xma_method='t3',
        adx_period=14,
        adx_phase=100,
        extra_high_level=30,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = SmoothedADXIndicator(
            self.data,
            xma_method=self.p.xma_method,
            adx_period=self.p.adx_period,
            adx_phase=self.p.adx_phase,
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
        mplus_prev = float(self.indicator.plus_di[-shift])
        mminus_prev = float(self.indicator.minus_di[-shift])
        mplus_cur = float(self.indicator.plus_di[-shift + 1]) if shift > 1 else float(self.indicator.plus_di[0])
        mminus_cur = float(self.indicator.minus_di[-shift + 1]) if shift > 1 else float(self.indicator.minus_di[0])
        adx_filter = float(self.indicator.adx[-shift + 1]) if shift > 1 else float(self.indicator.adx[0])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if mplus_prev > mminus_prev:
            if mplus_cur <= mminus_cur and adx_filter > float(self.p.extra_high_level):
                buy_open = True
            sell_close = True
        if mplus_prev < mminus_prev:
            if mplus_cur >= mminus_cur and adx_filter > float(self.p.extra_high_level):
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = int(self.p.adx_period) * 3 + int(self.p.signal_bar) + 5
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        adx_value = float(self.indicator.adx[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long adx={adx_value:.4f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell adx={adx_value:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short adx={adx_value:.4f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy adx={adx_value:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy adx={adx_value:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell adx={adx_value:.4f}')
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
