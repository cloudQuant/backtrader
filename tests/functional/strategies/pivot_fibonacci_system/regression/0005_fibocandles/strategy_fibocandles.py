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


FIBO_LEVELS = {1: 0.236, 2: 0.382, 3: 0.500, 4: 0.618, 5: 0.762}


class FiboCandlesIndicator(bt.Indicator):
    """Reconstructs the FiboCandles indicator from MQ5 source.

    Uses period-bar high/low range * fibo level to detect trend flips.
    color line: 0 = bullish (trend +1), 1 = bearish (trend -1).
    """
    lines = ('color',)
    params = dict(period=10, fibo_level=1)

    def __init__(self):
        self._level = FIBO_LEVELS.get(int(self.p.fibo_level), 0.236)
        self._trend = 1
        self.addminperiod(int(self.p.period) + 1)

    def next(self):
        period = int(self.p.period)
        level = self._level

        # maxHigh / minLow over [bar, bar+period) in MQ5 (as-series)
        # In backtrader forward indexing: last `period` bars including current
        max_high = max(float(self.data.high[-i]) for i in range(period))
        min_low = min(float(self.data.low[-i]) for i in range(period))
        rng = max_high - min_low

        o = float(self.data.open[0])
        c = float(self.data.close[0])
        h = float(self.data.high[0])
        l = float(self.data.low[0])
        trend = self._trend

        if o > c:  # bearish candle
            if not (trend < 0 and rng * level < c - min_low):
                trend = 1
            else:
                trend = -1
        else:  # bullish candle
            if not (trend > 0 and rng * level < max_high - c):
                trend = -1
            else:
                trend = 1

        # Color assignment
        if trend == 1:
            open_buf = max(o, c)
            close_buf = min(o, c)
        else:
            open_buf = min(o, c)
            close_buf = max(o, c)

        if open_buf > close_buf:
            self.lines.color[0] = 1.0  # bearish color
        else:
            self.lines.color[0] = 0.0  # bullish color

        self._trend = trend


class ExpFiboCandlesStrategy(bt.Strategy):
    params = dict(
        period=10,
        fibo_level=1,
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
        self.indicator = FiboCandlesIndicator(
            self.signal_data, period=self.p.period, fibo_level=self.p.fibo_level,
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
                prev_c = float(self.indicator.color[-(k + 1)]) if k + 1 < len(self.signal_data) else float(self.indicator.color[-k])
                cur_c = float(self.indicator.color[-k])
                if not math.isnan(prev_c) and not math.isnan(cur_c):
                    if cur_c == 1.0 and prev_c == 0.0:
                        self.log(f'close short by historical buy signal at -{k}')
                        self.close()
                        return

        if self.position.size > 0 and self.p.buy_pos_close:
            for k in range(sig_bar + 1, sig_bar + max_look):
                if k >= len(self.signal_data):
                    break
                prev_c = float(self.indicator.color[-(k + 1)]) if k + 1 < len(self.signal_data) else float(self.indicator.color[-k])
                cur_c = float(self.indicator.color[-k])
                if not math.isnan(prev_c) and not math.isnan(cur_c):
                    if cur_c == 0.0 and prev_c == 1.0:
                        self.log(f'close long by historical sell signal at -{k}')
                        self.close()
                        return

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return

        if self._check_exit_levels():
            return

        sig_bar = max(int(self.p.signal_bar), 1)
        min_needed = int(self.p.period) + sig_bar + 3
        if len(self.signal_data) < min_needed:
            return

        current_signal_len = len(self.signal_data)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        # Read color at SignalBar and SignalBar+1
        idx0 = sig_bar - 1  # current signal bar (0-indexed ago)
        idx1 = sig_bar       # previous signal bar
        c0 = float(self.indicator.color[-idx0]) if idx0 > 0 else float(self.indicator.color[0])
        c1 = float(self.indicator.color[-idx1])
        if math.isnan(c0) or math.isnan(c1):
            return

        close_price = float(self.base.close[0])
        size = float(self.p.fixed_lot)
        if size <= 0:
            return

        BUY_Open = False
        SELL_Open = False
        BUY_Close = False
        SELL_Close = False

        # color 1->0: buy (bearish to bullish)
        if c0 == 1.0 and c1 == 0.0:
            if self.p.buy_pos_open:
                BUY_Open = True
            if self.p.sell_pos_close:
                SELL_Close = True

        # color 0->1: sell (bullish to bearish)
        if c0 == 0.0 and c1 == 1.0:
            if self.p.sell_pos_open:
                SELL_Open = True
            if self.p.buy_pos_close:
                BUY_Close = True

        if not BUY_Close and not SELL_Close:
            if self.position.size < 0 and self.p.sell_pos_open and self.p.sell_pos_close and c1 == 0.0:
                SELL_Close = True
            if self.position.size > 0 and self.p.buy_pos_open and self.p.buy_pos_close and c1 == 1.0:
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
            self.log(f'buy signal close={close_price:.5f}')
            if self.position.size <= 0:
                self.buy(size=size)

        if SELL_Open:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.5f}')
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
