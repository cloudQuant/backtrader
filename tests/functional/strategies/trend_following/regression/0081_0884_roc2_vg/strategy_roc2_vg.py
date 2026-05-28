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


# ROC type enum: 1=MOM, 2=ROC, 3=ROCP, 4=ROCR, 5=ROCR100
def _calc_roc(price, prev_price, roc_type):
    if prev_price == 0:
        return 0.0
    if roc_type == 1:    # MOM
        return price - prev_price
    elif roc_type == 2:  # ROC
        return ((price / prev_price) - 1) * 100
    elif roc_type == 3:  # ROCP
        return (price - prev_price) / prev_price
    elif roc_type == 4:  # ROCR
        return price / prev_price
    elif roc_type == 5:  # ROCR100
        return (price / prev_price) * 100
    return (price - prev_price) / prev_price


class ROC2VGIndicator(bt.Indicator):
    """Reconstructs ROC2_VG indicator.

    DRAW_FILLING between ROC1 and ROC2.
    Buffer 0 = ROC1 (period1, type1), Buffer 1 = ROC2 (period2, type2).
    """
    lines = ('roc1', 'roc2')
    params = dict(roc_period1=8, roc_type1=1, roc_period2=14, roc_type2=1)

    def __init__(self):
        self._p1 = int(self.p.roc_period1)
        self._p2 = int(self.p.roc_period2)
        self._t1 = int(self.p.roc_type1)
        self._t2 = int(self.p.roc_type2)
        self.addminperiod(max(self._p1, self._p2) + 2)

    def next(self):
        price = float(self.data.close[0])

        if self._p1 < len(self.data):
            prev1 = float(self.data.close[-self._p1])
        else:
            prev1 = price
        self.lines.roc1[0] = _calc_roc(price, prev1, self._t1)

        if self._p2 < len(self.data):
            prev2 = float(self.data.close[-self._p2])
        else:
            prev2 = price
        self.lines.roc2[0] = _calc_roc(price, prev2, self._t2)


class ExpROC2VGStrategy(bt.Strategy):
    """FILLING cross EA: trades on ROC1 vs ROC2 crossover.
    Same pattern as CCI_Woodies: BUY on bearish→bullish, SELL on bullish→bearish.
    Supports Invert mode."""
    params = dict(
        roc_period1=8,
        roc_type1=1,
        roc_period2=14,
        roc_type2=1,
        signal_bar=1,
        invert=False,
        stop_loss_points=1000,
        take_profit_points=2000,
        fixed_lot=0.1,
        point=0.0001,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=240,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.indicator = ROC2VGIndicator(
            self.signal_data,
            roc_period1=self.p.roc_period1, roc_type1=self.p.roc_type1,
            roc_period2=self.p.roc_period2, roc_type2=self.p.roc_type2,
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
        min_needed = max(self.p.roc_period1, self.p.roc_period2) + sig_bar + 4
        if len(self.signal_data) < min_needed:
            return
        csl = len(self.signal_data)
        if csl == self._last_signal_len:
            return
        self._last_signal_len = csl

        if not self.p.invert:
            up_cur = self._val(self.indicator.roc1, sig_bar)
            dn_cur = self._val(self.indicator.roc2, sig_bar)
            up_prev = self._val(self.indicator.roc1, sig_bar + 1)
            dn_prev = self._val(self.indicator.roc2, sig_bar + 1)
        else:
            up_cur = self._val(self.indicator.roc2, sig_bar)
            dn_cur = self._val(self.indicator.roc1, sig_bar)
            up_prev = self._val(self.indicator.roc2, sig_bar + 1)
            dn_prev = self._val(self.indicator.roc1, sig_bar + 1)

        cp = float(self.base.close[0])
        sz = float(self.p.fixed_lot)
        if sz <= 0:
            return

        BO = SO = BC = SC = False

        if up_cur >= dn_cur and up_prev < dn_prev:
            if self.p.buy_pos_open: BO = True
            if self.p.sell_pos_close: SC = True

        if up_cur <= dn_cur and up_prev > dn_prev:
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
