from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
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
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class AlligatorStrategy(bt.Strategy):
    """
    MQL5 Wizard - Alligator indicator crossover signal.

    Trading logic (from readme):
    - Uses Williams Alligator: Jaw (SMMA 13, shift 8), Teeth (SMMA 8, shift 5), Lips (SMMA 5, shift 3)
    - Open long: After Alligator lines cross, Lips > Teeth > Jaw, and distances are widening
    - Close long: Jaw crosses above Lips
    - Open short: After Alligator lines cross, Lips < Teeth < Jaw, and distances are widening
    - Close short: Jaw crosses below Lips

    Simplified for backtrader: We use SMMA (=RMA) approximated by EMA with equivalent period.
    SMMA(N) ~ EMA(2*N-1). Shifts are applied by accessing past values.
    """
    params = dict(
        jaw_period=13,
        jaw_shift=8,
        teeth_period=8,
        teeth_shift=5,
        lips_period=5,
        lips_shift=3,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        # SMMA(N) can be approximated as EMA(2*N-1) for practical purposes
        # But for fidelity, we use bt.indicators.SmoothedMovingAverage which IS SMMA
        self.jaw = bt.indicators.SmoothedMovingAverage(self.data.close, period=self.p.jaw_period)
        self.teeth = bt.indicators.SmoothedMovingAverage(self.data.close, period=self.p.teeth_period)
        self.lips = bt.indicators.SmoothedMovingAverage(self.data.close, period=self.p.lips_period)

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._crossed = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _jaw(self, shift):
        """Get Jaw value with shift applied. shift=0 means current bar shifted by jaw_shift."""
        idx = -(self.p.jaw_shift + shift)
        if abs(idx) >= len(self.jaw):
            return None
        return float(self.jaw[idx])

    def _teeth(self, shift):
        """Get Teeth value with shift applied."""
        idx = -(self.p.teeth_shift + shift)
        if abs(idx) >= len(self.teeth):
            return None
        return float(self.teeth[idx])

    def _lips(self, shift):
        """Get Lips value with shift applied."""
        idx = -(self.p.lips_shift + shift)
        if abs(idx) >= len(self.lips):
            return None
        return float(self.lips[idx])

    def _lips_teeth_diff(self, shift):
        l = self._lips(shift)
        t = self._teeth(shift)
        if l is None or t is None:
            return None
        return l - t

    def _teeth_jaw_diff(self, shift):
        t = self._teeth(shift)
        j = self._jaw(shift)
        if t is None or j is None:
            return None
        return t - j

    def _check_cross(self):
        """Check if Alligator lines have crossed (reset crossed state)."""
        lt0 = self._lips_teeth_diff(0)
        lt1 = self._lips_teeth_diff(1)
        if lt0 is None or lt1 is None:
            return True
        if (lt0 >= 0 and lt1 < 0) or (lt0 <= 0 and lt1 > 0):
            self._crossed = False
            return True
        return False

    def _check_open_long(self):
        if self._check_cross():
            return False

        lt_m2 = self._lips_teeth_diff(-2)
        lt_m1 = self._lips_teeth_diff(-1)
        lt_0 = self._lips_teeth_diff(0)
        tj_m2 = self._teeth_jaw_diff(-2)
        tj_m1 = self._teeth_jaw_diff(-1)
        tj_0 = self._teeth_jaw_diff(0)

        if any(v is None for v in [lt_m2, lt_m1, lt_0, tj_m2, tj_m1, tj_0]):
            return False

        if (lt_m2 >= lt_m1 and lt_m1 >= lt_0 and lt_0 >= 0.0 and
                tj_m2 >= tj_m1 and tj_m1 >= tj_0 and tj_0 >= 0.0):
            self._crossed = True

        return self._crossed

    def _check_close_long(self):
        lt_m1 = self._lips_teeth_diff(-1)
        lt_0 = self._lips_teeth_diff(0)
        lt_1 = self._lips_teeth_diff(1)
        if any(v is None for v in [lt_m1, lt_0, lt_1]):
            return False
        return lt_m1 < 0 and lt_0 >= 0 and lt_1 > 0

    def _check_open_short(self):
        if self._check_cross():
            return False

        lt_m2 = self._lips_teeth_diff(-2)
        lt_m1 = self._lips_teeth_diff(-1)
        lt_0 = self._lips_teeth_diff(0)
        tj_m2 = self._teeth_jaw_diff(-2)
        tj_m1 = self._teeth_jaw_diff(-1)
        tj_0 = self._teeth_jaw_diff(0)

        if any(v is None for v in [lt_m2, lt_m1, lt_0, tj_m2, tj_m1, tj_0]):
            return False

        if (lt_m2 <= lt_m1 and lt_m1 <= lt_0 and lt_0 <= 0.0 and
                tj_m2 <= tj_m1 and tj_m1 <= tj_0 and tj_0 <= 0.0):
            self._crossed = True

        return self._crossed

    def _check_close_short(self):
        lt_m1 = self._lips_teeth_diff(-1)
        lt_0 = self._lips_teeth_diff(0)
        lt_1 = self._lips_teeth_diff(1)
        if any(v is None for v in [lt_m1, lt_0, lt_1]):
            return False
        return lt_m1 > 0 and lt_0 <= 0 and lt_1 < 0

    def next(self):
        self.bar_num += 1
        min_bars = self.p.jaw_period + self.p.jaw_shift + 5
        if len(self.data) < min_bars:
            return

        if self.position:
            if self.position.size > 0 and self._check_close_long():
                self.log(f'close long price={self.data.close[0]:.2f}')
                self.close()
                self._crossed = False
                return
            if self.position.size < 0 and self._check_close_short():
                self.log(f'close short price={self.data.close[0]:.2f}')
                self.close()
                self._crossed = False
                return
        else:
            if self._check_open_long():
                self.log(f'buy signal price={self.data.close[0]:.2f}')
                self.buy(size=self.p.lot)
                return
            if self._check_open_short():
                self.log(f'sell signal price={self.data.close[0]:.2f}')
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
