from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
from collections import deque

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


class AmlSignalFeed(btfeeds.PandasData):
    lines = ('aml',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('aml', 6),
    )


def build_aml_signal_frame(df, fractal, lag, point):
    fractal = max(1, int(fractal))
    lag = max(1, int(lag))
    point = float(point)
    signal_df = df.copy()
    highs = signal_df['high'].astype(float).tolist()
    lows = signal_df['low'].astype(float).tolist()
    opens = signal_df['open'].astype(float).tolist()
    closes = signal_df['close'].astype(float).tolist()
    aml_values = []
    smooth_values = []
    for idx in range(len(signal_df)):
        price = (highs[idx] + lows[idx] + 2.0 * opens[idx] + 2.0 * closes[idx]) / 6.0
        if idx < fractal * 2:
            aml_values.append(price)
            smooth_values.append(price)
            continue
        recent_high = max(highs[idx - fractal + 1: idx + 1])
        recent_low = min(lows[idx - fractal + 1: idx + 1])
        prior_high = max(highs[idx - 2 * fractal + 1: idx - fractal + 1])
        prior_low = min(lows[idx - 2 * fractal + 1: idx - fractal + 1])
        full_high = max(highs[idx - 2 * fractal + 1: idx + 1])
        full_low = min(lows[idx - 2 * fractal + 1: idx + 1])
        r1 = (recent_high - recent_low) / fractal
        r2 = (prior_high - prior_low) / fractal
        r3 = (full_high - full_low) / (2 * fractal)
        dim = 0.0
        if r1 + r2 > 0 and r3 > 0:
            dim = (math.log(r1 + r2) - math.log(r3)) / math.log(2.0)
        alpha = math.exp(-lag * (dim - 1.0))
        alpha = min(1.0, max(0.01, alpha))
        prev_smooth = smooth_values[-1] if smooth_values else 0.0
        smooth = alpha * price + (1.0 - alpha) * prev_smooth
        lagged_smooth = smooth_values[-(lag + 1)] if len(smooth_values) >= lag + 1 else 0.0
        prev_aml = aml_values[-1] if aml_values else smooth
        aml = smooth if abs(smooth - lagged_smooth) >= lag * lag * point else prev_aml
        smooth_values.append(smooth)
        aml_values.append(aml)
    signal_df['aml'] = aml_values
    return signal_df


class AmlIndicator(bt.Indicator):
    lines = ('aml',)
    params = dict(
        fractal=70,
        lag=18,
        shift=0,
        point=0.01,
    )

    def __init__(self):
        lag = max(1, int(self.p.lag))
        fractal = max(1, int(self.p.fractal))
        self._smooth = deque(maxlen=lag + 1)
        self.addminperiod(max(fractal * 2 + 2, lag + 2))

    def _range(self, start, count):
        highs = [float(self.data.high[-(start + i)]) for i in range(count)]
        lows = [float(self.data.low[-(start + i)]) for i in range(count)]
        return max(highs) - min(lows)

    def next(self):
        fractal = max(1, int(self.p.fractal))
        lag = max(1, int(self.p.lag))
        price = (
            float(self.data.high[0])
            + float(self.data.low[0])
            + 2.0 * float(self.data.open[0])
            + 2.0 * float(self.data.close[0])
        ) / 6.0

        if len(self.data) < fractal * 2 + 1:
            self._smooth.append(price)
            self.lines.aml[0] = float(self.lines.aml[-1]) if len(self) > 1 else price
            return

        r1 = self._range(0, fractal) / fractal
        r2 = self._range(fractal, fractal) / fractal
        r3 = self._range(0, fractal * 2) / (fractal * 2)

        dim = 0.0
        if r1 + r2 > 0 and r3 > 0:
            dim = (math.log(r1 + r2) - math.log(r3)) / math.log(2.0)

        alpha = math.exp(-lag * (dim - 1.0))
        alpha = min(1.0, max(0.01, alpha))

        prev_smooth = self._smooth[-1] if self._smooth else 0.0
        smooth = alpha * price + (1.0 - alpha) * prev_smooth
        lagged_smooth = self._smooth[0] if len(self._smooth) == self._smooth.maxlen else 0.0
        self._smooth.append(smooth)

        if abs(smooth - lagged_smooth) >= lag * lag * float(self.p.point):
            self.lines.aml[0] = smooth
        else:
            self.lines.aml[0] = float(self.lines.aml[-1]) if len(self) > 1 else smooth


class EaAmlStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        tp=3500.0,
        sl=500.0,
        use_opposite=True,
        use_multpl=False,
        max_drawdown=1800.0,
        max_lot=50.0,
        point=0.01,
        fractal=70,
        lag=18,
        shift=0,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal = self.datas[1]
        self.aml = self.signal.aml
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.order = None
        self.pending_entry_side = None
        self.stop_price = None
        self.take_price = None
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _current_lot(self):
        lot = float(self.p.lots)
        if bool(self.p.use_multpl) and float(self.p.max_drawdown) > 0:
            lot = round(lot * float(self.broker.getcash()) / float(self.p.max_drawdown), 2)
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

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.2f}')
                self.order = self.close()
                return True
            if self.take_price is not None and high >= self.take_price:
                self.log(f'close long by take={self.take_price:.2f}')
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.2f}')
                self.order = self.close()
                return True
            if self.take_price is not None and low <= self.take_price:
                self.log(f'close short by take={self.take_price:.2f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.fractal) * 2 + 2, int(self.p.lag) + 3)
        if len(self.base) < warmup or len(self.signal) < warmup:
            return
        if self.order is not None:
            return

        if not self.position and self.pending_entry_side is not None:
            lot = self._current_lot()
            if self.pending_entry_side == 'long':
                self.log(f'pending buy lot={lot:.2f}')
                self.order = self.buy(size=lot)
            else:
                self.log(f'pending sell lot={lot:.2f}')
                self.order = self.sell(size=lot)
            self.pending_entry_side = None
            return

        if self._check_exit_levels():
            return

        aml_prev = float(self.aml[-1])
        open_prev = float(self.base.open[-1])
        close_prev = float(self.base.close[-1])
        buy_signal = aml_prev >= open_prev and aml_prev <= close_prev
        sell_signal = aml_prev <= open_prev and aml_prev >= close_prev
        if buy_signal or sell_signal:
            self.signal_count += 1
        lot = self._current_lot()

        if not self.position:
            if buy_signal:
                self.log(f'buy signal aml={aml_prev:.5f} open={open_prev:.5f} close={close_prev:.5f} lot={lot:.2f}')
                self.order = self.buy(size=lot)
                return
            if sell_signal:
                self.log(f'sell signal aml={aml_prev:.5f} open={open_prev:.5f} close={close_prev:.5f} lot={lot:.2f}')
                self.order = self.sell(size=lot)
                return
            return

        if not bool(self.p.use_opposite):
            return

        if self.position.size > 0 and sell_signal:
            self.log(f'reverse long->short aml={aml_prev:.5f} open={open_prev:.5f} close={close_prev:.5f}')
            self.pending_entry_side = 'short'
            self.order = self.close()
            return

        if self.position.size < 0 and buy_signal:
            self.log(f'reverse short->long aml={aml_prev:.5f} open={open_prev:.5f} close={close_prev:.5f}')
            self.pending_entry_side = 'long'
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
                self.pending_entry_side = None
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
