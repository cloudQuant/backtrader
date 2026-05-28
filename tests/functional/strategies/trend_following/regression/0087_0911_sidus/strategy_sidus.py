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


class SidusIndicator(bt.Indicator):
    """Reconstructs Sidus indicator from its MQ5 source.

    Uses 4 MAs: FastEMA, SlowEMA, FastLWMA, SlowLWMA + ATR(15).
    Buy arrows on: FastLWMA crosses above SlowLWMA, or SlowLWMA crosses above SlowEMA.
    Sell arrows on reverse crosses.
    Arrow offset = ATR * digit scaling.
    """
    lines = ('buy_arrow', 'sell_arrow')
    params = dict(fast_ema=18, slow_ema=28, fast_lwma=5, slow_lwma=8, digit=0)

    def __init__(self):
        self._fe = int(self.p.fast_ema)
        self._se = int(self.p.slow_ema)
        self._fl = int(self.p.fast_lwma)
        self._sl = int(self.p.slow_lwma)
        self._digit = float(10 ** int(self.p.digit)) if int(self.p.digit) > 0 else 0.0
        self.addminperiod(max(self._fe, self._se, self._fl, self._sl) + 3)

    def _ema(self, period, ago):
        # Simple EMA approximation using close prices
        k = 2.0 / (period + 1)
        val = float(self.data.close[-(ago + period - 1)])
        for i in range(ago + period - 2, ago - 1, -1):
            val = float(self.data.close[-i]) * k + val * (1 - k) if i >= 0 else val
        return val

    def _lwma(self, period, ago):
        total = 0.0
        wsum = 0.0
        for i in range(period):
            w = float(period - i)
            total += float(self.data.close[-(ago + i)]) * w
            wsum += w
        return total / wsum if wsum > 0 else 0.0

    def _atr(self, period, ago):
        total = 0.0
        for i in range(period):
            idx = ago + i
            h = float(self.data.high[-idx])
            l = float(self.data.low[-idx])
            if idx + 1 < len(self.data):
                pc = float(self.data.close[-(idx + 1)])
                tr = max(h - l, abs(h - pc), abs(l - pc))
            else:
                tr = h - l
            total += tr
        return total / period

    def next(self):
        # Current bar (ago=0) and previous bar (ago=1)
        fst_ema_0 = self._ema(self._fe, 0)
        slw_ema_0 = self._ema(self._se, 0)
        fst_lwma_0 = self._lwma(self._fl, 0)
        slw_lwma_0 = self._lwma(self._sl, 0)

        fst_lwma_1 = self._lwma(self._fl, 1)
        slw_lwma_1 = self._lwma(self._sl, 1)
        slw_ema_1 = self._ema(self._se, 1)

        atr_val = self._atr(15, 0)
        rng = atr_val * 3.0
        digit = self._digit

        buy_val = 0.0
        sell_val = 0.0

        # Buy: FastLWMA crosses above SlowLWMA, or SlowLWMA crosses above SlowEMA
        if (fst_lwma_0 > slw_lwma_0 + digit and fst_lwma_1 <= slw_lwma_1):
            buy_val = float(self.data.low[0]) - rng
        if (slw_lwma_0 > slw_ema_0 + digit and slw_lwma_1 <= slw_ema_1):
            buy_val = float(self.data.low[0]) - rng

        # Sell: FastLWMA crosses below SlowLWMA, or SlowLWMA crosses below SlowEMA
        if (fst_lwma_0 < slw_lwma_0 - digit and fst_lwma_1 >= slw_lwma_1):
            sell_val = float(self.data.high[0]) + rng
        if (slw_lwma_0 < slw_ema_0 - digit and slw_lwma_1 >= slw_ema_1):
            sell_val = float(self.data.high[0]) + rng

        self.lines.buy_arrow[0] = buy_val
        self.lines.sell_arrow[0] = sell_val


class ExpSidusStrategy(bt.Strategy):
    params = dict(
        fast_ema=18,
        slow_ema=28,
        fast_lwma=5,
        slow_lwma=8,
        digit=0,
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
        self.indicator = SidusIndicator(
            self.signal_data,
            fast_ema=self.p.fast_ema, slow_ema=self.p.slow_ema,
            fast_lwma=self.p.fast_lwma, slow_lwma=self.p.slow_lwma,
            digit=self.p.digit,
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
                bv = float(self.indicator.buy_arrow[-k])
                if not math.isnan(bv) and bv != 0.0:
                    self.log(f'close short hist buy -{k}'); self.close(); return
        if self.position.size > 0 and self.p.buy_pos_close:
            for k in range(sig_bar + 1, sig_bar + max_look):
                if k >= len(self.signal_data):
                    break
                sv = float(self.indicator.sell_arrow[-k])
                if not math.isnan(sv) and sv != 0.0:
                    self.log(f'close long hist sell -{k}'); self.close(); return

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return
        if self._check_exit_levels():
            return
        sig_bar = max(int(self.p.signal_bar) - 1, 0)
        min_needed = max(self.p.fast_ema, self.p.slow_ema, self.p.fast_lwma, self.p.slow_lwma) + sig_bar + 5
        if len(self.signal_data) < min_needed:
            return
        csl = len(self.signal_data)
        if csl == self._last_signal_len:
            return
        self._last_signal_len = csl

        bv = float(self.indicator.buy_arrow[-sig_bar]) if sig_bar else float(self.indicator.buy_arrow[0])
        sv = float(self.indicator.sell_arrow[-sig_bar]) if sig_bar else float(self.indicator.sell_arrow[0])
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
