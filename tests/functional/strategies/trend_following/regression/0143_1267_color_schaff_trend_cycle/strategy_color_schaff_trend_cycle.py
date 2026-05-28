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
    if price_mode in {'price_simpl', 'simpl'}:
        return (data.open + data.close) / 2.0
    if price_mode in {'price_quarter', 'quarter'}:
        return (data.high + data.low + data.open + data.close) / 4.0
    return data.close


class ColorSchaffTrendCycleIndicator(bt.Indicator):
    lines = ('value', 'color')
    params = dict(
        xma_method='ema',
        fast_xma=23,
        slow_xma=50,
        xphase=15,
        applied_price='price_close',
        cycle=10,
        high_level=60,
        low_level=-60,
    )

    def __init__(self):
        price_line = resolve_price_line(self.data, self.p.applied_price)
        ma_cls = resolve_ma_class(self.p.xma_method)
        self._fast = ma_cls(price_line, period=max(1, int(self.p.fast_xma)))
        self._slow = ma_cls(price_line, period=max(1, int(self.p.slow_xma)))
        self.addminperiod(max(int(self.p.fast_xma), int(self.p.slow_xma)) + int(self.p.cycle) * 2 + 5)

    def next(self):
        cycle = max(2, int(self.p.cycle))
        macd_vals = [float(self._fast[-i]) - float(self._slow[-i]) for i in range(cycle)]
        llv1 = min(macd_vals)
        hhv1 = max(macd_vals)
        prev_st = float(self.lines.value[-1]) if len(self) > 0 else 0.0
        if prev_st != prev_st:
            prev_st = 0.0
        cur_macd = macd_vals[0]
        st = ((cur_macd - llv1) / (hhv1 - llv1) * 100.0) if (hhv1 - llv1) != 0 else prev_st
        st = 0.5 * (st - prev_st) + prev_st if len(self) > 0 else st
        st_vals = [st]
        for i in range(1, cycle):
            value = float(self.lines.value[-i])
            if value == value:
                st_vals.append(value)
        llv2 = min(st_vals)
        hhv2 = max(st_vals)
        prev_stc = float(self.lines.value[-1]) if len(self) > 0 else 0.0
        if prev_stc != prev_stc:
            prev_stc = 0.0
        stc = ((st - llv2) / (hhv2 - llv2) * 200.0 - 100.0) if (hhv2 - llv2) != 0 else prev_stc
        stc = 0.5 * (stc - prev_stc) + prev_stc if len(self) > 0 else stc
        self.lines.value[0] = stc
        delta = stc - prev_stc if len(self) > 0 else 0.0
        color = 4
        if stc > 0:
            if stc > float(self.p.high_level):
                color = 7 if delta >= 0 else 6
            else:
                color = 5 if delta >= 0 else 4
        if stc < 0:
            if stc < float(self.p.low_level):
                color = 0 if delta < 0 else 1
            else:
                color = 2 if delta < 0 else 3
        self.lines.color[0] = color

    def once(self, start, end):
        fast_array = self._fast.array
        slow_array = self._slow.array
        value_line = self.lines.value.array
        color_line = self.lines.color.array
        for line in (value_line, color_line):
            while len(line) < end:
                line.append(float('nan'))

        cycle = max(2, int(self.p.cycle))
        prev_value = None
        actual_end = min(end, len(fast_array), len(slow_array))
        for i in range(start, actual_end):
            macd_vals = [
                float(fast_array[i - j]) - float(slow_array[i - j])
                for j in range(cycle)
                if i - j >= 0
            ]
            llv1 = min(macd_vals)
            hhv1 = max(macd_vals)
            prev_st = 0.0 if prev_value is None else prev_value
            cur_macd = macd_vals[0]
            st = ((cur_macd - llv1) / (hhv1 - llv1) * 100.0) if (hhv1 - llv1) != 0 else prev_st
            if prev_value is not None:
                st = 0.5 * (st - prev_st) + prev_st

            st_vals = [st]
            for j in range(1, cycle):
                idx = i - j
                if idx < start:
                    break
                st_vals.append(float(value_line[idx]))
            llv2 = min(st_vals)
            hhv2 = max(st_vals)
            prev_stc = 0.0 if prev_value is None else prev_value
            stc = ((st - llv2) / (hhv2 - llv2) * 200.0 - 100.0) if (hhv2 - llv2) != 0 else prev_stc
            if prev_value is not None:
                stc = 0.5 * (stc - prev_stc) + prev_stc

            delta = stc - prev_stc if prev_value is not None else 0.0
            color = 4
            if stc > 0:
                if stc > float(self.p.high_level):
                    color = 7 if delta >= 0 else 6
                else:
                    color = 5 if delta >= 0 else 4
            if stc < 0:
                if stc < float(self.p.low_level):
                    color = 0 if delta < 0 else 1
                else:
                    color = 2 if delta < 0 else 3
            value_line[i] = stc
            color_line[i] = color
            prev_value = stc


class ColorSchaffTrendCycleStrategy(bt.Strategy):
    params = dict(
        xma_method='ema',
        fast_xma=23,
        slow_xma=50,
        xphase=15,
        applied_price='price_close',
        cycle=10,
        high_level=60,
        low_level=-60,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = ColorSchaffTrendCycleIndicator(
            self.data,
            xma_method=self.p.xma_method,
            fast_xma=self.p.fast_xma,
            slow_xma=self.p.slow_xma,
            xphase=self.p.xphase,
            applied_price=self.p.applied_price,
            cycle=self.p.cycle,
            high_level=self.p.high_level,
            low_level=self.p.low_level,
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
        sig_cur = float(self.indicator.color[-shift + 1]) if shift > 1 else float(self.indicator.color[0])
        sig_prev = float(self.indicator.color[-shift])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if sig_prev > 6:
            if sig_cur >= 6:
                buy_open = True
            sell_close = True
        if sig_prev < 2:
            if sig_cur >= 2:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.fast_xma), int(self.p.slow_xma)) + int(self.p.cycle) * 2 + int(self.p.signal_bar) + 5
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        value = float(self.indicator.value[0])
        color = int(self.indicator.color[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long value={value:.4f} color={color}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell value={value:.4f} color={color}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short value={value:.4f} color={color}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy value={value:.4f} color={color}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy value={value:.4f} color={color}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell value={value:.4f} color={color}')
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
