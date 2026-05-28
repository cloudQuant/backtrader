from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
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


def signal_ma_from_open_and_prev_closes(frame, period):
    total = frame['open'].copy()
    for shift in range(1, period):
        total = total + frame['close'].shift(shift)
    return total / period


def signal_cci_from_open(frame, period):
    typical = (frame['high'] + frame['low'] + frame['close']) / 3.0
    signal_tp = frame['open']
    samples = [signal_tp]
    for shift in range(1, period):
        samples.append(typical.shift(shift))
    window = pd.concat(samples, axis=1)
    sma = window.mean(axis=1)
    mean_dev = window.sub(sma, axis=0).abs().mean(axis=1)
    denominator = 0.015 * mean_dev.replace(0, pd.NA)
    return (signal_tp - sma) / denominator


def closed_bar_cci(frame, period):
    typical = (frame['high'] + frame['low'] + frame['close']) / 3.0
    sma = typical.rolling(period).mean()
    mad = typical.rolling(period).apply(lambda s: (s - s.mean()).abs().mean(), raw=False)
    return (typical - sma) / (0.015 * mad.replace(0, pd.NA))


def build_signal_frame(
    filepath,
    fromdate=None,
    todate=None,
    bar_shift_minutes=15,
    cci_period=14,
    cci_level=100,
    ma_period=120,
    ma_delta=0.001,
):
    frame = load_mt5_csv(filepath, fromdate=fromdate, todate=todate, bar_shift_minutes=bar_shift_minutes).copy()
    frame['cci_signal_current'] = signal_cci_from_open(frame, cci_period)
    frame['cci_signal_prev'] = closed_bar_cci(frame, cci_period).shift(1)
    frame['ma_signal_current'] = signal_ma_from_open_and_prev_closes(frame, ma_period)
    frame['ma_signal_prev'] = frame['close'].rolling(ma_period).mean().shift(1)
    frame = frame.dropna(subset=['cci_signal_current', 'cci_signal_prev', 'ma_signal_current', 'ma_signal_prev']).copy()
    cci_rising = frame['cci_signal_prev'].lt(frame['cci_signal_current']).fillna(False)
    cci_falling = frame['cci_signal_prev'].gt(frame['cci_signal_current']).fillna(False)
    frame['buy_signal'] = (
        (frame['ma_signal_current'] - frame['ma_signal_prev'] > ma_delta)
        & cci_rising
        & (frame['cci_signal_current'].fillna(0).astype(int) > -cci_level)
        & (frame['cci_signal_prev'].fillna(0).astype(int) < -cci_level)
    )
    frame['sell_signal'] = (
        (frame['ma_signal_current'] - frame['ma_signal_prev'] < -ma_delta)
        & cci_falling
        & (frame['cci_signal_current'].fillna(0).astype(int) < cci_level)
        & (frame['cci_signal_prev'].fillna(0).astype(int) > cci_level)
    )
    return frame


class StarterFeed(bt.feeds.PandasData):
    lines = (
        'cci_signal_current', 'cci_signal_prev', 'ma_signal_current', 'ma_signal_prev', 'buy_signal', 'sell_signal',
    )
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('cci_signal_current', 6),
        ('cci_signal_prev', 7),
        ('ma_signal_current', 8),
        ('ma_signal_prev', 9),
        ('buy_signal', 10),
        ('sell_signal', 11),
    )


class StarterStrategy(bt.Strategy):
    params = dict(
        maximum_risk=0.02,
        decrease_factor=3.0,
        history_days=60,
        stop_loss_points=0,
        trailing_stop_points=5,
        trailing_step_points=5,
        cci_level=100,
        ma_delta=0.001,
        point=0.01,
        margin_per_lot=250.0,
        lot_step=0.01,
        lot_min=0.01,
        lot_max=100.0,
        cci_period=14,
        ma_period=120,
    )

    def __init__(self):
        self.order = None
        self.current_stop = None
        self.pending_stop = None
        self.pending_side = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.closed_trades = []

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

    def _consecutive_losses(self):
        if not self.closed_trades:
            return 0
        cutoff = bt.num2date(self.data.datetime[0]) - pd.Timedelta(days=self.p.history_days)
        losses = 0
        for trade_dt, pnl in reversed(self.closed_trades):
            if trade_dt < cutoff:
                break
            if pnl < 0:
                losses += 1
                continue
            break
        return losses

    def trade_size_optimized(self):
        cash = self.broker.getcash()
        margin = self.p.margin_per_lot
        if margin <= 0:
            return 0.0
        lot = cash * self.p.maximum_risk / margin
        if self.p.decrease_factor > 0:
            losses = self._consecutive_losses()
            if losses > 1:
                lot = lot - lot * losses / self.p.decrease_factor
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

    def _close_if_stop_hit(self):
        if not self.position or self.current_stop is None:
            return False
        low = float(self.data.low[-1])
        high = float(self.data.high[-1])
        if self.position.size > 0 and low <= self.current_stop:
            self.log(f'close long stop={self.current_stop:.2f}')
            self.order = self.close()
            return True
        if self.position.size < 0 and high >= self.current_stop:
            self.log(f'close short stop={self.current_stop:.2f}')
            self.order = self.close()
            return True
        return False

    def next_open(self):
        if self.order:
            return
        if len(self.data) < 2:
            return

        if self.position:
            if self._close_if_stop_hit():
                return
            if self.position.size > 0:
                self._apply_trailing_long()
            else:
                self._apply_trailing_short()
            return

        lot = self.trade_size_optimized()
        if lot == 0.0:
            return

        entry_price = float(self.data.open[0])
        if bool(self.data.buy_signal[0]):
            self.pending_side = 'long'
            self.pending_stop = entry_price - self.p.stop_loss_points * self.p.point if self.p.stop_loss_points else None
            self.log(
                'buy '
                f'size={lot:.2f} '
                f'open={entry_price:.2f} '
                f'cci_cur={float(self.data.cci_signal_current[0]):.2f} '
                f'cci_prev={float(self.data.cci_signal_prev[0]):.2f} '
                f'ma_delta={(float(self.data.ma_signal_current[0]) - float(self.data.ma_signal_prev[0])):.4f}'
            )
            self.order = self.buy(size=lot)
            return

        if bool(self.data.sell_signal[0]):
            self.pending_side = 'short'
            self.pending_stop = entry_price + self.p.stop_loss_points * self.p.point if self.p.stop_loss_points else None
            self.log(
                'sell '
                f'size={lot:.2f} '
                f'open={entry_price:.2f} '
                f'cci_cur={float(self.data.cci_signal_current[0]):.2f} '
                f'cci_prev={float(self.data.cci_signal_prev[0]):.2f} '
                f'ma_delta={(float(self.data.ma_signal_current[0]) - float(self.data.ma_signal_prev[0])):.4f}'
            )
            self.order = self.sell(size=lot)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if self.pending_side == 'long' and self.position.size > 0:
                self.buy_count += 1
                self.current_stop = self.pending_stop
            elif self.pending_side == 'short' and self.position.size < 0:
                self.sell_count += 1
                self.current_stop = self.pending_stop
            elif self.position.size == 0:
                self.current_stop = None
        self.order = None
        self.pending_stop = None
        self.pending_side = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        trade_dt = bt.num2date(self.data.datetime[0])
        self.closed_trades.append((trade_dt, trade.pnlcomm))
        if trade.pnlcomm > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
