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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
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
    params = (('datetime', None), ('open', 0), ('high', 1), ('low', 2),
              ('close', 3), ('volume', 4), ('openinterest', 5))


class VWAPCloseIndicator(bt.Indicator):
    """Reconstructs VWAP_Close indicator.

    VWAP = sum(close[i] * volume[i], i=0..n-1) / sum(volume[i], i=0..n-1)
    Uses tick volume by default.
    Buffer 0 = VWAP line.
    """
    lines = ('vwap',)
    params = dict(n=2)

    def __init__(self):
        self._n = int(self.p.n)
        self.addminperiod(self._n + 1)

    def next(self):
        n = self._n
        sum1 = 0.0
        sum2 = 0
        for i in range(n):
            if i >= len(self.data):
                break
            c = float(self.data.close[-i])
            v = float(self.data.volume[-i])
            if v < 1:
                v = 1
            sum1 += c * v
            sum2 += v

        if sum2 > 0:
            self.lines.vwap[0] = sum1 / sum2
        else:
            prev = float(self.lines.vwap[-1]) if len(self.lines.vwap) > 1 else float(self.data.close[0])
            self.lines.vwap[0] = prev if not math.isnan(prev) else float(self.data.close[0])


class ExpVWAPCloseStrategy(bt.Strategy):
    """EA reads buffer 0 with 3 bars:
    BUY: Value[1] < Value[2] (was falling) AND Value[0] > Value[1] (now rising) → V-bottom
    SELL: Value[1] > Value[2] (was rising) AND Value[0] < Value[1] (now falling) → V-top
    Close: direction reversal without V pattern required."""
    params = dict(
        n=2,
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        fixed_lot=0.1,
        point=0.0001,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=360,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.indicator = VWAPCloseIndicator(
            self.signal_data, n=self.p.n,
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
        cp = float(self.base.close[0])
        pv = float(self.p.point)
        sd = self.p.stop_loss_points * pv if self.p.stop_loss_points > 0 else None
        td = self.p.take_profit_points * pv if self.p.take_profit_points > 0 else None
        ep = float(self.position.price)
        if self.position.size > 0:
            if sd and cp <= ep - sd:
                self.log(f'close long SL {cp:.5f}'); self.close(); return True
            if td and cp >= ep + td:
                self.log(f'close long TP {cp:.5f}'); self.close(); return True
        elif self.position.size < 0:
            if sd and cp >= ep + sd:
                self.log(f'close short SL {cp:.5f}'); self.close(); return True
            if td and cp <= ep - td:
                self.log(f'close short TP {cp:.5f}'); self.close(); return True
        return False

    def _val(self, line, offset):
        v = float(line[-offset]) if offset else float(line[0])
        return 0.0 if math.isnan(v) else v

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return
        if self._check_exit_levels():
            return
        sig_bar = max(int(self.p.signal_bar) - 1, 0)
        min_needed = self.p.n + sig_bar + 4
        if len(self.signal_data) < min_needed:
            return
        csl = len(self.signal_data)
        if csl == self._last_signal_len:
            return
        self._last_signal_len = csl

        # Read 3 consecutive VWAP values: newest (sig_bar), sig_bar+1, sig_bar+2
        v0 = self._val(self.indicator.vwap, sig_bar)
        v1 = self._val(self.indicator.vwap, sig_bar + 1)
        v2 = self._val(self.indicator.vwap, sig_bar + 2)

        cp = float(self.base.close[0])
        sz = float(self.p.fixed_lot)
        if sz <= 0:
            return

        BO = SO = BC = SC = False

        # BUY: V-bottom (was falling, now rising)
        if v1 < v2 and v0 > v1:
            if self.p.buy_pos_open: BO = True
            if self.p.sell_pos_close: SC = True

        # SELL: V-top (was rising, now falling)
        if v1 > v2 and v0 < v1:
            if self.p.sell_pos_open: SO = True
            if self.p.buy_pos_close: BC = True

        if SC and self.position.size < 0:
            self.log(f'close short signal {cp:.5f}'); self.close()
        if BC and self.position.size > 0:
            self.log(f'close long signal {cp:.5f}'); self.close()
        if BO:
            self.signal_count += 1
            self.log(f'buy signal {cp:.5f}')
            if self.position.size <= 0: self.buy(size=sz)
        if SO:
            self.signal_count += 1
            self.log(f'sell signal {cp:.5f}')
            if self.position.size >= 0: self.sell(size=sz)

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0: self.buy_count += 1
            elif trade.size < 0: self.sell_count += 1
            self._position_was_open = True; return
        if not trade.isclosed: return
        self.trade_count += 1
        if trade.pnlcomm >= 0: self.win_count += 1
        else: self.loss_count += 1
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
