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


def _applied_price(data, price_type, ago=0):
    """Get price based on ENUM_APPLIED_PRICE."""
    o = float(data.open[-ago])
    h = float(data.high[-ago])
    l = float(data.low[-ago])
    c = float(data.close[-ago])
    if price_type == 0: return c           # PRICE_CLOSE
    elif price_type == 1: return o         # PRICE_OPEN
    elif price_type == 2: return h         # PRICE_HIGH
    elif price_type == 3: return l         # PRICE_LOW
    elif price_type == 4: return (h+l)/2   # PRICE_MEDIAN
    elif price_type == 5: return (h+l+c)/3 # PRICE_TYPICAL
    elif price_type == 6: return (h+l+c+c)/4  # PRICE_WEIGHTED
    return c


class CCIWoodiesIndicator(bt.Indicator):
    """Reconstructs CCI_Woodies indicator.

    DRAW_FILLING between FastCCI and SlowCCI.
    Buffer 0 = FastCCI, Buffer 1 = SlowCCI.
    When Fast > Slow → bullish (Lime fill); when Fast < Slow → bearish (Plum fill).
    """
    lines = ('fast_cci', 'slow_cci')
    params = dict(fast_period=6, fast_price=4, slow_period=14, slow_price=4)

    def __init__(self):
        self._fp = int(self.p.fast_period)
        self._sp = int(self.p.slow_period)
        self._fpr = int(self.p.fast_price)
        self._spr = int(self.p.slow_price)
        self.addminperiod(max(self._fp, self._sp) + 2)

    def _calc_cci(self, period, price_type):
        prices = []
        for i in range(period):
            if i >= len(self.data):
                break
            prices.append(_applied_price(self.data, price_type, i))
        if not prices:
            return 0.0
        mean = sum(prices) / len(prices)
        mad = sum(abs(p - mean) for p in prices) / len(prices)
        tp = prices[0]  # current bar
        if mad == 0:
            return 0.0
        return (tp - mean) / (0.015 * mad)

    def next(self):
        self.lines.fast_cci[0] = self._calc_cci(self._fp, self._fpr)
        self.lines.slow_cci[0] = self._calc_cci(self._sp, self._spr)


class ExpCCIWoodiesStrategy(bt.Strategy):
    """FILLING cross EA: trades on FastCCI vs SlowCCI crossover.
    BUY when cloud transitions from bearish to bullish.
    SELL when cloud transitions from bullish to bearish.
    Supports Invert mode to swap signal directions."""
    params = dict(
        fast_period=6,
        fast_price=4,
        slow_period=14,
        slow_price=4,
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
        self.indicator = CCIWoodiesIndicator(
            self.signal_data,
            fast_period=self.p.fast_period, fast_price=self.p.fast_price,
            slow_period=self.p.slow_period, slow_price=self.p.slow_price,
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
        min_needed = max(self.p.fast_period, self.p.slow_period) + sig_bar + 4
        if len(self.signal_data) < min_needed:
            return
        csl = len(self.signal_data)
        if csl == self._last_signal_len:
            return
        self._last_signal_len = csl

        # Read 2 consecutive values of each buffer
        if not self.p.invert:
            up_cur = self._val(self.indicator.fast_cci, sig_bar)
            dn_cur = self._val(self.indicator.slow_cci, sig_bar)
            up_prev = self._val(self.indicator.fast_cci, sig_bar + 1)
            dn_prev = self._val(self.indicator.slow_cci, sig_bar + 1)
        else:
            up_cur = self._val(self.indicator.slow_cci, sig_bar)
            dn_cur = self._val(self.indicator.fast_cci, sig_bar)
            up_prev = self._val(self.indicator.slow_cci, sig_bar + 1)
            dn_prev = self._val(self.indicator.fast_cci, sig_bar + 1)

        cp = float(self.base.close[0])
        sz = float(self.p.fixed_lot)
        if sz <= 0:
            return

        BO = SO = BC = SC = False

        # BUY: transition from bearish (up < dn) to bullish (up >= dn)
        if up_cur >= dn_cur and up_prev < dn_prev:
            if self.p.buy_pos_open: BO = True
            if self.p.sell_pos_close: SC = True

        # SELL: transition from bullish (up > dn) to bearish (up <= dn)
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
