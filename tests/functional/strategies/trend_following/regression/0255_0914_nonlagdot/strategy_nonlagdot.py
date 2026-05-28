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

PI = math.pi


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


class NonLagDotIndicator(bt.Indicator):
    """Reconstructs NonLagDot from its MQ5 source.

    Applies a weighted cosine kernel over SMA values to produce a non-lag MA,
    then assigns color: 0=gray, 1=magenta(down), 2=green(up).
    """
    lines = ('nlm', 'color')
    params = dict(length=10, filter_pts=0, deviation=0.0, point=0.0001)

    def __init__(self):
        self._length = int(self.p.length)
        coeff = 3 * PI
        phase = self._length - 1
        cycle = 4
        self._len_total = int(self._length * cycle + phase)
        self._dT1 = (2 * cycle - 1) / (cycle * self._length - 1)
        self._dT2 = 1.0 / (phase - 1) if phase > 1 else 1.0
        self._kd = 1.0 + self.p.deviation / 100.0
        self._fi = int(self.p.filter_pts) * float(self.p.point)
        self._coeff = coeff
        self._phase = phase
        self._cycle = cycle
        self._trend = 0
        self.addminperiod(self._length + self._len_total + 2)

    def _calc_sma(self, ago):
        length = self._length
        total = 0.0
        for i in range(length):
            total += float(self.data.close[-(ago + i)])
        return total / length

    def next(self):
        length = self._length
        len_total = self._len_total
        coeff = self._coeff
        phase = self._phase
        fi = self._fi

        # Build weighted sum using cosine kernel over SMA values
        total_sum = 0.0
        total_weight = 0.0
        t = 0.0

        for i in range(int(len_total)):
            # SMA at offset i (0 = current bar)
            sma_val = self._calc_sma(i)
            if i <= phase - 1:
                alfa = 1.0
            else:
                alfa = 1.0 / (1.0 + math.exp((i - phase + 0.5) * coeff / len_total))

            beta = math.cos(PI * t)
            g = 1.0 / (coeff * t + 1.0)
            if t <= 0.5:
                g = 1.0

            total_sum += sma_val * beta * g * alfa
            total_weight += beta * g * alfa

            if t < 0.5:
                t += self._dT2
            elif t < len_total - 1:
                t += self._dT1

        nlm_val = self._kd * total_sum / total_weight if total_weight > 0 else 0.0

        # Filter: if change < fi, hold previous value
        prev_nlm = float(self.lines.nlm[-1]) if len(self.lines.nlm) > 1 and not math.isnan(float(self.lines.nlm[-1])) else nlm_val
        if fi > 0 and abs(nlm_val - prev_nlm) < fi:
            nlm_val = prev_nlm

        self.lines.nlm[0] = nlm_val

        # Trend detection
        trend = self._trend
        if nlm_val - prev_nlm > fi:
            trend = 1  # up
        if prev_nlm - nlm_val > fi:
            trend = -1  # down

        # Color: 0=gray, 1=magenta(down), 2=green(up)
        color = 0.0
        if trend > 0:
            color = 2.0
        if trend < 0:
            color = 1.0

        self.lines.color[0] = color
        self._trend = trend


class ExpNonLagDotStrategy(bt.Strategy):
    params = dict(
        length=10,
        filter_pts=0,
        deviation=0.0,
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
        self.indicator = NonLagDotIndicator(
            self.signal_data, length=self.p.length,
            filter_pts=self.p.filter_pts, deviation=self.p.deviation,
            point=self.p.point,
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
        sig_bar = max(int(self.p.signal_bar), 1)
        min_needed = int(self.p.length) * 5 + sig_bar + 5
        if len(self.signal_data) < min_needed:
            return
        csl = len(self.signal_data)
        if csl == self._last_signal_len:
            return
        self._last_signal_len = csl

        # CopyBuffer copies 2 values: TrendValue[0]=older, TrendValue[1]=newer(SignalBar)
        # sig_bar-1 maps to SignalBar in bt (0-indexed ago)
        idx_new = sig_bar - 1  # SignalBar position
        idx_old = sig_bar      # SignalBar+1 position
        c_new = float(self.indicator.color[-idx_new]) if idx_new > 0 else float(self.indicator.color[0])
        c_old = float(self.indicator.color[-idx_old])
        if math.isnan(c_new) or math.isnan(c_old):
            return

        cp = float(self.base.close[0])
        sz = float(self.p.fixed_lot)
        if sz <= 0:
            return

        BO = SO = BC = SC = False

        # c_old==1(down) && c_new==2(up) -> BUY
        if c_old == 1.0 and c_new == 2.0:
            if self.p.buy_pos_open: BO = True
            if self.p.sell_pos_close: SC = True
        # c_old==2(up) && c_new==1(down) -> SELL
        if c_old == 2.0 and c_new == 1.0:
            if self.p.sell_pos_open: SO = True
            if self.p.buy_pos_close: BC = True

        # Continuous trend close
        if not BC and not SC:
            if self.p.sell_pos_open and self.p.sell_pos_close and c_new == 2.0:
                SC = True
            if self.p.buy_pos_open and self.p.buy_pos_close and c_new == 1.0:
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
