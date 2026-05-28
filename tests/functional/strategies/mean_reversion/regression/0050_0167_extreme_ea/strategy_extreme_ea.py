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
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def smma(series, period):
    values = [math.nan] * len(series)
    data = series.tolist()
    if len(data) < period:
        return pd.Series(values, index=series.index, dtype=float)
    seed = sum(data[:period]) / float(period)
    values[period - 1] = seed
    prev = seed
    for idx in range(period, len(data)):
        prev = (prev * (period - 1) + data[idx]) / float(period)
        values[idx] = prev
    return pd.Series(values, index=series.index, dtype=float)


def cci(series_high, series_low, series_close, period):
    tp = (series_high + series_low + series_close) / 3.0
    sma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: pd.Series(x).sub(pd.Series(x).mean()).abs().mean(), raw=False)
    return (tp - sma) / (0.015 * mad.replace(0, math.nan))


def resample_ohlcv(df, minutes):
    rule = f'{int(minutes)}min'
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
        'spread': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close']).copy()
    out['openinterest'] = out['openinterest'].fillna(0)
    out['spread'] = out['spread'].fillna(0)
    return out


def build_signal_frame(df, cci_minutes, cci_period, cci_up_level, cci_down_level, ma_fast_period, ma_slow_period):
    frame = df.copy()
    median_price = (frame['high'] + frame['low']) / 2.0
    frame['ma_fast'] = smma(median_price, ma_fast_period)
    frame['ma_slow'] = smma(median_price, ma_slow_period)
    cci_frame = resample_ohlcv(df, cci_minutes)
    cci_frame['cci'] = cci(cci_frame['high'], cci_frame['low'], cci_frame['close'], cci_period)
    frame['cci'] = cci_frame['cci'].reindex(frame.index, method='ffill')
    frame = frame.dropna(subset=['ma_fast', 'ma_slow', 'cci']).copy()
    frame['long_signal'] = (
        frame['ma_slow'].shift(1) > frame['ma_slow'].shift(2)
    ) & (
        frame['ma_fast'] > frame['ma_fast'].shift(1)
    ) & (
        frame['cci'].astype(int) < int(cci_down_level)
    )
    frame['long_exit'] = frame['ma_slow'].shift(1) <= frame['ma_slow'].shift(2)
    frame['short_signal'] = (
        frame['ma_slow'].shift(1) < frame['ma_slow'].shift(2)
    ) & (
        frame['ma_fast'] < frame['ma_fast'].shift(1)
    ) & (
        frame['cci'].astype(int) > int(cci_up_level)
    )
    frame['short_exit'] = frame['ma_slow'].shift(1) >= frame['ma_slow'].shift(2)
    return frame


class Mt5PandasFeed(btfeeds.PandasData):
    lines = ('spread', 'long_signal', 'short_signal', 'long_exit', 'short_exit')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6), ('long_signal', 7), ('short_signal', 8), ('long_exit', 9), ('short_exit', 10),
    )


class ExtremeEaStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stoploss_pips=50,
        takeprofit_pips=50,
        trailing_stop_pips=5,
        trailing_step_pips=5,
        history_days=60,
        max_positions=3,
        cci_period=12,
        cci_up_level=50,
        cci_down_level=-50,
        ma_fast_period=15,
        ma_slow_period=75,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_reverse = None
        self.active_side = None
        self.active_stop_price = None
        self.last_bar_dt = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _new_bar(self):
        current = bt.num2date(self.data0_feed.datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _place_exit_orders(self):
        if not self.position:
            return
        size = abs(self.position.size)
        stop_distance = self.p.stoploss_pips * self.p.point_size
        take_distance = self.p.takeprofit_pips * self.p.point_size
        if self.position.size > 0:
            stop_price = self.position.price - stop_distance if self.p.stoploss_pips > 0 else None
            take_price = self.position.price + take_distance if self.p.takeprofit_pips > 0 else None
            if stop_price is not None:
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=stop_price)
                self.active_stop_price = stop_price
            if take_price is not None:
                self.limit_order = self.sell(size=size, exectype=bt.Order.Limit, price=take_price, oco=self.stop_order)
        else:
            stop_price = self.position.price + stop_distance if self.p.stoploss_pips > 0 else None
            take_price = self.position.price - take_distance if self.p.takeprofit_pips > 0 else None
            if stop_price is not None:
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=stop_price)
                self.active_stop_price = stop_price
            if take_price is not None:
                self.limit_order = self.buy(size=size, exectype=bt.Order.Limit, price=take_price, oco=self.stop_order)

    def _apply_trailing(self):
        if not self.position or self.p.trailing_stop_pips <= 0 or self.p.trailing_step_pips <= 0 or self.stop_order is None:
            return
        trail_stop = self.p.trailing_stop_pips * self.p.point_size
        trail_step = self.p.trailing_step_pips * self.p.point_size
        current_price = float(self.data0_feed.close[0])
        size = abs(self.position.size)
        if self.position.size > 0:
            if current_price - self.position.price <= trail_stop + trail_step:
                return
            candidate = current_price - trail_stop
            if self.active_stop_price is None or candidate > self.active_stop_price + trail_step:
                self.cancel(self.stop_order)
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=candidate, oco=self.limit_order)
                self.active_stop_price = candidate
        else:
            if self.position.price - current_price <= trail_stop + trail_step:
                return
            candidate = current_price + trail_stop
            if self.active_stop_price is None or candidate < self.active_stop_price - trail_step:
                self.cancel(self.stop_order)
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=candidate, oco=self.limit_order)
                self.active_stop_price = candidate

    def _submit_entry(self, side, reason):
        if self.position or self.entry_order is not None or self.close_order is not None:
            return
        size = max(0.01, float(self.p.fixed_lot))
        self.entry_order = self.buy(size=size) if side == 'long' else self.sell(size=size)
        self.log(f'OPEN {side.upper()} size={size} reason={reason}')

    def _submit_close(self, reason, reverse=None):
        if not self.position or self.close_order is not None:
            return
        self.pending_reverse = reverse
        self._cancel_exit_orders()
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason} reverse={reverse}')

    def next(self):
        self.bar_num += 1
        self._apply_trailing()
        if len(self.data0_feed) < 20:
            return
        if not self._new_bar():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        long_signal = bool(self.data0_feed.long_signal[0])
        short_signal = bool(self.data0_feed.short_signal[0])
        long_exit = bool(self.data0_feed.long_exit[0])
        short_exit = bool(self.data0_feed.short_exit[0])
        if self.position.size > 0 and long_exit:
            self._submit_close('slow ma lost upward slope', reverse='short' if short_signal else None)
            return
        if self.position.size < 0 and short_exit:
            self._submit_close('slow ma lost downward slope', reverse='long' if long_signal else None)
            return
        if not self.position:
            if long_signal:
                self._submit_entry('long', 'ma up + cci below down level')
            elif short_signal:
                self._submit_entry('short', 'ma down + cci above up level')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                if order.executed.size > 0:
                    self.buy_count += 1
                else:
                    self.sell_count += 1
                self.entry_order = None
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self._place_exit_orders()
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
                self.active_stop_price = None
                reverse = self.pending_reverse
                self.pending_reverse = None
                if reverse is not None and not self.position:
                    self._submit_entry(reverse, 'reverse after close')
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
                self.active_stop_price = None
            elif order == self.limit_order:
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
                self.active_side = None
                self.active_stop_price = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None
                self.pending_reverse = None
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'TRADE CLOSED side={self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
