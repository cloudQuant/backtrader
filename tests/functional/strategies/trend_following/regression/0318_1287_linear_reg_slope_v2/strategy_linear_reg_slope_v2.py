from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from collections import deque
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


class LinearRegSlopeV2Indicator(bt.Indicator):
    lines = ('reg_slope', 'trigger',)
    params = dict(
        sl_method='sma',
        sl_length=12,
        sl_phase=15,
        ipc='price_close',
        trigger_shift=1,
    )

    def __init__(self):
        ma_cls = resolve_ma_class(self.p.sl_method)
        price_line = resolve_price_line(self.data, self.p.ipc)
        self.smooth = ma_cls(price_line, period=self.p.sl_length)
        self._window = deque(maxlen=self.p.sl_length)
        self._sum_x = self.p.sl_length * (self.p.sl_length - 1) * 0.5
        sum_x_sqr = (self.p.sl_length - 1.0) * self.p.sl_length * (2.0 * self.p.sl_length - 1.0) / 6.0
        self._divisor = self._sum_x * self._sum_x - self.p.sl_length * sum_x_sqr
        if self.p.trigger_shift > self.p.sl_length - 2:
            self._trig_shift = 1
            self._trig_shift_back = self.p.sl_length - 2
        else:
            self._trig_shift = self.p.sl_length - 1 - self.p.trigger_shift
            self._trig_shift_back = self.p.trigger_shift
        self.addminperiod(self.p.sl_length + self.p.trigger_shift + 3)

    def next(self):
        self._window.appendleft(float(self.smooth[0]))
        if len(self._window) < self.p.sl_length:
            self.lines.reg_slope[0] = float('nan')
            self.lines.trigger[0] = float('nan')
            return
        sum_y = sum(self._window[i] for i in range(self.p.sl_length))
        sum_xy = sum(i * self._window[i] for i in range(self.p.sl_length))
        slope = (self.p.sl_length * sum_xy - self._sum_x * sum_y) / self._divisor if self._divisor else float('nan')
        intercept = (sum_y - slope * self._sum_x) / self.p.sl_length
        reg_value = intercept + slope * self._trig_shift
        self.lines.reg_slope[0] = reg_value
        if len(self) > self._trig_shift_back and not pd.isna(self.lines.reg_slope[-self._trig_shift_back]):
            self.lines.trigger[0] = 2.0 * reg_value - float(self.lines.reg_slope[-self._trig_shift_back])
        else:
            self.lines.trigger[0] = float('nan')


class LinearRegSlopeV2Strategy(bt.Strategy):
    params = dict(
        sl_method='sma',
        sl_length=12,
        sl_phase=15,
        ipc='price_close',
        trigger_shift=1,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = LinearRegSlopeV2Indicator(
            self.data,
            sl_method=self.p.sl_method,
            sl_length=self.p.sl_length,
            sl_phase=self.p.sl_phase,
            ipc=self.p.ipc,
            trigger_shift=self.p.trigger_shift,
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
        dn_prev = float(self.indicator.reg_slope[-shift - 1])
        up_prev = float(self.indicator.trigger[-shift - 1])
        dn_cur = float(self.indicator.reg_slope[-shift])
        up_cur = float(self.indicator.trigger[-shift])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if up_prev > dn_prev:
            if up_cur <= dn_cur:
                buy_open = True
            sell_close = True
        if dn_prev > up_prev:
            if dn_cur <= up_cur:
                sell_open = True
            buy_close = True
        if buy_open and sell_open:
            return False, False, False, False
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = int(self.p.sl_length) + int(self.p.signal_bar) + int(self.p.trigger_shift) + 5
        if len(self.data) < warmup:
            return
        if pd.isna(float(self.indicator.reg_slope[0])) or pd.isna(float(self.indicator.trigger[0])):
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        reg_value = float(self.indicator.reg_slope[0])
        trigger_value = float(self.indicator.trigger[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long reg={reg_value:.4f} trig={trigger_value:.4f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell reg={reg_value:.4f} trig={trigger_value:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short reg={reg_value:.4f} trig={trigger_value:.4f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy reg={reg_value:.4f} trig={trigger_value:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy reg={reg_value:.4f} trig={trigger_value:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell reg={reg_value:.4f} trig={trigger_value:.4f}')
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
