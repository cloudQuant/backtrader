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


# ---------------------------------------------------------------------------
# Williams %R helper  (same formula as MT5 iWPR, range [−100, 0])
# ---------------------------------------------------------------------------
def _wpr(highs, lows, close, period):
    """Return Williams %R for the last bar given arrays of length >= period."""
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    if hh == ll:
        return 0.0
    return -100.0 * (hh - close) / (hh - ll)


class ASCtrendIndicator(bt.Indicator):
    """Reconstructs ASCtrend from its MQ5 source.

    Outputs:
      - buy_arrow : non-zero price level when a buy arrow fires
      - sell_arrow: non-zero price level when a sell arrow fires
    """
    lines = ('buy_arrow', 'sell_arrow')
    params = dict(risk=4)

    def __init__(self):
        self._x1 = 67 + int(self.p.risk)
        self._x2 = 33 - int(self.p.risk)
        self._wpr_periods = [3, 4, 3 + int(self.p.risk) * 2]
        self._value10 = 2   # default WPR index
        min_period = max(3 + int(self.p.risk) * 2, 4) + 1
        # need enough history for ATR-style range calc (10 bars) + WPR look-back
        self.addminperiod(max(min_period, 12))

    # -- helpers operating on self.data (signal-timeframe feed) --
    def _get_wpr_val(self, period_idx, ago):
        """Compute WPR(period) at bar shifted by -ago from current."""
        period = self._wpr_periods[period_idx]
        n = len(self.data)
        idx = n - 1 - ago
        if idx < period:
            return 0.0
        highs = [float(self.data.high.array[i]) for i in range(idx - period + 1, idx + 1)]
        lows = [float(self.data.low.array[i]) for i in range(idx - period + 1, idx + 1)]
        close_val = float(self.data.close.array[idx])
        return _wpr(highs, lows, close_val, period)

    def next(self):
        risk = int(self.p.risk)
        x1 = self._x1
        x2 = self._x2

        # --- ATR-style average range (10 bars) ---
        total_range = 0.0
        for i in range(1, 11):
            hi = float(self.data.high[-i])
            lo = float(self.data.low[-i])
            prev_close = float(self.data.close[-(i + 1)]) if len(self.data) > i + 1 else lo
            true_range = max(hi - lo, abs(hi - prev_close), abs(prev_close - lo))
            total_range += true_range
        avg_range = total_range / 10.0
        half_range = avg_range * 0.5

        # --- MRO1 / MRO2: look back for WPR threshold breach ---
        value10 = self._value10
        value11 = value10

        # MRO1: check if WPR(3) crossed > x1 recently
        mro1 = -1
        for k in range(1, risk * 2 + 1):
            if len(self.data) <= k:
                break
            w = 100.0 - abs(self._get_wpr_val(0, k))  # WPR_Handle[0] period=3
            if w > x1:
                mro1 = k
                break

        # MRO2: check if WPR(4) crossed < x2 recently
        mro2 = -1
        for k in range(1, risk * 2 + 1):
            if len(self.data) <= k:
                break
            w = 100.0 - abs(self._get_wpr_val(1, k))  # WPR_Handle[1] period=4
            if w < x2:
                mro2 = k
                break

        if mro1 > -1:
            value11 = 0
        else:
            value11 = value10
        if mro2 > -1:
            value11 = 1
        else:
            value11 = value10

        # Current WPR value with the selected period
        wpr_raw = self._get_wpr_val(value11, 0)
        value2 = 100.0 - abs(wpr_raw)

        buy_val = 0.0
        sell_val = 0.0
        cur_high = float(self.data.high[0])
        cur_low = float(self.data.low[0])

        if value2 < x2:
            # look back for transition from neutral zone to >x1
            iii = 1
            vel = 0.0
            while len(self.data) > iii:
                vel = 100.0 - abs(self._get_wpr_val(value11, iii))
                if x2 <= vel <= x1:
                    iii += 1
                else:
                    break
            if vel > x1:
                sell_val = cur_high + half_range

        if value2 > x1:
            iii = 1
            vel = 0.0
            while len(self.data) > iii:
                vel = 100.0 - abs(self._get_wpr_val(value11, iii))
                if x2 <= vel <= x1:
                    iii += 1
                else:
                    break
            if vel < x2:
                buy_val = cur_low - half_range

        self.lines.buy_arrow[0] = buy_val
        self.lines.sell_arrow[0] = sell_val


class ExpASCtrendStrategy(bt.Strategy):
    params = dict(
        risk=4,
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
        self.indicator = ASCtrendIndicator(self.signal_data, risk=self.p.risk)
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
        """Replicate the EA's historical scan that closes positions when
        a past signal exists in the opposite direction."""
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
        if len(self.signal_data) < 12 + sig_bar + 2:
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

        # Historical scan for close (only when no direct close signal)
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
