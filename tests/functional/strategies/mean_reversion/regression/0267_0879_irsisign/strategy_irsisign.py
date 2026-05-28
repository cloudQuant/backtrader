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
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


def _applied_price(data, price_type, ago=0):
    o = float(data.open[-ago])
    h = float(data.high[-ago])
    l = float(data.low[-ago])
    c = float(data.close[-ago])
    if price_type == 0:
        return c
    if price_type == 1:
        return o
    if price_type == 2:
        return h
    if price_type == 3:
        return l
    if price_type == 4:
        return (h + l) / 2.0
    if price_type == 5:
        return (h + l + c) / 3.0
    if price_type == 6:
        return (h + l + c + c) / 4.0
    return c


class IRSISignIndicator(bt.Indicator):
    lines = ('sell', 'buy', 'rsi', 'atr')
    params = dict(atr_period=14, rsi_period=14, rsi_price=0, up_level=70, dn_level=30)

    def __init__(self):
        self._atr = bt.indicators.ATR(self.data, period=int(self.p.atr_period))
        self.addminperiod(max(int(self.p.atr_period), int(self.p.rsi_period)) + 2)

    def _calc_rsi(self):
        period = int(self.p.rsi_period)
        gains = []
        losses = []
        for i in range(period):
            p0 = _applied_price(self.data, int(self.p.rsi_price), i)
            p1 = _applied_price(self.data, int(self.p.rsi_price), i + 1)
            delta = p0 - p1
            gains.append(max(delta, 0.0))
            losses.append(max(-delta, 0.0))
        avg_gain = sum(gains) / period if period else 0.0
        avg_loss = sum(losses) / period if period else 0.0
        if avg_loss == 0.0:
            return 100.0 if avg_gain > 0.0 else 50.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def next(self):
        self.lines.sell[0] = float('nan')
        self.lines.buy[0] = float('nan')
        rsi_now = self._calc_rsi()
        self.lines.rsi[0] = rsi_now
        self.lines.atr[0] = float(self._atr[0])

        if len(self) < 2:
            return

        rsi_prev = float(self.lines.rsi[-1])
        atr_now = float(self._atr[0])
        low_now = float(self.data.low[0])
        high_now = float(self.data.high[0])

        if rsi_now > float(self.p.dn_level) and rsi_prev <= float(self.p.dn_level):
            self.lines.buy[0] = low_now - atr_now * 3.0 / 8.0
        if rsi_now < float(self.p.up_level) and rsi_prev >= float(self.p.up_level):
            self.lines.sell[0] = high_now + atr_now * 3.0 / 8.0


class ExpIRSISignStrategy(bt.Strategy):
    params = dict(
        atr_period=14,
        rsi_period=14,
        rsi_price=0,
        up_level=70,
        dn_level=30,
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        fixed_lot=0.1,
        point=0.0001,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=60,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.indicator = IRSISignIndicator(
            self.signal_data,
            atr_period=self.p.atr_period,
            rsi_period=self.p.rsi_period,
            rsi_price=self.p.rsi_price,
            up_level=self.p.up_level,
            dn_level=self.p.dn_level,
        )
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._last_signal_len = 0

    def log(self, text):
        print(f'{bt.num2date(self.base.datetime[0]).isoformat()}, {text}')

    def _check_exit_levels(self):
        if not self.position:
            return False
        close_price = float(self.base.close[0])
        point_value = float(self.p.point)
        stop_dist = self.p.stop_loss_points * point_value if self.p.stop_loss_points > 0 else None
        take_dist = self.p.take_profit_points * point_value if self.p.take_profit_points > 0 else None
        entry_price = float(self.position.price)
        if self.position.size > 0:
            if stop_dist and close_price <= entry_price - stop_dist:
                self.log(f'close long SL {close_price:.5f}')
                self.close()
                return True
            if take_dist and close_price >= entry_price + take_dist:
                self.log(f'close long TP {close_price:.5f}')
                self.close()
                return True
        else:
            if stop_dist and close_price >= entry_price + stop_dist:
                self.log(f'close short SL {close_price:.5f}')
                self.close()
                return True
            if take_dist and close_price <= entry_price - take_dist:
                self.log(f'close short TP {close_price:.5f}')
                self.close()
                return True
        return False

    def _line_value(self, line, offset):
        val = float(line[-offset]) if offset else float(line[0])
        return None if math.isnan(val) else val

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return
        if self._check_exit_levels():
            return

        signal_bar = max(int(self.p.signal_bar) - 1, 0)
        min_needed = max(int(self.p.atr_period), int(self.p.rsi_period)) + signal_bar + 4
        if len(self.signal_data) < min_needed:
            return
        current_signal_len = len(self.signal_data)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        up_signal = self._line_value(self.indicator.buy, signal_bar)
        dn_signal = self._line_value(self.indicator.sell, signal_bar)
        close_long = False
        close_short = False

        for bar in range(signal_bar + 1, len(self.signal_data)):
            if self.p.sell_pos_close and self._line_value(self.indicator.buy, bar) is not None:
                close_short = True
                break
        for bar in range(signal_bar + 1, len(self.signal_data)):
            if self.p.buy_pos_close and self._line_value(self.indicator.sell, bar) is not None:
                close_long = True
                break

        buy_open = up_signal is not None and self.p.buy_pos_open
        sell_open = dn_signal is not None and self.p.sell_pos_open
        if up_signal is not None and self.p.sell_pos_close:
            close_short = True
        if dn_signal is not None and self.p.buy_pos_close:
            close_long = True

        close_price = float(self.base.close[0])
        size = float(self.p.fixed_lot)
        if size <= 0:
            return

        if close_short and self.position.size < 0:
            self.log(f'close short signal {close_price:.5f}')
            self.close()
        if close_long and self.position.size > 0:
            self.log(f'close long signal {close_price:.5f}')
            self.close()
        if buy_open:
            self.signal_count += 1
            self.log(f'buy signal {close_price:.5f}')
            if self.position.size <= 0:
                self.buy(size=size)
        if sell_open:
            self.signal_count += 1
            self.log(f'sell signal {close_price:.5f}')
            if self.position.size >= 0:
                self.sell(size=size)

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
