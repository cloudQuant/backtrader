from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
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
        '<VOL>': 'real_volume',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'real_volume']]
    df['openinterest'] = 0
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def resample_frame(df, rule):
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'real_volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


def weighted_moving_average(series, period):
    period = int(max(period, 1))
    weights = np.arange(1, period + 1, dtype=float)
    return series.rolling(period).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)


def smma(series, period):
    period = int(max(period, 1))
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    if len(values) < period:
        return pd.Series(out, index=series.index)
    seed = np.nanmean(values[:period])
    out[period - 1] = seed
    for idx in range(period, len(values)):
        prev = out[idx - 1]
        curr = values[idx]
        if np.isnan(prev) or np.isnan(curr):
            continue
        out[idx] = (prev * (period - 1) + curr) / period
    return pd.Series(out, index=series.index)


def smooth_series(series, method, period):
    method = str(method or 'MODE_T3').upper()
    period = int(max(period, 1))
    if method in ('MODE_SMA', 'MODE_SMA_'):
        return series.rolling(period).mean()
    if method in ('MODE_EMA', 'MODE_EMA_'):
        return series.ewm(span=period, adjust=False).mean()
    if method in ('MODE_SMMA', 'MODE_SMMA_'):
        return smma(series, period)
    return weighted_moving_average(series, period)


def compute_bnb(frame, xma_method='MODE_T3', xlength=14, xphase=15, volume_type='VOLUME_TICK'):
    use_tick = str(volume_type or 'VOLUME_TICK').upper() == 'VOLUME_TICK'
    vol = frame['volume'] if use_tick else frame['real_volume']
    vol = vol.replace(0, np.nan).fillna(1.0)
    tic = (frame['high'] - frame['low']) / vol
    tic = tic.replace(0, np.nan).fillna(1.0)
    diff = pd.Series(0.0, index=frame.index)
    open_gt_close = frame['open'] > frame['close']
    open_lt_close = frame['open'] < frame['close']
    diff.loc[open_gt_close] = ((frame.loc[open_gt_close, 'high'] - frame.loc[open_gt_close, 'low']) - (frame.loc[open_gt_close, 'open'] - frame.loc[open_gt_close, 'close'])) / (2.0 * tic.loc[open_gt_close])
    diff.loc[open_lt_close] = ((frame.loc[open_lt_close, 'high'] - frame.loc[open_lt_close, 'low']) - (frame.loc[open_lt_close, 'close'] - frame.loc[open_lt_close, 'open'])) / (2.0 * tic.loc[open_lt_close])
    bulls = pd.Series(diff, index=frame.index)
    bears = pd.Series(diff, index=frame.index)
    bulls.loc[open_gt_close] = (frame.loc[open_gt_close, 'open'] - frame.loc[open_gt_close, 'close']) / tic.loc[open_gt_close] + diff.loc[open_gt_close]
    bears.loc[open_lt_close] = (frame.loc[open_lt_close, 'close'] - frame.loc[open_lt_close, 'open']) / tic.loc[open_lt_close] + diff.loc[open_lt_close]
    up = smooth_series(bulls, xma_method, xlength)
    dn = smooth_series(bears, xma_method, xlength)
    out = frame.copy()
    out['up_buffer'] = up
    out['dn_buffer'] = dn
    return out.dropna(subset=['up_buffer', 'dn_buffer'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 6),
    )


class BnBFeed(bt.feeds.PandasData):
    lines = ('up_buffer', 'dn_buffer')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 6),
        ('up_buffer', 7), ('dn_buffer', 8),
    )


class BnBStrategy(bt.Strategy):
    params = dict(
        mm=0.1,
        mm_mode='LOT',
        stop_loss=1000,
        take_profit=2000,
        deviation=10,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        xma_method='MODE_T3',
        xlength=14,
        xphase=15,
        volume_type='VOLUME_TICK',
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h4 = self.datas[1]
        self.up_buffer = self.h4.up_buffer
        self.dn_buffer = self.h4.dn_buffer

        self.bar_num = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.entry_order = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None
        self.min_signal_bars = int(self.p.xlength) + max(int(self.p.signal_bar), 1) + 5

    def log(self, text):
        dt = bt.num2date(self.m15.datetime[0])
        print('{0}, {1}'.format(dt.isoformat(), text))

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        if len(self.h4) < self.min_signal_bars:
            return False
        try:
            values = [float(self.dn_buffer[-idx]), float(self.dn_buffer[-(idx + 1)]), float(self.up_buffer[-idx]), float(self.up_buffer[-(idx + 1)])]
        except (TypeError, ValueError, IndexError):
            return False
        return not any(np.isnan(v) for v in values)

    def _manage_risk(self):
        if not self.position:
            return False
        high = float(self.m15.high[0])
        low = float(self.m15.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.entry_order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.entry_order = self.close()
                return True
        return False

    def _set_risk_prices(self, side):
        price = float(self.m15.close[0])
        unit = self._trade_unit()
        if side == 'buy':
            self.stop_price = round(price - self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None

    def _evaluate_signals(self):
        idx = max(int(self.p.signal_bar), 1)
        ind_curr = float(self.dn_buffer[-idx])
        ind_prev = float(self.dn_buffer[-(idx + 1)])
        sign_curr = float(self.up_buffer[-idx])
        sign_prev = float(self.up_buffer[-(idx + 1)])
        buy_open = buy_close = sell_open = sell_close = False
        if ind_prev > sign_prev:
            if self.p.buy_pos_open and ind_curr <= sign_curr:
                buy_open = True
                self.buy_signal_count += 1
            if self.p.sell_pos_close:
                sell_close = True
        if ind_prev < sign_prev:
            if self.p.sell_pos_open and ind_curr >= sign_curr:
                sell_open = True
                self.sell_signal_count += 1
            if self.p.buy_pos_close:
                buy_close = True
        return buy_open, buy_close, sell_open, sell_close, ind_prev, sign_prev, ind_curr, sign_curr

    def next(self):
        self.bar_num += 1
        if self.entry_order is not None:
            return
        if not self._enough_history():
            return
        if self._manage_risk():
            return
        signal_idx = max(int(self.p.signal_bar), 1)
        signal_dt = bt.num2date(self.h4.datetime[-signal_idx])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        buy_open, buy_close, sell_open, sell_close, ind_prev, sign_prev, ind_curr, sign_curr = self._evaluate_signals()
        self.log('bnb ind_prev={0:.5f} sign_prev={1:.5f} ind_curr={2:.5f} sign_curr={3:.5f} buy_open={4} sell_open={5}'.format(ind_prev, sign_prev, ind_curr, sign_curr, buy_open, sell_open))
        if buy_close and self.position and self.position.size > 0:
            self.entry_order = self.close()
            return
        if sell_close and self.position and self.position.size < 0:
            self.entry_order = self.close()
            return
        if buy_open and (not self.position or self.position.size <= 0):
            if self.position and self.position.size < 0:
                self.entry_order = self.close()
                return
            self._set_risk_prices('buy')
            self.entry_order = self.buy(size=self.p.size)
            return
        if sell_open and (not self.position or self.position.size >= 0):
            if self.position and self.position.size > 0:
                self.entry_order = self.close()
                return
            self._set_risk_prices('sell')
            self.entry_order = self.sell(size=self.p.size)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.entry_order is not None and order.ref == self.entry_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
