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


class StepMANRTRIndicator(bt.Indicator):
    """Reconstructs StepMA_NRTR indicator.

    StepSizeCalc: Volty-based step size from ATR-like calculation.
    StepMACalc: Trend-following MA with NRTR ratchet.
    4 buffers: UpBuffer(0), DnBuffer(1), BuySignal(2), SellSignal(3).
    Buy when trend flips from down to up. Sell on reverse.
    """
    lines = ('trend_up', 'trend_down', 'buy_signal', 'sell_signal')
    params = dict(length=10, kv=1.0, step_size=0, percentage=0, switch=1)

    def __init__(self):
        self._length = int(self.p.length)
        self._kv = float(self.p.kv)
        self._step_size = int(self.p.step_size)
        self._percentage = float(self.p.percentage)
        self._switch = int(self.p.switch)  # 0=Close, 1=HighLow
        self._trend0 = 0
        self._trend1 = 0
        self._trend1_ = 0
        self._smax1 = 0.0
        self._smin1 = 0.0
        self._first = True
        self.addminperiod(self._length + 3)

    def _step_size_calc(self, bar_idx):
        length = self._length
        kv = self._kv
        if self._step_size > 0:
            return self._step_size
        # Volty calculation: average of high-low ranges
        total = 0.0
        for i in range(length):
            h = float(self.data.high[-i])
            l = float(self.data.low[-i])
            total += h - l
        avg = total / length if length > 0 else 0
        # Convert to points-like value
        step = avg * kv / self.data.close[0] * 10000 if self.data.close[0] != 0 else 0
        return max(step, 1)

    def _step_ma_calc(self):
        step = self._step_size_calc(0)
        point = float(self.data.close[0]) / 10000.0 if float(self.data.close[0]) > 10 else 0.0001
        size_p = step * point
        size_2p = size_p * 2

        cur_high = float(self.data.high[0])
        cur_low = float(self.data.low[0])
        cur_close = float(self.data.close[0])

        if self._first:
            self._trend1 = 0
            self._smax1 = cur_low + size_2p
            self._smin1 = cur_high - size_2p
            self._first = False

        if self._switch:  # HighLow mode
            smax0 = cur_high - size_2p
            smin0 = cur_low + size_2p
        else:
            smax0 = cur_close + size_2p
            smin0 = cur_close - size_2p

        self._trend0 = self._trend1

        if cur_close > self._smax1:
            self._trend0 = 1
        if cur_close < self._smin1:
            self._trend0 = -1

        if self._trend0 > 0:
            if smin0 < self._smin1:
                smin0 = self._smin1
            result = smin0 + size_p
        else:
            if smax0 > self._smax1:
                smax0 = self._smax1
            result = smax0 - size_p

        self._trend1_ = self._trend1
        self._smax1 = smax0
        self._smin1 = smin0
        self._trend1 = self._trend0

        return result, size_p

    def next(self):
        result, size_p = self._step_ma_calc()
        ratio = self._percentage / 100.0 if self._percentage > 0 else 0
        step = self._step_size_calc(0)
        if step > 0:
            result += ratio / step

        tu = 0.0
        td = 0.0
        bs = 0.0
        ss = 0.0

        point = float(self.data.close[0]) / 10000.0 if float(self.data.close[0]) > 10 else 0.0001

        if self._trend0 > 0:
            tu = result - step * point
            if self._trend1_ < 0:
                bs = tu
        if self._trend0 < 0:
            td = result + step * point
            if self._trend1_ > 0:
                ss = td

        self.lines.trend_up[0] = tu
        self.lines.trend_down[0] = td
        self.lines.buy_signal[0] = bs
        self.lines.sell_signal[0] = ss


class ExpStepMANRTRStrategy(bt.Strategy):
    """EA reads buffer 2 (BuySignal) and buffer 3 (SellSignal) for entry.
    Also reads buffer 0 (TrendUp) and buffer 1 (TrendDown) for continuous trend closing."""
    params = dict(
        length=10,
        kv=1.0,
        step_size=0,
        percentage=0,
        switch=1,
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
        self.indicator = StepMANRTRIndicator(
            self.signal_data,
            length=self.p.length, kv=self.p.kv,
            step_size=self.p.step_size, percentage=self.p.percentage,
            switch=self.p.switch,
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

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return
        if self._check_exit_levels():
            return
        sig_bar = max(int(self.p.signal_bar) - 1, 0)
        min_needed = int(self.p.length) + sig_bar + 5
        if len(self.signal_data) < min_needed:
            return
        csl = len(self.signal_data)
        if csl == self._last_signal_len:
            return
        self._last_signal_len = csl

        def _val(line, offset):
            v = float(line[-offset]) if offset else float(line[0])
            return 0.0 if math.isnan(v) else v

        bv = _val(self.indicator.buy_signal, sig_bar)
        sv = _val(self.indicator.sell_signal, sig_bar)

        cp = float(self.base.close[0])
        sz = float(self.p.fixed_lot)
        if sz <= 0:
            return

        BO = SO = BC = SC = False
        if bv != 0.0:
            if self.p.buy_pos_open: BO = True
            if self.p.sell_pos_close: SC = True
        if sv != 0.0:
            if self.p.sell_pos_open: SO = True
            if self.p.buy_pos_close: BC = True

        # Continuous trend close
        tu = _val(self.indicator.trend_up, sig_bar)
        td = _val(self.indicator.trend_down, sig_bar)
        if self.p.sell_pos_open and self.p.sell_pos_close and tu != 0.0:
            SC = True
        if self.p.buy_pos_open and self.p.buy_pos_close and td != 0.0:
            BC = True

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
