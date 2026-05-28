from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

import pandas as pd

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
LOCAL_BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(LOCAL_BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(LOCAL_BACKTRADER_REPO))

import backtrader as bt


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=15):
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


def rolling_mean_from_signal(signal_series, history_series, period):
    total = signal_series.copy()
    for shift in range(1, period):
        total = total + history_series.shift(shift)
    return total / period


def build_signal_frame(
    filepath,
    fromdate=None,
    todate=None,
    bar_shift_minutes=15,
    minimum_indent=0.001,
):
    frame = load_mt5_csv(filepath, fromdate=fromdate, todate=todate, bar_shift_minutes=bar_shift_minutes).copy()
    median = (frame['high'] + frame['low']) / 2.0
    ao_closed = median.rolling(5).mean() - median.rolling(34).mean()
    ao_signal_current = rolling_mean_from_signal(frame['open'], median, 5) - rolling_mean_from_signal(frame['open'], median, 34)
    frame['ao_signal_current'] = ao_signal_current
    frame['ao_signal_prev'] = ao_closed.shift(1)
    frame['ao_signal_prev2'] = ao_closed.shift(2)
    frame['buy_signal'] = (
        (frame['ao_signal_current'] > frame['ao_signal_prev'])
        & (frame['ao_signal_prev'] < frame['ao_signal_prev2'])
        & (frame['ao_signal_current'] < -minimum_indent)
    )
    frame['sell_signal'] = (
        (frame['ao_signal_current'] < frame['ao_signal_prev'])
        & (frame['ao_signal_prev'] > frame['ao_signal_prev2'])
        & (frame['ao_signal_current'] > minimum_indent)
    )
    frame['close_buy_signal'] = frame['ao_signal_prev'] > 0.0
    frame['close_sell_signal'] = frame['ao_signal_prev'] < 0.0
    return frame.dropna(subset=['ao_signal_current', 'ao_signal_prev', 'ao_signal_prev2'])


class AoExecutorFeed(bt.feeds.PandasData):
    lines = (
        'ao_signal_current', 'ao_signal_prev', 'ao_signal_prev2', 'buy_signal', 'sell_signal', 'close_buy_signal', 'close_sell_signal',
    )
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('ao_signal_current', 6),
        ('ao_signal_prev', 7),
        ('ao_signal_prev2', 8),
        ('buy_signal', 9),
        ('sell_signal', 10),
        ('close_buy_signal', 11),
        ('close_sell_signal', 12),
    )


