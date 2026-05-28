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
import backtrader.feeds as btfeeds
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
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
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class AdaptiveMarketLevel(bt.Indicator):
    lines = ('aml',)
    params = dict(
        fractal=70,
        lag=18,
        shift=0,
        point=0.01,
    )

    def __init__(self):
        self._smooth_history = []
        self._aml_history = []
        self._min_period = max(int(self.p.fractal) * 2 + int(self.p.lag), 1)

    def _range(self, count, start):
        highs = []
        lows = []
        for idx in range(start, start + count):
            ago = -idx if idx else 0
            highs.append(float(self.data.high[ago]))
            lows.append(float(self.data.low[ago]))
        return max(highs) - min(lows)

    def next(self):
        fractal = int(self.p.fractal)
        lag = int(self.p.lag)
        if len(self.data) < self._min_period:
            self.lines.aml[0] = float(self.data.close[0])
            return
        r1 = self._range(fractal, 0) / fractal
        r2 = self._range(fractal, fractal) / fractal
        r3 = self._range(fractal * 2, 0) / (fractal * 2)
        dim = 0.0
        if r1 + r2 > 0 and r3 > 0:
            dim = (math.log(r1 + r2) - math.log(r3)) * 1.44269504088896
        alpha = math.exp(-lag * (dim - 1.0))
        alpha = min(max(alpha, 0.01), 1.0)
        price = (
            float(self.data.high[0])
            + float(self.data.low[0])
            + 2.0 * float(self.data.open[0])
            + 2.0 * float(self.data.close[0])
        ) / 6.0
        prev_smooth = self._smooth_history[-1] if self._smooth_history else 0.0
        smooth = alpha * price + (1.0 - alpha) * prev_smooth
        lagged_smooth = self._smooth_history[-lag] if len(self._smooth_history) >= lag else 0.0
        prev_aml = self._aml_history[-1] if self._aml_history else smooth
        threshold = lag * lag * float(self.p.point)
        aml = smooth if abs(smooth - lagged_smooth) >= threshold else prev_aml
        self._smooth_history.append(smooth)
        self._aml_history.append(aml)
        self.lines.aml[0] = aml


class EaAmlStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        tp=3500.0,
        sl=500.0,
        use_opposite=True,
        use_multpl=False,
        max_drawdown=1800.0,
        fractal=70,
        lag=18,
        shift=0,
        point=0.01,
        max_lot=None,
    )

    def __init__(self):
        self.aml = AdaptiveMarketLevel(
            self.data,
            fractal=self.p.fractal,
            lag=self.p.lag,
            shift=self.p.shift,
            point=self.p.point,
        )
        self.order = None
        self.pending_reverse = None
        self.stop_price = None
        self.take_price = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _current_lot(self):
        lot = float(self.p.lots)
        if bool(self.p.use_multpl):
            max_drawdown = max(float(self.p.max_drawdown), 1e-9)
            lot = round(lot * float(self.broker.getcash()) / max_drawdown, 2)
        if self.p.max_lot is not None:
            lot = min(lot, float(self.p.max_lot))
        return max(round(lot, 2), 0.0)

    def _set_exit_levels(self, is_long, entry_price):
        point = float(self.p.point)
        self.stop_price = None
        self.take_price = None
        if float(self.p.sl) > 0:
            self.stop_price = entry_price - float(self.p.sl) * point if is_long else entry_price + float(self.p.sl) * point
        if float(self.p.tp) > 0:
            self.take_price = entry_price + float(self.p.tp) * point if is_long else entry_price - float(self.p.tp) * point

    def _clear_exit_levels(self):
        self.stop_price = None
        self.take_price = None

    def _enter(self, direction):
        if self.order is not None:
            return
        lot = self._current_lot()
        if lot <= 0:
            return
        if direction > 0:
            self.log(f'open long size={lot:.2f}')
            self.order = self.buy(size=lot)
        else:
            self.log(f'open short size={lot:.2f}')
            self.order = self.sell(size=lot)

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.2f}')
                self.pending_reverse = None
                self.order = self.close()
                return True
            if self.take_price is not None and high >= self.take_price:
                self.log(f'close long by take={self.take_price:.2f}')
                self.pending_reverse = None
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.2f}')
                self.pending_reverse = None
                self.order = self.close()
                return True
            if self.take_price is not None and low <= self.take_price:
                self.log(f'close short by take={self.take_price:.2f}')
                self.pending_reverse = None
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(int(self.p.fractal) * 2 + int(self.p.lag), 3):
            return
        if self.order is not None:
            return
        if self.pending_reverse is not None and not self.position:
            direction = self.pending_reverse
            self.pending_reverse = None
            self._enter(direction)
            return
        if self._check_exit_levels():
            return
        aml_prev = float(self.aml[-1])
        open_prev = float(self.data.open[-1])
        close_prev = float(self.data.close[-1])
        bullish_signal = aml_prev >= open_prev and aml_prev <= close_prev
        bearish_signal = aml_prev <= open_prev and aml_prev >= close_prev
        if not self.position:
            if bullish_signal:
                self._enter(1)
                return
            if bearish_signal:
                self._enter(-1)
                return
            return
        if not bool(self.p.use_opposite):
            return
        if self.position.size > 0 and bearish_signal:
            self.log('reverse long to short')
            self.pending_reverse = -1
            self.order = self.close()
            return
        if self.position.size < 0 and bullish_signal:
            self.log('reverse short to long')
            self.pending_reverse = 1
            self.order = self.close()

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if self.position:
                self._set_exit_levels(self.position.size > 0, float(order.executed.price))
            else:
                self._clear_exit_levels()
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
            if not self.position:
                self.pending_reverse = None
        self.order = None

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
        self._clear_exit_levels()
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
