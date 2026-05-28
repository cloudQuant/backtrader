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
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
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
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class BykovTrendIndicator(bt.Indicator):
    """Reconstructs BykovTrend from its MQ5 source.

    Uses WPR(SSP) + ATR(15) to detect trend flips.
    Outputs buy_arrow / sell_arrow (non-zero price level when arrow fires).
    """
    lines = ('buy_arrow', 'sell_arrow')
    params = dict(risk=3, ssp=9)

    def __init__(self):
        self._k = 33 - int(self.p.risk)
        self._atr_period = 15
        self._wpr_period = int(self.p.ssp)
        self._uptrend = True
        self._old = True
        self.addminperiod(max(self._wpr_period, self._atr_period) + 2)

    def _calc_wpr(self):
        period = self._wpr_period
        if len(self.data) < period:
            return 0.0
        hh = max(float(self.data.high[-i]) for i in range(period))
        ll = min(float(self.data.low[-i]) for i in range(period))
        close_val = float(self.data.close[0])
        if hh == ll:
            return 0.0
        return -100.0 * (hh - close_val) / (hh - ll)

    def _calc_atr(self):
        period = self._atr_period
        if len(self.data) < period + 1:
            return 0.0
        total = 0.0
        for i in range(period):
            hi = float(self.data.high[-i])
            lo = float(self.data.low[-i])
            prev_close = float(self.data.close[-(i + 1)])
            tr = max(hi - lo, abs(hi - prev_close), abs(prev_close - lo))
            total += tr
        return total / period

    def next(self):
        k = self._k
        wpr = self._calc_wpr()
        atr = self._calc_atr()
        rng = atr * 3.0 / 8.0

        uptrend = self._uptrend
        if wpr < -100 + k:
            uptrend = False
        if wpr > -k:
            uptrend = True

        buy_val = 0.0
        sell_val = 0.0
        if not self._old and uptrend:
            buy_val = float(self.data.low[0]) - rng
        if self._old and not uptrend:
            sell_val = float(self.data.high[0]) + rng

        self.lines.buy_arrow[0] = buy_val
        self.lines.sell_arrow[0] = sell_val

        self._old = uptrend
        self._uptrend = uptrend


class ExpBykovTrendStrategy(bt.Strategy):
    params = dict(
        risk=3,
        ssp=9,
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
        self.indicator = BykovTrendIndicator(self.signal_data, risk=self.p.risk, ssp=self.p.ssp)
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
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _check_exit_levels(self):
        if not self.position:
            return False
        close_price = float(self.base.close[0])
        point_value = float(self.p.point)
        stop_distance = self.p.stop_loss_points * point_value if self.p.stop_loss_points > 0 else None
        take_distance = self.p.take_profit_points * point_value if self.p.take_profit_points > 0 else None
        entry_price = float(self.position.price)

        if self.position.size > 0:
            if stop_distance is not None and close_price <= entry_price - stop_distance:
                self.log(f'close long by SL close={close_price:.5f} entry={entry_price:.5f}')
                self.close()
                return True
            if take_distance is not None and close_price >= entry_price + take_distance:
                self.log(f'close long by TP close={close_price:.5f} entry={entry_price:.5f}')
                self.close()
                return True
        elif self.position.size < 0:
            if stop_distance is not None and close_price >= entry_price + stop_distance:
                self.log(f'close short by SL close={close_price:.5f} entry={entry_price:.5f}')
                self.close()
                return True
            if take_distance is not None and close_price <= entry_price - take_distance:
                self.log(f'close short by TP close={close_price:.5f} entry={entry_price:.5f}')
                self.close()
                return True
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
                val = float(self.indicator.buy_arrow[-k])
                if not math.isnan(val) and val != 0.0:
                    self.log(f'close short by historical buy arrow at -{k}')
                    self.close()
                    return

        if self.position.size > 0 and self.p.buy_pos_close:
            for k in range(sig_bar + 1, sig_bar + max_look):
                if k >= len(self.signal_data):
                    break
                val = float(self.indicator.sell_arrow[-k])
                if not math.isnan(val) and val != 0.0:
                    self.log(f'close long by historical sell arrow at -{k}')
                    self.close()
                    return

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return

        if self._check_exit_levels():
            return

        sig_bar = max(int(self.p.signal_bar) - 1, 0)
        min_needed = max(int(self.p.ssp), 15) + sig_bar + 3
        if len(self.signal_data) < min_needed:
            return

        current_signal_len = len(self.signal_data)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        buy_val = float(self.indicator.buy_arrow[-sig_bar]) if sig_bar else float(self.indicator.buy_arrow[0])
        sell_val = float(self.indicator.sell_arrow[-sig_bar]) if sig_bar else float(self.indicator.sell_arrow[0])
        if math.isnan(buy_val):
            buy_val = 0.0
        if math.isnan(sell_val):
            sell_val = 0.0

        close_price = float(self.base.close[0])
        size = float(self.p.fixed_lot)
        if size <= 0:
            return

        BUY_Open = False
        SELL_Open = False
        BUY_Close = False
        SELL_Close = False

        if buy_val != 0.0:
            if self.p.buy_pos_open:
                BUY_Open = True
            if self.p.sell_pos_close:
                SELL_Close = True

        if sell_val != 0.0:
            if self.p.sell_pos_open:
                SELL_Open = True
            if self.p.buy_pos_close:
                BUY_Close = True

        if not BUY_Close and not SELL_Close:
            self._scan_history_for_close()

        if SELL_Close and self.position.size < 0:
            self.log(f'close short by signal close={close_price:.5f}')
            self.close()
        if BUY_Close and self.position.size > 0:
            self.log(f'close long by signal close={close_price:.5f}')
            self.close()

        if BUY_Open:
            self.signal_count += 1
            self.log(f'buy signal arrow={buy_val:.5f} close={close_price:.5f}')
            if self.position.size <= 0:
                self.buy(size=size)

        if SELL_Open:
            self.signal_count += 1
            self.log(f'sell signal arrow={sell_val:.5f} close={close_price:.5f}')
            if self.position.size >= 0:
                self.sell(size=size)

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
