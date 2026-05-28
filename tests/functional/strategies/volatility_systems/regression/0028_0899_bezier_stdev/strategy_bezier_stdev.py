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


def _factorial(n):
    r = 1
    for i in range(2, n + 1):
        r *= i
    return r


def _price_series(ipc, data, ago=0):
    """Replicate MQ5 PriceSeries with Applied_price_ enum."""
    o = float(data.open[-ago])
    h = float(data.high[-ago])
    l = float(data.low[-ago])
    c = float(data.close[-ago])
    if ipc == 0:   return c                      # PRICE_CLOSE_
    elif ipc == 1: return o                       # PRICE_OPEN_
    elif ipc == 2: return h                       # PRICE_HIGH_
    elif ipc == 3: return l                       # PRICE_LOW_
    elif ipc == 4: return (h + l) / 2.0           # PRICE_MEDIAN_
    elif ipc == 5: return (h + l + c) / 3.0       # PRICE_TYPICAL_
    elif ipc == 6: return (h + l + c + c) / 4.0   # PRICE_WEIGHTED_
    return c


class BezierStDevIndicator(bt.Indicator):
    """Reconstructs Bezier_StDev indicator.

    Bezier curve interpolation of price over BPeriod, then StDev filter
    on the first derivative to generate Bulls/Bears signals.
    Buffers: 0=BezierLine, 1=ColorIndex, 2=BearsBuffer(sell), 3=BullsBuffer(buy).
    """
    lines = ('bezier', 'color', 'bears', 'bulls')
    params = dict(bperiod=8, t_param=0.5, ipc=6, dk=2.0, std_period=9)

    def __init__(self):
        self._bp = int(self.p.bperiod)
        self._t = float(self.p.t_param)
        self._ipc = int(self.p.ipc)
        self._dk = float(self.p.dk)
        self._sp = int(self.p.std_period)
        # Precompute binomial coefficients
        n = self._bp
        self._binom = [_factorial(n) / (_factorial(i) * _factorial(n - i))
                       for i in range(n + 1)]
        self.addminperiod(self._bp + self._sp + 3)

    def next(self):
        bp = self._bp
        t = self._t
        ipc = self._ipc
        dk = self._dk
        sp = self._sp

        # Compute Bezier for current and previous sp+1 bars
        bezier_vals = []
        needed = sp + 2
        for k in range(needed):
            r = 0.0
            for i in range(bp + 1):
                ago = k + i
                if ago >= len(self.data):
                    break
                price = _price_series(ipc, self.data, ago)
                r += price * self._binom[i] * (t ** i) * ((1 - t) ** (bp - i))
            bezier_vals.append(r)

        bz_cur = bezier_vals[0]
        self.lines.bezier[0] = bz_cur

        # Color
        if len(bezier_vals) > 1:
            bz_prev = bezier_vals[1]
            if bz_cur > bz_prev:
                self.lines.color[0] = 1.0
            elif bz_cur < bz_prev:
                self.lines.color[0] = 2.0
            else:
                self.lines.color[0] = 0.0
        else:
            self.lines.color[0] = 0.0

        # StDev filter on derivatives
        d_bezier = []
        for i in range(sp):
            if i + 1 < len(bezier_vals):
                d_bezier.append(bezier_vals[i] - bezier_vals[i + 1])
            else:
                d_bezier.append(0.0)

        mean_d = sum(d_bezier) / sp if sp > 0 else 0
        var_sum = sum((d - mean_d) ** 2 for d in d_bezier)
        std_dev = math.sqrt(var_sum / sp) if sp > 0 else 0

        dstd = d_bezier[0] if d_bezier else 0
        filt = dk * std_dev

        bulls = 0.0
        bears = 0.0
        if dstd > filt:
            bulls = bz_cur
        if dstd < -filt:
            bears = bz_cur

        self.lines.bulls[0] = bulls
        self.lines.bears[0] = bears


