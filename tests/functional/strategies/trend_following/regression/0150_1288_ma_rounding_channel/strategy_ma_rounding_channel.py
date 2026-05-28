from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
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
    if price_mode in {'price_simpl', 'simpl'}:
        return (data.open + data.close) / 2.0
    if price_mode in {'price_quarter', 'quarter'}:
        return (data.high + data.low + data.open + data.close) / 4.0
    if price_mode in {'price_trendfollow0', 'trendfollow0'}:
        return (data.high + data.low + data.close + data.close) / 4.0
    if price_mode in {'price_trendfollow1', 'trendfollow1'}:
        return (data.high + data.low + data.open + data.close + data.close) / 5.0
    return data.close


class MARoundingChannelIndicator(bt.Indicator):
    lines = ('base', 'upper', 'lower',)
    params = dict(
        xma_method='sma',
        xlength=12,
        xphase=15,
        ipc='price_close',
        ma_round=500,
        atr_period=12,
        atr_factor=1.0,
        chan_continuity=False,
    )

    def __init__(self):
        ma_cls = resolve_ma_class(self.p.xma_method)
        price_line = resolve_price_line(self.data, self.p.ipc)
        self.ma = ma_cls(price_line, period=self.p.xlength)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self._ma_ro = None
        self._prev_ma = None
        self._prev_dir = 0
        self._prev_range = 0.0
        self._prev_base = None
        self._prev_prev_base = None
        self._prev_upper = 0.0
        self._prev_lower = 0.0
        self.addminperiod(max(self.p.xlength, self.p.atr_period) + 3)

    def next(self):
        if self._ma_ro is None:
            self._ma_ro = float(self.data.close[0]) * 0.0 + self.data._dataname['close'].iloc[0] * 0.0 if False else None
        ma_ro = float(getattr(self.data, '_compression', 0) or 0)
        if not ma_ro:
            point = 0.01 if abs(float(self.data.close[0])) >= 1 else 0.0001
            ma_ro = point * float(self.p.ma_round)
        mov_ave0 = float(self.ma[0])
        if self._prev_ma is None:
            self._prev_ma = mov_ave0
        res1 = self._prev_base if self._prev_base is not None else mov_ave0
        if (
            mov_ave0 > self._prev_ma + ma_ro
            or mov_ave0 < self._prev_ma - ma_ro
            or mov_ave0 > res1 + ma_ro
            or mov_ave0 < res1 - ma_ro
            or (mov_ave0 > res1 and self._prev_dir == 1)
            or (mov_ave0 < res1 and self._prev_dir == -1)
        ):
            base = mov_ave0
        else:
            base = res1
        direction = 0
        if base < res1:
            direction = -1
        elif base > res1:
            direction = 1
        else:
            direction = self._prev_dir
        upper = 0.0
        lower = 0.0
        range0 = self._prev_range
        if base == res1:
            if self._prev_prev_base is None or res1 != self._prev_prev_base:
                range0 = float(self.atr[0]) * float(self.p.atr_factor)
            upper = base + range0
            lower = base - range0
        elif self.p.chan_continuity:
            upper = self._prev_upper
            lower = self._prev_lower
        self.lines.base[0] = base
        self.lines.upper[0] = upper
        self.lines.lower[0] = lower
        self._prev_dir = direction
        self._prev_ma = mov_ave0
        self._prev_range = range0
        self._prev_prev_base = self._prev_base
        self._prev_base = base
        self._prev_upper = upper
        self._prev_lower = lower


class MARoundingChannelStrategy(bt.Strategy):
    params = dict(
        xma_method='sma',
        xlength=12,
        xphase=15,
        ipc='price_close',
        ma_round=500,
        atr_period=12,
        atr_factor=1.0,
        chan_continuity=False,
        signal_bar=1,
        lot=0.1,
        lookback_search=200,
    )

    def __init__(self):
        self.channel = MARoundingChannelIndicator(
            self.data,
            xma_method=self.p.xma_method,
            xlength=self.p.xlength,
            xphase=self.p.xphase,
            ipc=self.p.ipc,
            ma_round=self.p.ma_round,
            atr_period=self.p.atr_period,
            atr_factor=self.p.atr_factor,
            chan_continuity=self.p.chan_continuity,
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

    @staticmethod
    def _value(line, idx):
        value = float(line[idx])
        return 0.0 if math.isnan(value) else value

    def _latest_channel(self, start_shift):
        max_bars = min(len(self.data) - 1, int(self.p.lookback_search))
        for shift in range(start_shift, max_bars):
            upper = self._value(self.channel.upper, -shift)
            lower = self._value(self.channel.lower, -shift)
            if upper and lower:
                return upper, lower
        return 0.0, 0.0

    def _signals(self):
        shift = max(1, int(self.p.signal_bar))
        close_value = self._value(self.data.close, -shift)
        upper = self._value(self.channel.upper, -shift)
        lower = self._value(self.channel.lower, -shift)
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if upper and lower:
            if close_value > upper:
                buy_open = True
                sell_close = True
            if close_value < lower:
                sell_open = True
                buy_close = True
            return buy_open, sell_open, buy_close, sell_close
        latest_upper, latest_lower = self._latest_channel(shift + 1)
        if latest_upper and close_value > latest_upper:
            sell_close = True
        if latest_lower and close_value < latest_lower:
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.xlength), int(self.p.atr_period)) + int(self.p.signal_bar) + 5
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        channel_upper = self._value(self.channel.upper, 0)
        channel_lower = self._value(self.channel.lower, 0)
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long upper={channel_upper:.4f} lower={channel_lower:.4f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell upper={channel_upper:.4f} lower={channel_lower:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short upper={channel_upper:.4f} lower={channel_lower:.4f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy upper={channel_upper:.4f} lower={channel_lower:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy upper={channel_upper:.4f} lower={channel_lower:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell upper={channel_upper:.4f} lower={channel_lower:.4f}')
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
