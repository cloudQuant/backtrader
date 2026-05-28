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


class StalinIndicator(bt.Indicator):
    """Reconstructs Stalin indicator from its MQ5 source.

    Uses Fast/Slow MA crossover with optional RSI filter.
    BU() fires buy arrow at low if flat distance check passes.
    BD() fires sell arrow at high if flat distance check passes.
    Optional Confirm parameter adds a price-distance confirmation step.
    """
    lines = ('buy_arrow', 'sell_arrow')
    params = dict(ma_method='ema', fast=14, slow=21, rsi_period=17,
                  confirm=0, flat=0, point=0.0001)

    def __init__(self):
        self._fast = int(self.p.fast)
        self._slow = int(self.p.slow)
        self._rsi = int(self.p.rsi_period)
        self._confirm2 = float(self.p.confirm) * float(self.p.point)
        self._flat2 = float(self.p.flat) * float(self.p.point)
        self._e1 = 0.0  # last buy arrow price
        self._e2 = 0.0  # last sell arrow price
        self._iup = 0.0  # pending buy confirmation price
        self._idn = 0.0  # pending sell confirmation price
        self.addminperiod(max(self._fast, self._slow, self._rsi if self._rsi > 0 else 1) + 3)

    def _calc_ema(self, period, ago):
        k = 2.0 / (period + 1)
        val = float(self.data.close[-(ago + period - 1)])
        for i in range(ago + period - 2, ago - 1, -1):
            val = float(self.data.close[-i]) * k + val * (1 - k) if i >= 0 else val
        return val

    def _calc_lwma(self, period, ago):
        total = 0.0
        wsum = 0.0
        for i in range(period):
            w = float(period - i)
            total += float(self.data.close[-(ago + i)]) * w
            wsum += w
        return total / wsum if wsum > 0 else 0.0

    def _calc_sma(self, period, ago):
        total = 0.0
        for i in range(period):
            total += float(self.data.close[-(ago + i)])
        return total / period

    def _calc_ma(self, period, ago):
        method = str(self.p.ma_method).lower()
        if method == 'lwma':
            return self._calc_lwma(period, ago)
        elif method == 'sma':
            return self._calc_sma(period, ago)
        else:
            return self._calc_ema(period, ago)

    def _calc_rsi(self, period, ago):
        gains = 0.0
        losses = 0.0
        for i in range(period):
            idx = ago + i
            c = float(self.data.close[-idx])
            cp = float(self.data.close[-(idx + 1)])
            diff = c - cp
            if diff > 0:
                gains += diff
            else:
                losses -= diff
        avg_gain = gains / period
        avg_loss = losses / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def next(self):
        fast_ma_0 = self._calc_ma(self._fast, 0)
        slow_ma_0 = self._calc_ma(self._slow, 0)
        fast_ma_1 = self._calc_ma(self._fast, 1)
        slow_ma_1 = self._calc_ma(self._slow, 1)

        use_rsi = self._rsi > 0
        rsi_val = self._calc_rsi(self._rsi, 0) if use_rsi else 50.0

        buy_val = 0.0
        sell_val = 0.0

        cur_low = float(self.data.low[0])
        cur_high = float(self.data.high[0])
        cur_close = float(self.data.close[0])
        flat2 = self._flat2
        confirm2 = self._confirm2

        # MA crossover buy signal
        if (not use_rsi) or (fast_ma_1 < slow_ma_1 and fast_ma_0 > slow_ma_0 and rsi_val > 50):
            if not confirm2:
                # BU: fire buy arrow if flat distance passes
                if cur_low >= (self._e1 + flat2) or cur_low <= (self._e1 - flat2):
                    buy_val = cur_low
                    self._e1 = cur_low
            else:
                self._iup = cur_low
                self._idn = 0.0

        # MA crossover sell signal
        if (not use_rsi) or (fast_ma_1 > slow_ma_1 and fast_ma_0 < slow_ma_0 and rsi_val < 50):
            if not confirm2:
                if cur_high >= (self._e2 + flat2) or cur_high <= (self._e2 - flat2):
                    sell_val = cur_high
                    self._e2 = cur_high
            else:
                self._idn = cur_high
                self._iup = 0.0

        # Confirm pending buy
        if self._iup and cur_high - self._iup >= confirm2 and cur_close <= cur_high:
            if cur_low >= (self._e1 + flat2) or cur_low <= (self._e1 - flat2):
                buy_val = cur_low
                self._e1 = cur_low
            self._iup = 0.0

        # Confirm pending sell
        if self._idn and self._idn - cur_low >= confirm2 and float(self.data.open[0]) >= cur_close:
            if cur_high >= (self._e2 + flat2) or cur_high <= (self._e2 - flat2):
                sell_val = cur_high
                self._e2 = cur_high
            self._idn = 0.0

        self.lines.buy_arrow[0] = buy_val
        self.lines.sell_arrow[0] = sell_val


class ExpStalinStrategy(bt.Strategy):
    params = dict(
        ma_method='ema',
        fast=14,
        slow=21,
        rsi_period=17,
        confirm=0,
        flat=0,
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
        self.indicator = StalinIndicator(
            self.signal_data,
            ma_method=self.p.ma_method, fast=self.p.fast, slow=self.p.slow,
            rsi_period=self.p.rsi_period, confirm=self.p.confirm,
            flat=self.p.flat, point=self.p.point,
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
        min_needed = max(self.p.fast, self.p.slow, self.p.rsi_period) + sig_bar + 5
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