class ExpBezierStDevStrategy(bt.Strategy):
    """EA uses SignalMode for open/close: POINT reads arrow buffers, DIRECT reads Bezier line direction.
    Default: BuyOpen=POINT, SellOpen=POINT, BuyClose=DIRECT, SellClose=DIRECT."""
    params = dict(
        bperiod=8,
        t_param=0.5,
        ipc=6,
        dk=2.0,
        std_period=9,
        signal_bar=1,
        buy_open_mode=0,
        sell_open_mode=0,
        buy_close_mode=1,
        sell_close_mode=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        fixed_lot=0.1,
        point=0.0001,
        indicator_minutes=240,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.indicator = BezierStDevIndicator(
            self.signal_data,
            bperiod=self.p.bperiod, t_param=self.p.t_param,
            ipc=self.p.ipc, dk=self.p.dk, std_period=self.p.std_period,
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
        min_needed = self.p.bperiod + self.p.std_period + sig_bar + 5
        if len(self.signal_data) < min_needed:
            return
        csl = len(self.signal_data)
        if csl == self._last_signal_len:
            return
        self._last_signal_len = csl

        BO = SO = BC = SC = False

        # Buy open
        if self.p.buy_open_mode == 0:  # POINT
            bv = self._val(self.indicator.bulls, sig_bar)
            if bv != 0.0:
                BO = True
        else:  # DIRECT: V-bottom on Bezier line
            if sig_bar + 2 < len(self.signal_data):
                l0 = self._val(self.indicator.bezier, sig_bar)
                l1 = self._val(self.indicator.bezier, sig_bar + 1)
                l2 = self._val(self.indicator.bezier, sig_bar + 2)
                if l0 > l1 and l1 < l2:
                    BO = True

        # Sell open
        if self.p.sell_open_mode == 0:  # POINT
            sv = self._val(self.indicator.bears, sig_bar)
            if sv != 0.0:
                SO = True
        else:  # DIRECT: V-top on Bezier line
            if sig_bar + 2 < len(self.signal_data):
                l0 = self._val(self.indicator.bezier, sig_bar)
                l1 = self._val(self.indicator.bezier, sig_bar + 1)
                l2 = self._val(self.indicator.bezier, sig_bar + 2)
                if l0 < l1 and l1 > l2:
                    SO = True

        # Buy close (close short)
        if self.p.buy_close_mode == 0:  # POINT
            bv = self._val(self.indicator.bulls, sig_bar)
            if bv != 0.0:
                SC = True
        else:  # DIRECT: Bezier rising
            if sig_bar + 1 < len(self.signal_data):
                l0 = self._val(self.indicator.bezier, sig_bar)
                l1 = self._val(self.indicator.bezier, sig_bar + 1)
                if l0 > l1:
                    SC = True

        # Sell close (close long)
        if self.p.sell_close_mode == 0:  # POINT
            sv = self._val(self.indicator.bears, sig_bar)
            if sv != 0.0:
                BC = True
        else:  # DIRECT: Bezier falling
            if sig_bar + 1 < len(self.signal_data):
                l0 = self._val(self.indicator.bezier, sig_bar)
                l1 = self._val(self.indicator.bezier, sig_bar + 1)
                if l0 < l1:
                    BC = True

        cp = float(self.base.close[0])
        sz = float(self.p.fixed_lot)
        if sz <= 0:
            return

        if SC and self.position.size < 0:
            self.log(f'close short signal {cp:.5f}'); self.close()
        if BC and self.position.size > 0:
            self.log(f'close long signal {cp:.5f}'); self.close()
        if BO:
            self.signal_count += 1
            self.log(f'buy signal {cp:.5f}')
            if self.position.size <= 0:
                self.buy(size=sz)
        if SO:
            self.signal_count += 1
            self.log(f'sell signal {cp:.5f}')
            if self.position.size >= 0:
                self.sell(size=sz)

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
