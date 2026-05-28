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
        return (data.high + data.low + data.close + data.close) / 4.0
    if price_mode in {'price_simple', 'simple'}:
        return (data.open + data.close) / 2.0
    if price_mode in {'price_quarter', 'quarter'}:
        return (data.high + data.low + data.open + data.close) / 4.0
    return data.close


class ADXCrossHullStyleIndicator(bt.Indicator):
    lines = ('up', 'down')
    params = dict(adx_period=14)

    def __init__(self):
        period = max(2, int(self.p.adx_period))
        self._plus1 = bt.indicators.PlusDirectionalIndicator(self.data, period=period)
        self._plus2 = bt.indicators.PlusDirectionalIndicator(self.data, period=max(2, period // 2))
        self._minus1 = bt.indicators.MinusDirectionalIndicator(self.data, period=period)
        self._minus2 = bt.indicators.MinusDirectionalIndicator(self.data, period=max(2, period // 2))
        self._atr = bt.indicators.AverageTrueRange(self.data, period=10)
        self.addminperiod(period + 12)

    def next(self):
        b4plusdi = 2.0 * float(self._plus2[-1]) - float(self._plus1[-1])
        nowplusdi = 2.0 * float(self._plus2[0]) - float(self._plus1[0])
        b4minusdi = 2.0 * float(self._minus2[-1]) - float(self._minus1[-1])
        nowminusdi = 2.0 * float(self._minus2[0]) - float(self._minus1[0])
        self.lines.up[0] = 0.0
        self.lines.down[0] = 0.0
        if b4plusdi < b4minusdi and nowplusdi > nowminusdi:
            self.lines.up[0] = float(self.data.low[0]) - 0.25 * float(self._atr[0])
        if b4plusdi > b4minusdi and nowplusdi < nowminusdi:
            self.lines.down[0] = float(self.data.high[0]) + 0.25 * float(self._atr[0])

    def once(self, start, end):
        plus1 = self._plus1.array
        plus2 = self._plus2.array
        minus1 = self._minus1.array
        minus2 = self._minus2.array
        atr = self._atr.array
        low = self.data.low.array
        high = self.data.high.array
        up_line = self.lines.up.array
        down_line = self.lines.down.array
        for line in (up_line, down_line):
            while len(line) < end:
                line.append(float('nan'))

        actual_end = min(end, len(plus1), len(plus2), len(minus1), len(minus2), len(atr), len(low), len(high))
        for i in range(start, actual_end):
            up_line[i] = 0.0
            down_line[i] = 0.0
            if i <= 0:
                continue
            b4plusdi = 2.0 * float(plus2[i - 1]) - float(plus1[i - 1])
            nowplusdi = 2.0 * float(plus2[i]) - float(plus1[i])
            b4minusdi = 2.0 * float(minus2[i - 1]) - float(minus1[i - 1])
            nowminusdi = 2.0 * float(minus2[i]) - float(minus1[i])
            if b4plusdi < b4minusdi and nowplusdi > nowminusdi:
                up_line[i] = float(low[i]) - 0.25 * float(atr[i])
            if b4plusdi > b4minusdi and nowplusdi < nowminusdi:
                down_line[i] = float(high[i]) + 0.25 * float(atr[i])


class UltraXMAIndicator(bt.Indicator):
    lines = ('bulls', 'bears')
    params = dict(
        w_method='jjma',
        start_length=3,
        wphase=100,
        step=5,
        steps_total=10,
        smooth_method='jjma',
        smooth_length=3,
        smooth_phase=100,
        ipc='price_close',
    )

    def __init__(self):
        price_line = resolve_price_line(self.data, self.p.ipc)
        ma_cls = resolve_ma_class(self.p.w_method)
        smooth_cls = resolve_ma_class(self.p.smooth_method)
        self._periods = [int(self.p.start_length + i * self.p.step) for i in range(int(self.p.steps_total) + 1)]
        self._ma_lines = [ma_cls(price_line, period=max(1, p)) for p in self._periods]
        self._bull_smooth = smooth_cls(self.lines.bulls, period=max(1, int(self.p.smooth_length)))
        self._bear_smooth = smooth_cls(self.lines.bears, period=max(1, int(self.p.smooth_length)))
        self.addminperiod(max(self._periods) + int(self.p.smooth_length) + 5)

    def next(self):
        upsch = 0.0
        dnsch = 0.0
        for ma_line in self._ma_lines:
            if float(ma_line[0]) > float(ma_line[-1]):
                upsch += 1.0
            else:
                dnsch += 1.0
        period = max(1, int(self.p.smooth_length))
        alpha = 2.0 / (period + 1.0)
        prev_bulls = float(self.lines.bulls[-1]) if len(self) > 0 else upsch
        prev_bears = float(self.lines.bears[-1]) if len(self) > 0 else dnsch
        if prev_bulls != prev_bulls:
            prev_bulls = upsch
        if prev_bears != prev_bears:
            prev_bears = dnsch
        self.lines.bulls[0] = alpha * upsch + (1.0 - alpha) * prev_bulls if len(self) > 0 else upsch
        self.lines.bears[0] = alpha * dnsch + (1.0 - alpha) * prev_bears if len(self) > 0 else dnsch

    def once(self, start, end):
        ma_arrays = [ma_line.array for ma_line in self._ma_lines]
        bulls_line = self.lines.bulls.array
        bears_line = self.lines.bears.array
        for line in (bulls_line, bears_line):
            while len(line) < end:
                line.append(float('nan'))

        period = max(1, int(self.p.smooth_length))
        alpha = 2.0 / (period + 1.0)
        prev_bulls = None
        prev_bears = None
        actual_end = min([end] + [len(array) for array in ma_arrays])
        for i in range(start, actual_end):
            upsch = 0.0
            dnsch = 0.0
            for ma_array in ma_arrays:
                if i > 0 and float(ma_array[i]) > float(ma_array[i - 1]):
                    upsch += 1.0
                else:
                    dnsch += 1.0
            bulls = upsch if prev_bulls is None else alpha * upsch + (1.0 - alpha) * prev_bulls
            bears = dnsch if prev_bears is None else alpha * dnsch + (1.0 - alpha) * prev_bears
            bulls_line[i] = bulls
            bears_line[i] = bears
            prev_bulls = bulls
            prev_bears = bears


class ADXCrossHullStyleStrategy(bt.Strategy):
    params = dict(
        adx_period=14,
        w_method='jjma',
        start_length=3,
        wphase=100,
        n_step=5,
        n_steps_total=10,
        smooth_method='jjma',
        smooth_length=3,
        smooth_phase=100,
        ipc='price_close',
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.cross = ADXCrossHullStyleIndicator(self.data, adx_period=self.p.adx_period)
        self.ultra = UltraXMAIndicator(
            self.data,
            w_method=self.p.w_method,
            start_length=self.p.start_length,
            wphase=self.p.wphase,
            step=self.p.n_step,
            steps_total=self.p.n_steps_total,
            smooth_method=self.p.smooth_method,
            smooth_length=self.p.smooth_length,
            smooth_phase=self.p.smooth_phase,
            ipc=self.p.ipc,
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

    def _has_recent_signal(self, line, shift, limit=80):
        start = max(shift + 1, 1)
        max_lookback = min(len(self.data) - 1, start + limit)
        for bar in range(start, max_lookback):
            value = float(line[-bar])
            if value != 0.0:
                return True
        return False

    def _signals(self):
        shift = max(1, int(self.p.signal_bar))
        up_value = float(self.cross.up[-shift])
        dn_value = float(self.cross.down[-shift])
        up_uxma = float(self.ultra.bulls[-shift])
        dn_uxma = float(self.ultra.bears[-shift])
        buy_open = bool(up_value != 0.0)
        sell_open = bool(dn_value != 0.0)
        buy_close = sell_open
        sell_close = buy_open
        if up_uxma < dn_uxma:
            buy_open = False
            buy_close = True
        if up_uxma > dn_uxma:
            sell_open = False
            sell_close = True
        if not buy_close and not sell_close:
            if self.position.size < 0 and self._has_recent_signal(self.cross.up, shift):
                sell_close = True
            if self.position.size > 0 and self._has_recent_signal(self.cross.down, shift):
                buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.adx_period) + 12, int(self.p.start_length + self.p.n_step * self.p.n_steps_total) + int(self.p.smooth_length) + 5) + int(self.p.signal_bar)
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        bulls = float(self.ultra.bulls[0])
        bears = float(self.ultra.bears[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long bulls={bulls:.2f} bears={bears:.2f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell bulls={bulls:.2f} bears={bears:.2f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short bulls={bulls:.2f} bears={bears:.2f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy bulls={bulls:.2f} bears={bears:.2f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy bulls={bulls:.2f} bears={bears:.2f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell bulls={bulls:.2f} bears={bears:.2f}')
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