class AoExecutorStrategy(bt.Strategy):
    params = dict(
        stop_loss_points=50,
        take_profit_points=50,
        trailing_stop_points=5,
        trailing_step_points=5,
        lot_or_risk='lot',
        volume_or_risk=1.0,
        minimum_indent=0.001,
        point=0.01,
        margin_per_lot=250.0,
        lot_step=0.01,
        lot_min=0.01,
        lot_max=100.0,
    )

    def __init__(self):
        self.order = None
        self.current_stop = None
        self.current_take_profit = None
        self.pending_stop = None
        self.pending_take_profit = None
        self.pending_side = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        self.bar_num += 1

    def _normalize_lot(self, lot):
        step = self.p.lot_step
        lot = step * round(lot / step)
        lot = max(self.p.lot_min, min(self.p.lot_max, lot))
        return round(lot, 2)

    def trade_size(self):
        if str(self.p.lot_or_risk).lower() == 'lot':
            return self._normalize_lot(self.p.volume_or_risk)
        margin = self.p.margin_per_lot
        if margin <= 0:
            return 0.0
        cash = self.broker.getcash()
        lot = cash * (self.p.volume_or_risk / 100.0) / margin
        if lot <= 0:
            return 0.0
        return self._normalize_lot(lot)

    def _apply_trailing_long(self):
        if self.p.trailing_stop_points == 0 or not self.position or self.position.size <= 0:
            return
        high = float(self.data.high[-1])
        trailing_stop = self.p.trailing_stop_points * self.p.point
        trailing_step = self.p.trailing_step_points * self.p.point
        if high - self.position.price > trailing_stop + trailing_step:
            candidate = high - trailing_stop
            if self.current_stop is None or self.current_stop < high - (trailing_stop + trailing_step):
                self.current_stop = candidate

    def _apply_trailing_short(self):
        if self.p.trailing_stop_points == 0 or not self.position or self.position.size >= 0:
            return
        low = float(self.data.low[-1])
        trailing_stop = self.p.trailing_stop_points * self.p.point
        trailing_step = self.p.trailing_step_points * self.p.point
        if self.position.price - low > trailing_stop + trailing_step:
            candidate = low + trailing_stop
            if self.current_stop is None or self.current_stop > low + (trailing_stop + trailing_step):
                self.current_stop = candidate

    def _close_if_exit_hit(self):
        if not self.position:
            return False
        low = float(self.data.low[-1])
        high = float(self.data.high[-1])
        if self.position.size > 0:
            if self.current_stop is not None and low <= self.current_stop:
                self.log(f'close long stop={self.current_stop:.2f}')
                self.order = self.close()
                return True
            if self.current_take_profit is not None and high >= self.current_take_profit:
                self.log(f'close long take_profit={self.current_take_profit:.2f}')
                self.order = self.close()
                return True
            if bool(self.data.close_buy_signal[0]):
                self.log('close long ao_prev_above_zero')
                self.order = self.close()
                return True
        else:
            if self.current_stop is not None and high >= self.current_stop:
                self.log(f'close short stop={self.current_stop:.2f}')
                self.order = self.close()
                return True
            if self.current_take_profit is not None and low <= self.current_take_profit:
                self.log(f'close short take_profit={self.current_take_profit:.2f}')
                self.order = self.close()
                return True
            if bool(self.data.close_sell_signal[0]):
                self.log('close short ao_prev_below_zero')
                self.order = self.close()
                return True
        return False

    def next_open(self):
        if self.order:
            return
        if len(self.data) < 2:
            return

        if self.position:
            if self._close_if_exit_hit():
                return
            if self.position.size > 0:
                self._apply_trailing_long()
            else:
                self._apply_trailing_short()
            return

        size = self.trade_size()
        if size == 0.0:
            return

        entry_price = float(self.data.open[0])
        if bool(self.data.buy_signal[0]):
            self.pending_side = 'long'
            self.pending_stop = entry_price - self.p.stop_loss_points * self.p.point if self.p.stop_loss_points else None
            self.pending_take_profit = entry_price + self.p.take_profit_points * self.p.point if self.p.take_profit_points else None
            self.log(
                'buy '
                f'size={size:.2f} '
                f'open={entry_price:.2f} '
                f'ao0={float(self.data.ao_signal_current[0]):.4f} '
                f'ao1={float(self.data.ao_signal_prev[0]):.4f} '
                f'ao2={float(self.data.ao_signal_prev2[0]):.4f}'
            )
            self.order = self.buy(size=size)
            return

        if bool(self.data.sell_signal[0]):
            self.pending_side = 'short'
            self.pending_stop = entry_price + self.p.stop_loss_points * self.p.point if self.p.stop_loss_points else None
            self.pending_take_profit = entry_price - self.p.take_profit_points * self.p.point if self.p.take_profit_points else None
            self.log(
                'sell '
                f'size={size:.2f} '
                f'open={entry_price:.2f} '
                f'ao0={float(self.data.ao_signal_current[0]):.4f} '
                f'ao1={float(self.data.ao_signal_prev[0]):.4f} '
                f'ao2={float(self.data.ao_signal_prev2[0]):.4f}'
            )
            self.order = self.sell(size=size)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if self.pending_side == 'long' and self.position.size > 0:
                self.buy_count += 1
                self.current_stop = self.pending_stop
                self.current_take_profit = self.pending_take_profit
            elif self.pending_side == 'short' and self.position.size < 0:
                self.sell_count += 1
                self.current_stop = self.pending_stop
                self.current_take_profit = self.pending_take_profit
            elif self.position.size == 0:
                self.current_stop = None
                self.current_take_profit = None
        self.order = None
        self.pending_stop = None
        self.pending_take_profit = None
        self.pending_side = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
