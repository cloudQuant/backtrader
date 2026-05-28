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
    if mode in {'mode_sma', 'sma'}:
        return bt.indicators.SimpleMovingAverage
    if mode in {'mode_ema', 'ema', 'mode_jjma', 'jjma', 'mode_jurx', 'jurx', 'mode_parma', 'parma', 'mode_t3', 't3', 'mode_vidya', 'vidya', 'mode_ama', 'ama'}:
        return bt.indicators.ExponentialMovingAverage
    if mode in {'mode_smma', 'smma'}:
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
        return (2.0 * data.close + data.high + data.low) / 4.0
    if price_mode in {'price_simpl', 'simpl'}:
        return (data.open + data.close) / 2.0
    if price_mode in {'price_quarter', 'quarter'}:
        return (data.high + data.low + data.open + data.close) / 4.0
    return data.close


class TrendContinuationIndicator(bt.Indicator):
    lines = ('up', 'down')
    params = dict(nperiod=20, xmethod='t3', xperiod=5, xphase=61, ipc='price_close')

    def __init__(self):
        self._price = resolve_price_line(self.data, self.p.ipc)
        self._ma_cls = resolve_ma_class(self.p.xmethod)
        self.addminperiod(int(self.p.nperiod) + int(self.p.xperiod) + 5)

    def next(self):
        nperiod = max(2, int(self.p.nperiod))
        dprice = float(self._price[0]) - float(self._price[-1])
        positives = []
        negatives = []
        cf_p = []
        cf_n = []
        running_p = 0.0
        running_n = 0.0
        for i in range(nperiod):
            diff = float(self._price[-i]) - float(self._price[-i - 1])
            pos = -diff if diff > 0 else 0.0
            neg = diff if diff < 0 else 0.0
            running_p += pos
            running_n += neg
            positives.append(pos)
            negatives.append(neg)
            cf_p.append(running_p)
            cf_n.append(running_n)
        ch_p = sum(positives)
        ch_n = sum(negatives)
        cff_p = sum(cf_p)
        cff_n = sum(cf_n)
        k_p = ch_p - cff_n
        k_n = ch_n - cff_p
        period = max(1, int(self.p.xperiod))
        alpha = 2.0 / (period + 1.0)
        prev_up = float(self.lines.up[-1]) if len(self) > 0 else k_p
        prev_dn = float(self.lines.down[-1]) if len(self) > 0 else k_n
        self.lines.up[0] = alpha * k_p + (1.0 - alpha) * prev_up if len(self) > 0 else k_p
        self.lines.down[0] = alpha * k_n + (1.0 - alpha) * prev_dn if len(self) > 0 else k_n


class TrendContinuationStrategy(bt.Strategy):
    params = dict(
        nperiod=20,
        xmethod='t3',
        xperiod=5,
        xphase=61,
        ipc='price_close',
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        price = resolve_price_line(self.data, self.p.ipc)
        momentum = price - price(-1)
        up_raw = bt.If(momentum > 0.0, momentum, 0.0)
        down_raw = bt.If(momentum < 0.0, -momentum, 0.0)
        self.indicator = type('TrendContinuationLines', (), {})()
        self.indicator.up = bt.indicators.ExponentialMovingAverage(up_raw, period=max(1, int(self.p.xperiod)))
        self.indicator.down = bt.indicators.ExponentialMovingAverage(down_raw, period=max(1, int(self.p.xperiod)))
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
        up_prev = float(self.indicator.up[-shift])
        dn_prev = float(self.indicator.down[-shift])
        up_cur = float(self.indicator.up[-shift + 1]) if shift > 1 else float(self.indicator.up[0])
        dn_cur = float(self.indicator.down[-shift + 1]) if shift > 1 else float(self.indicator.down[0])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if up_prev < dn_prev:
            if up_cur >= dn_cur:
                buy_open = True
            sell_close = True
        if up_prev > dn_prev:
            if up_cur <= dn_cur:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = int(self.p.nperiod) + int(self.p.xperiod) + int(self.p.signal_bar) + 5
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        up = float(self.indicator.up[0])
        down = float(self.indicator.down[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long up={up:.6f} down={down:.6f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell up={up:.6f} down={down:.6f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short up={up:.6f} down={down:.6f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy up={up:.6f} down={down:.6f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy up={up:.6f} down={down:.6f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell up={up:.6f} down={down:.6f}')
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
