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


class SuperTrendIndicator(bt.Indicator):
    """Reconstructs SuperTrend indicator from its MQ5 source.

    Uses CCI and ATR. CCI crossing Level triggers trend change.
    TrendUp = low - ATR (ratchets upward), TrendDown = high + ATR (ratchets downward).
    SignUp when TrendDown was active and TrendUp appears (trend flip up).
    SignDown when TrendUp was active and TrendDown appears (trend flip down).
    """
    lines = ('trend_up', 'trend_down', 'sign_up', 'sign_down')
    params = dict(cci_period=50, atr_period=5, level=0)

    def __init__(self):
        self._cci_period = int(self.p.cci_period)
        self._atr_period = int(self.p.atr_period)
        self._level = int(self.p.level)
        self._prev_tu = 0.0
        self._prev_td = 0.0
        self._prev_cci = 0.0
        self.addminperiod(max(self._cci_period, self._atr_period) + 2)

    def _calc_cci(self):
        period = self._cci_period
        tp_vals = []
        for i in range(period):
            h = float(self.data.high[-i])
            l = float(self.data.low[-i])
            c = float(self.data.close[-i])
            tp_vals.append((h + l + c) / 3.0)
        mean_tp = sum(tp_vals) / period
        mean_dev = sum(abs(v - mean_tp) for v in tp_vals) / period
        if mean_dev == 0:
            return 0.0
        return (tp_vals[0] - mean_tp) / (0.015 * mean_dev)

    def _calc_atr(self):
        period = self._atr_period
        total = 0.0
        for i in range(period):
            h = float(self.data.high[-i])
            l = float(self.data.low[-i])
            if i + 1 < len(self.data):
                pc = float(self.data.close[-(i + 1)])
                tr = max(h - l, abs(h - pc), abs(l - pc))
            else:
                tr = h - l
            total += tr
        return total / period

    def next(self):
        cci = self._calc_cci()
        atr = self._calc_atr()
        level = self._level

        tu = 0.0
        td = 0.0
        su = 0.0
        sd = 0.0

        cur_high = float(self.data.high[0])
        cur_low = float(self.data.low[0])

        # Trend flip detection
        if cci >= level and self._prev_cci < level:
            tu = self._prev_td  # start uptrend from previous downtrend value

        if cci <= level and self._prev_cci > level:
            td = self._prev_tu  # start downtrend from previous uptrend value

        # Continuous trend
        if cci > level:
            tu = cur_low - atr
            if tu < self._prev_tu and self._prev_cci >= level:
                tu = self._prev_tu

        if cci < level:
            td = cur_high + atr
            if td > self._prev_td and self._prev_cci <= level:
                td = self._prev_td

        # Signal arrows: trend reversal
        if self._prev_td != 0.0 and tu != 0.0:
            su = tu
        if self._prev_tu != 0.0 and td != 0.0:
            sd = td

        self._prev_cci = cci
        self._prev_tu = tu
        self._prev_td = td

        self.lines.trend_up[0] = tu
        self.lines.trend_down[0] = td
        self.lines.sign_up[0] = su
        self.lines.sign_down[0] = sd


class ExpSuperTrendStrategy(bt.Strategy):
    """EA reads buffer 2 (SignUp) and buffer 3 (SignDown) for entry.
    Also reads buffer 0 (TrendUp) and buffer 1 (TrendDown) for continuous trend closing."""
    params = dict(
        cci_period=50,
        atr_period=5,
        level=0,
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
        self.indicator = SuperTrendIndicator(
            self.signal_data,
            cci_period=self.p.cci_period, atr_period=self.p.atr_period,
            level=self.p.level,
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
        min_needed = max(self.p.cci_period, self.p.atr_period) + sig_bar + 3
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
