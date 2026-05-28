from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import backtrader.feeds as btfeeds
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def resample_ohlcv(df, minutes):
    rule = f'{int(minutes)}min'
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
        'spread': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close']).copy()
    out['openinterest'] = out['openinterest'].fillna(0)
    out['spread'] = out['spread'].fillna(0)
    return out


def build_pm(ftma, rank1, rank2, rank3, shift1, shift2, shift3):
    pm = []
    total = 0.0
    for h in range(int(ftma)):
        value = shift1 + math.pow(h / (ftma - 1.0), rank1) * (1.0 - shift1)
        value = (shift2 + math.pow(1.0 - (h / (ftma - 1.0)), rank2) * (1.0 - shift2)) * value
        if (h / (ftma - 1.0)) < 0.5:
            value = (shift3 + math.pow(1.0 - (h / (ftma - 1.0)) * 2.0, rank3) * (1.0 - shift3)) * value
        else:
            value = (shift3 + math.pow((h / (ftma - 1.0)) * 2.0 - 1.0, rank3) * (1.0 - shift3)) * value
        pm.append(value)
        total += value
    return [value / total for value in pm]


def weighted_series(values, weights):
    window = len(weights)
    out = [math.nan] * len(values)
    for idx in range(window - 1, len(values)):
        acc = 0.0
        for offset, weight in enumerate(weights):
            acc += weight * values[idx - offset]
        out[idx] = acc
    return out


def build_signal_frame(df, execution_minutes, ftma, rank1, rank2, rank3, shift1, shift2, shift3, gap_points, signal_bar):
    frame = resample_ohlcv(df, execution_minutes)
    weights = build_pm(ftma, rank1, rank2, rank3, shift1, shift2, shift3)
    wopen = weighted_series(frame['open'].tolist(), weights)
    whigh_raw = weighted_series(frame['high'].tolist(), weights)
    wlow_raw = weighted_series(frame['low'].tolist(), weights)
    wclose = weighted_series(frame['close'].tolist(), weights)
    gap = float(gap_points)
    o_buf, h_buf, l_buf, c_buf, color = [], [], [], [], []
    prev_close = math.nan
    for idx in range(len(frame)):
        o = wopen[idx]
        h = whigh_raw[idx]
        l = wlow_raw[idx]
        c = wclose[idx]
        if math.isnan(o) or math.isnan(h) or math.isnan(l) or math.isnan(c):
            o_buf.append(math.nan)
            h_buf.append(math.nan)
            l_buf.append(math.nan)
            c_buf.append(math.nan)
            color.append(math.nan)
            continue
        max_v = max(o, c, h, l)
        min_v = min(o, c, h, l)
        if not math.isnan(prev_close) and abs(frame['open'].iloc[idx] - frame['close'].iloc[idx]) <= gap:
            o = prev_close
        o_buf.append(o)
        h_buf.append(max_v)
        l_buf.append(min_v)
        c_buf.append(c)
        prev_close = c
        if o < c:
            color.append(2.0)
        elif o > c:
            color.append(0.0)
        else:
            color.append(1.0)
    frame['ft_open'] = o_buf
    frame['ft_high'] = h_buf
    frame['ft_low'] = l_buf
    frame['ft_close'] = c_buf
    frame['color'] = color
    frame = frame.dropna(subset=['ft_open', 'ft_close', 'color']).copy()
    colors = frame['color'].tolist()
    buy_open = [False] * len(frame)
    sell_open = [False] * len(frame)
    buy_close = [False] * len(frame)
    sell_close = [False] * len(frame)
    sb = int(signal_bar)
    for idx in range(sb + 1, len(frame)):
        older = colors[idx - (sb + 1)]
        newer = colors[idx - sb]
        if older == 2.0 and newer < 2.0:
            buy_open[idx] = True
            sell_close[idx] = True
        if older == 0.0 and newer > 0.0:
            sell_open[idx] = True
            buy_close[idx] = True
    frame['buy_open'] = buy_open
    frame['sell_open'] = sell_open
    frame['buy_close'] = buy_close
    frame['sell_close'] = sell_close
    return frame[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread', 'buy_open', 'sell_open', 'buy_close', 'sell_close']]


class Mt5PandasFeed(btfeeds.PandasData):
    lines = ('spread', 'buy_open', 'sell_open', 'buy_close', 'sell_close')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6), ('buy_open', 7), ('sell_open', 8), ('buy_close', 9), ('sell_close', 10),
    )


class FineTuningMacandleStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stoploss_pips=1000,
        takeprofit_pips=2000,
        ftma=10,
        rank1=2.0,
        rank2=2.0,
        rank3=2.0,
        shift1=1.0,
        shift2=1.0,
        shift3=1.0,
        gap_points=10,
        signal_bar=1,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_reverse = None
        self.active_side = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.last_bar_dt = None

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _new_bar(self):
        current = bt.num2date(self.data0_feed.datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _cancel_exits(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _place_exits(self):
        if not self.position:
            return
        size = abs(self.position.size)
        stop_distance = self.p.stoploss_pips * self.p.point_size
        take_distance = self.p.takeprofit_pips * self.p.point_size
        if self.position.size > 0:
            self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.position.price - stop_distance)
            self.limit_order = self.sell(size=size, exectype=bt.Order.Limit, price=self.position.price + take_distance, oco=self.stop_order)
        else:
            self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.position.price + stop_distance)
            self.limit_order = self.buy(size=size, exectype=bt.Order.Limit, price=self.position.price - take_distance, oco=self.stop_order)

    def _submit_entry(self, side, reason):
        if self.position or self.entry_order is not None or self.close_order is not None:
            return
        size = max(0.01, float(self.p.fixed_lot))
        self.entry_order = self.buy(size=size) if side == 'long' else self.sell(size=size)
        self.log(f'OPEN {side.upper()} size={size} reason={reason}')

    def _submit_close(self, reason, reverse=None):
        if not self.position or self.close_order is not None:
            return
        self.pending_reverse = reverse
        self._cancel_exits()
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason} reverse={reverse}')

    def next(self):
        self.bar_num += 1
        if len(self.data0_feed) < 5:
            return
        if not self._new_bar():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        buy_open = bool(self.data0_feed.buy_open[0])
        sell_open = bool(self.data0_feed.sell_open[0])
        buy_close = bool(self.data0_feed.buy_close[0])
        sell_close = bool(self.data0_feed.sell_close[0])
        if self.position.size > 0 and buy_close:
            self._submit_close('indicator sell/close signal', reverse='short' if sell_open else None)
            return
        if self.position.size < 0 and sell_close:
            self._submit_close('indicator buy/close signal', reverse='long' if buy_open else None)
            return
        if not self.position:
            if buy_open:
                self._submit_entry('long', 'fine tuning candle bullish transition')
            elif sell_open:
                self._submit_entry('short', 'fine tuning candle bearish transition')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                if order.executed.size > 0:
                    self.buy_count += 1
                else:
                    self.sell_count += 1
                self.entry_order = None
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self._place_exits()
            elif order == self.close_order:
                self.close_order = None
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
                reverse = self.pending_reverse
                self.pending_reverse = None
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                if reverse is not None and not self.position:
                    self._submit_entry(reverse, 'reverse after close')
            elif order == self.stop_order:
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
            elif order == self.limit_order:
                self.limit_order = None
                self.stop_order = None
                self.active_side = None
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None
                self.pending_reverse = None
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
