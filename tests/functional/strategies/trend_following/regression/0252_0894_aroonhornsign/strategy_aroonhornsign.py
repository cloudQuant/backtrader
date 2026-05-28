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


class AroonHornSignIndicator(bt.Indicator):
    """Reconstructs AroonHornSign indicator.

    BULLS = 100 - (bars_since_highest_high + 0.5) * 100 / AroonPeriod
    BEARS = 100 - (bars_since_lowest_low + 0.5) * 100 / AroonPeriod
    trend = +1 if BULLS > BEARS and BULLS >= 50
    trend = -1 if BULLS < BEARS and BEARS >= 50
    BullsAroon (buy arrow) when trend flips from -1 to +1: low - ATR*3/8
    BearsAroon (sell arrow) when trend flips from +1 to -1: high + ATR*3/8
    Buffers: 0=BearsAroon(sell), 1=BullsAroon(buy).
    """
    lines = ('bears_aroon', 'bulls_aroon')
    params = dict(aroon_period=9, atr_period=10)

    def __init__(self):
        self._ap = int(self.p.aroon_period)
        self._atr_p = int(self.p.atr_period)
        self._trend_prev = 0
        self.addminperiod(max(self._ap, self._atr_p) + 3)

    def _calc_atr(self):
        period = self._atr_p
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
        ap = self._ap

        # Find bars since highest high and lowest low within AroonPeriod
        max_idx = 0
        max_val = float(self.data.high[0])
        min_idx = 0
        min_val = float(self.data.low[0])
        for i in range(ap):
            h = float(self.data.high[-i])
            l = float(self.data.low[-i])
            if h > max_val:
                max_val = h
                max_idx = i
            if l < min_val:
                min_val = l
                min_idx = i

        bulls = 100.0 - (max_idx + 0.5) * 100.0 / ap
        bears = 100.0 - (min_idx + 0.5) * 100.0 / ap

        trend = self._trend_prev
        if bulls > bears and bulls >= 50:
            trend = 1
        if bulls < bears and bears >= 50:
            trend = -1

        bu = 0.0
        be = 0.0

        if self._trend_prev < 0 and trend > 0:
            atr = self._calc_atr()
            bu = float(self.data.low[0]) - atr * 3.0 / 8.0

        if self._trend_prev > 0 and trend < 0:
            atr = self._calc_atr()
            be = float(self.data.high[0]) + atr * 3.0 / 8.0

        self._trend_prev = trend

        self.lines.bears_aroon[0] = be
        self.lines.bulls_aroon[0] = bu


class ExpAroonHornSignStrategy(bt.Strategy):
    """EA reads buffer 1 (BullsAroon/buy) and buffer 0 (BearsAroon/sell)
    with historical scan for closing."""
    params = dict(
        aroon_period=9,
        atr_period=10,
        signal_bar=1,
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
        self.indicator = AroonHornSignIndicator(
            self.signal_data,
            aroon_period=self.p.aroon_period,
            atr_period=self.p.atr_period,
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

    def _scan_history_for_close(self):
        if not self.position:
            return
        sig_bar = max(int(self.p.signal_bar), 1)
        max_look = min(len(self.signal_data) - sig_bar, 200)
        if self.position.size < 0 and self.p.sell_pos_close:
            for k in range(sig_bar + 1, sig_bar + max_look):
                if k >= len(self.signal_data):
                    break
                bv = float(self.indicator.bulls_aroon[-k])
                if not math.isnan(bv) and bv != 0.0:
                    self.log(f'close short hist buy -{k}'); self.close(); return
        if self.position.size > 0 and self.p.buy_pos_close:
            for k in range(sig_bar + 1, sig_bar + max_look):
                if k >= len(self.signal_data):
                    break
                sv = float(self.indicator.bears_aroon[-k])
                if not math.isnan(sv) and sv != 0.0:
                    self.log(f'close long hist sell -{k}'); self.close(); return

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return
        if self._check_exit_levels():
            return
        sig_bar = max(int(self.p.signal_bar) - 1, 0)
        min_needed = max(self.p.aroon_period, self.p.atr_period) + sig_bar + 4
        if len(self.signal_data) < min_needed:
            return
        csl = len(self.signal_data)
        if csl == self._last_signal_len:
            return
        self._last_signal_len = csl

        bv = float(self.indicator.bulls_aroon[-sig_bar]) if sig_bar else float(self.indicator.bulls_aroon[0])
        sv = float(self.indicator.bears_aroon[-sig_bar]) if sig_bar else float(self.indicator.bears_aroon[0])
        if math.isnan(bv): bv = 0.0
        if math.isnan(sv): sv = 0.0

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
        if not BC and not SC:
            self._scan_history_for_close()
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
