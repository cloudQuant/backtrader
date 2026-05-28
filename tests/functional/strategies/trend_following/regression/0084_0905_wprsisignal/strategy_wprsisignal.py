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


class WPRSISignalIndicator(bt.Indicator):
    """Reconstructs WPRSIsignal indicator from its MQ5 source.

    Uses WPR and RSI with same period.
    Buy: WPR crosses above -20 from below AND RSI > 50, with filterUP lookback confirmation.
    Sell: WPR crosses below -80 from above AND RSI < 50, with filterDN lookback confirmation.
    """
    lines = ('sell_arrow', 'buy_arrow')  # buffer 0 = sell, buffer 1 = buy
    params = dict(wprsi_period=27, filter_up=10, filter_dn=10)

    def __init__(self):
        self._period = int(self.p.wprsi_period)
        self._filter_up = int(self.p.filter_up)
        self._filter_dn = int(self.p.filter_dn)
        filter_max = max(self._filter_up, self._filter_dn)
        self.addminperiod(self._period + filter_max + 3)

    def _calc_wpr(self, ago=0):
        period = self._period
        highest = max(float(self.data.high[-(ago + i)]) for i in range(period))
        lowest = min(float(self.data.low[-(ago + i)]) for i in range(period))
        close = float(self.data.close[-ago])
        if highest == lowest:
            return -50.0
        return -100.0 * (highest - close) / (highest - lowest)

    def _calc_rsi(self, ago=0):
        period = self._period
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
        wpr_0 = self._calc_wpr(0)
        wpr_1 = self._calc_wpr(1)
        rsi_0 = self._calc_rsi(0)

        buy_val = 0.0
        sell_val = 0.0

        cur_high = float(self.data.high[0])
        cur_low = float(self.data.low[0])
        rng = cur_high - cur_low

        # Buy: WPR crosses above -20 from below, RSI > 50
        if wpr_0 > -20.0 and wpr_1 < -20.0 and rsi_0 > 50.0:
            z = 0
            for k in range(2, self._filter_up + 3):
                if k < len(self.data):
                    wk = self._calc_wpr(k)
                    if wk > -20.0:
                        z = 1
                        break
            if z == 0:
                buy_val = cur_low - rng / 2.0

        # Sell: WPR crosses below -80 from above, RSI < 50
        if wpr_1 > -80.0 and wpr_0 < -80.0 and rsi_0 < 50.0:
            h = 0
            for c in range(2, self._filter_dn + 3):
                if c < len(self.data):
                    wk = self._calc_wpr(c)
                    if wk < -80.0:
                        h = 1
                        break
            if h == 0:
                sell_val = cur_high + rng / 2.0

        self.lines.sell_arrow[0] = sell_val
        self.lines.buy_arrow[0] = buy_val


class ExpWPRSISignalStrategy(bt.Strategy):
    """EA reads buffer 1 (BuyBuffer) and buffer 0 (SellBuffer) with historical scan."""
    params = dict(
        wprsi_period=27,
        filter_up=10,
        filter_dn=10,
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
        self.indicator = WPRSISignalIndicator(
            self.signal_data,
            wprsi_period=self.p.wprsi_period,
            filter_up=self.p.filter_up,
            filter_dn=self.p.filter_dn,
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
        filter_max = max(self.p.filter_up, self.p.filter_dn)
        min_needed = self.p.wprsi_period + filter_max + sig_bar + 5
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
