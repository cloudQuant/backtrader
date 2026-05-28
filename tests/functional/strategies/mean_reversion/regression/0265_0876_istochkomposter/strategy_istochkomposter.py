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
    df = df.rename(columns={'<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest'})
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
    params = (('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5))


class IStochKomposterIndicator(bt.Indicator):
    lines = ('sell', 'buy', 'sto', 'atr')
    params = dict(atr_period=14, k_period=5, d_period=3, slowing=3, up_level=70, dn_level=30)

    def __init__(self):
        self._atr = bt.indicators.ATR(self.data, period=int(self.p.atr_period))
        self.addminperiod(max(int(self.p.atr_period), int(self.p.k_period) + int(self.p.d_period) + int(self.p.slowing) + 1) + 2)

    def _raw_k(self, ago):
        period = int(self.p.k_period)
        highs = [float(self.data.high[-(ago + i)]) for i in range(period)]
        lows = [float(self.data.low[-(ago + i)]) for i in range(period)]
        hh = max(highs)
        ll = min(lows)
        cp = float(self.data.close[-ago])
        if hh == ll:
            return 50.0
        return 100.0 * (cp - ll) / (hh - ll)

    def _main_stochastic(self):
        slowing = int(self.p.slowing)
        vals = [self._raw_k(i) for i in range(slowing)]
        return sum(vals) / len(vals)

    def next(self):
        self.lines.sell[0] = float('nan')
        self.lines.buy[0] = float('nan')
        sto_now = self._main_stochastic()
        self.lines.sto[0] = sto_now
        self.lines.atr[0] = float(self._atr[0])
        if len(self) < 2:
            return
        sto_prev = float(self.lines.sto[-1])
        atr_now = float(self._atr[0])
        if sto_now > float(self.p.dn_level) and sto_prev <= float(self.p.dn_level):
            self.lines.buy[0] = float(self.data.low[0]) - atr_now * 3.0 / 8.0
        if sto_now < float(self.p.up_level) and sto_prev >= float(self.p.up_level):
            self.lines.sell[0] = float(self.data.high[0]) + atr_now * 3.0 / 8.0


class ExpIStochKomposterStrategy(bt.Strategy):
    params = dict(
        atr_period=14,
        k_period=5,
        d_period=3,
        slowing=3,
        up_level=70,
        dn_level=30,
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        fixed_lot=0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=60,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.indicator = IStochKomposterIndicator(self.signal_data, atr_period=self.p.atr_period, k_period=self.p.k_period, d_period=self.p.d_period, slowing=self.p.slowing, up_level=self.p.up_level, dn_level=self.p.dn_level)
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
        cp = float(self.base.close[0])
        pv = float(self.p.point)
        sd = self.p.stop_loss_points * pv if self.p.stop_loss_points > 0 else None
        td = self.p.take_profit_points * pv if self.p.take_profit_points > 0 else None
        ep = float(self.position.price)
        if self.position.size > 0:
            if sd and cp <= ep - sd:
                self.log(f'close long SL {cp:.2f}')
                self.close()
                return True
            if td and cp >= ep + td:
                self.log(f'close long TP {cp:.2f}')
                self.close()
                return True
        else:
            if sd and cp >= ep + sd:
                self.log(f'close short SL {cp:.2f}')
                self.close()
                return True
            if td and cp <= ep - td:
                self.log(f'close short TP {cp:.2f}')
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
        min_needed = max(int(self.p.atr_period), int(self.p.k_period) + int(self.p.d_period) + int(self.p.slowing) + 1) + signal_bar + 4
        if len(self.signal_data) < min_needed:
            return
        csl = len(self.signal_data)
        if csl == self._last_signal_len:
            return
        self._last_signal_len = csl

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
        if up_signal is not None and self.p.sell_pos_close:
            close_short = True
        if dn_signal is not None and self.p.buy_pos_close:
            close_long = True
        buy_open = up_signal is not None and self.p.buy_pos_open
        sell_open = dn_signal is not None and self.p.sell_pos_open
        cp = float(self.base.close[0])
        sz = float(self.p.fixed_lot)
        if sz <= 0:
            return
        if close_short and self.position.size < 0:
            self.log(f'close short signal {cp:.2f}')
            self.close()
        if close_long and self.position.size > 0:
            self.log(f'close long signal {cp:.2f}')
            self.close()
        if buy_open:
            self.signal_count += 1
            self.log(f'buy signal {cp:.2f}')
            if self.position.size <= 0:
                self.buy(size=sz)
        if sell_open:
            self.signal_count += 1
            self.log(f'sell signal {cp:.2f}')
            if self.position.size >= 0:
                self.sell(size=sz)

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
