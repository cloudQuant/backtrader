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


class NRTRIndicator(bt.Indicator):
    """Reconstructs NRTR indicator from its MQ5 source.

    Uses iPeriod average range to compute dK scaling factor.
    Tracks price (close-based) and value with trend ratchet.
    When close drops below value in uptrend → flip to downtrend.
    When close rises above value in downtrend → flip to uptrend.
    4 buffers: TrendUp(0), TrendDown(1), SignUp(2), SignDown(3).
    """
    lines = ('trend_up', 'trend_down', 'sign_up', 'sign_down')
    params = dict(iperiod=10, idig=0)

    def __init__(self):
        self._period = int(self.p.iperiod)
        self._idig = int(self.p.idig)
        self._trend = 0
        self._trend_prev = 0
        self._price = 0.0
        self._value = 0.0
        self._first = True
        self.addminperiod(self._period + 2)

    def next(self):
        period = self._period

        if self._first:
            self._trend_prev = 0
            self._price = float(self.data.close[0])
            self._value = self._price
            self._first = False

        self._trend = self._trend_prev
        price = self._price
        value = self._value

        # Average range
        avg_range = 0.0
        for i in range(period):
            avg_range += abs(float(self.data.high[-i]) - float(self.data.low[-i]))
        avg_range /= period

        # dK scaling (original uses EURUSD digits but we simplify)
        digits_diff = 5 - self._idig  # approximate
        dK = avg_range / pow(10, digits_diff) if pow(10, digits_diff) != 0 else avg_range

        cur_close = float(self.data.close[0])

        if self._trend >= 0:
            price = max(price, cur_close)
            value = max(value, price * (1.0 - dK))
            if cur_close < value:
                price = cur_close
                value = price * (1.0 + dK)
                self._trend = -1
        elif self._trend <= 0:
            price = min(price, cur_close)
            value = min(value, price * (1.0 + dK))
            if cur_close > value:
                price = cur_close
                value = price * (1.0 - dK)
                self._trend = 1

        tu = value if self._trend > 0 else 0.0
        td = value if self._trend < 0 else 0.0
        su = tu if self._trend_prev < 0 and self._trend > 0 else 0.0
        sd = td if self._trend_prev > 0 and self._trend < 0 else 0.0

        self._trend_prev = self._trend
        self._price = price
        self._value = value

        self.lines.trend_up[0] = tu
        self.lines.trend_down[0] = td
        self.lines.sign_up[0] = su
        self.lines.sign_down[0] = sd


class ExpNRTRStrategy(bt.Strategy):
    """EA reads buffer 2 (SignUp) and buffer 3 (SignDown) for entry.
    Also reads buffer 0 (TrendUp) and buffer 1 (TrendDown) for continuous trend closing."""
    params = dict(
        iperiod=10,
        idig=0,
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
        self.indicator = NRTRIndicator(
            self.signal_data, iperiod=self.p.iperiod, idig=self.p.idig,
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
        min_needed = self.p.iperiod + sig_bar + 4
        if len(self.signal_data) < min_needed:
            return
        csl = len(self.signal_data)
        if csl == self._last_signal_len:
            return
        self._last_signal_len = csl

        def _val(line, offset):
            v = float(line[-offset]) if offset else float(line[0])
            return 0.0 if math.isnan(v) else v

        bv = _val(self.indicator.sign_up, sig_bar)
        sv = _val(self.indicator.sign_down, sig_bar)

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
