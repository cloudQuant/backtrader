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


def resample_frame(df, rule):
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


def ema_manual(series, period):
    period = int(max(period, 1))
    alpha = 2.0 / (period + 1.0)
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    if len(values) < period:
        return pd.Series(out, index=series.index)
    seed = np.nanmean(values[:period])
    out[period - 1] = seed
    for idx in range(period, len(values)):
        prev = out[idx - 1]
        curr = values[idx]
        if np.isnan(curr):
            out[idx] = prev
        else:
            out[idx] = prev + alpha * (curr - prev)
    return pd.Series(out, index=series.index)


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


def weighted_moving_average(series, period):
    period = int(max(period, 1))
    weights = np.arange(1, period + 1, dtype=float)
    return series.rolling(period).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)


def true_range(frame):
    prev_close = frame['close'].shift(1)
    return pd.concat([
        frame['high'] - frame['low'],
        (frame['high'] - prev_close).abs(),
        (frame['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)


def compute_atr(frame, period=15):
    tr = true_range(frame)
    return smma(tr, period)


def compute_kama(series, er_period=9, fast_period=2, slow_period=30):
    er_period = int(max(er_period, 1))
    fast_sc = 2.0 / (fast_period + 1.0)
    slow_sc = 2.0 / (slow_period + 1.0)
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    if len(values) <= er_period:
        return pd.Series(out, index=series.index)
    out[er_period] = np.nanmean(values[:er_period + 1])
    for idx in range(er_period + 1, len(values)):
        change = abs(values[idx] - values[idx - er_period])
        volatility = np.nansum(np.abs(np.diff(values[idx - er_period:idx + 1])))
        er = (change / volatility) if volatility else 0.0
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        prev = out[idx - 1]
        if np.isnan(prev):
            prev = values[idx - 1]
        out[idx] = prev + sc * (values[idx] - prev)
    return pd.Series(out, index=series.index)


def moving_average(series, period, method='MODE_LWMA'):
    method = str(method or 'MODE_LWMA').upper()
    if method == 'MODE_SMA':
        return series.rolling(int(max(period, 1))).mean()
    if method == 'MODE_EMA':
        return ema_manual(series, period)
    if method == 'MODE_SMMA':
        return smma(series, period)
    return weighted_moving_average(series, period)


def compute_kaufwmacross(frame, ama_period=9, fast_ma_period=2, slow_ma_period=30, ama_price='PRICE_CLOSE', ma_period=13, ma_type='MODE_LWMA', ma_price='PRICE_CLOSE', point=0.01):
    price_ama = frame['close'] if str(ama_price).upper() == 'PRICE_CLOSE' else frame['close']
    price_ma = frame['close'] if str(ma_price).upper() == 'PRICE_CLOSE' else frame['close']
    ama = compute_kama(price_ama, er_period=ama_period, fast_period=fast_ma_period, slow_period=slow_ma_period)
    ma = moving_average(price_ma, ma_period, ma_type)
    atr = compute_atr(frame, 15)
    buy_arrow = pd.Series(0.0, index=frame.index)
    sell_arrow = pd.Series(0.0, index=frame.index)
    cross_buy = (ama.shift(1) > ma.shift(1)) & (ama < ma)
    cross_sell = (ama.shift(1) < ma.shift(1)) & (ama > ma)
    buy_arrow.loc[cross_buy] = frame.loc[cross_buy, 'low'] - atr.loc[cross_buy] * 3.0 / 8.0
    sell_arrow.loc[cross_sell] = frame.loc[cross_sell, 'high'] + atr.loc[cross_sell] * 3.0 / 8.0
    out = frame.copy()
    out['buy_arrow'] = buy_arrow
    out['sell_arrow'] = sell_arrow
    return out.dropna(subset=['buy_arrow', 'sell_arrow'], how='all')


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class KaufWMAcrossFeed(bt.feeds.PandasData):
    lines = ('sell_arrow', 'buy_arrow')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('sell_arrow', 6), ('buy_arrow', 7),
    )


class KaufWMAcrossStrategy(bt.Strategy):
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
        ama_period=9,
        fast_ma_period=2,
        slow_ma_period=30,
        ama_price='PRICE_CLOSE',
        ma_period=13,
        ma_type='MODE_LWMA',
        ma_price='PRICE_CLOSE',
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h6 = self.datas[1]
        self.sell_arrow = self.h6.sell_arrow
        self.buy_arrow = self.h6.buy_arrow

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
        self.min_signal_bars = max(int(self.p.signal_bar), 1) + max(int(self.p.ama_period), int(self.p.ma_period), 15) + 5

    def log(self, text):
        dt = bt.num2date(self.m15.datetime[0])
        print('{0}, {1}'.format(dt.isoformat(), text))

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        if len(self.h6) < self.min_signal_bars:
            return False
        try:
            buy_value = float(self.buy_arrow[-idx])
            sell_value = float(self.sell_arrow[-idx])
        except (TypeError, ValueError, IndexError):
            return False
        return not (np.isnan(buy_value) and np.isnan(sell_value))

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
        buy_arrow = float(self.buy_arrow[-idx])
        sell_arrow = float(self.sell_arrow[-idx])
        has_buy = (not np.isnan(buy_arrow)) and buy_arrow != 0.0
        has_sell = (not np.isnan(sell_arrow)) and sell_arrow != 0.0
        buy_open = buy_close = sell_open = sell_close = False
        if has_buy:
            if self.p.buy_pos_open:
                buy_open = True
                self.buy_signal_count += 1
            if self.p.sell_pos_close:
                sell_close = True
        if has_sell:
            if self.p.sell_pos_open:
                sell_open = True
                self.sell_signal_count += 1
            if self.p.buy_pos_close:
                buy_close = True
        if ((self.p.buy_pos_open and self.p.buy_pos_close) or (self.p.sell_pos_open and self.p.sell_pos_close)) and (not buy_close and not sell_close):
            for offset in range(idx + 1, len(self.h6)):
                hist_buy = float(self.buy_arrow[-offset]) if len(self.h6) > offset else np.nan
                hist_sell = float(self.sell_arrow[-offset]) if len(self.h6) > offset else np.nan
                if self.p.sell_pos_close and (not np.isnan(hist_buy)) and hist_buy != 0.0:
                    sell_close = True
                    break
                if self.p.buy_pos_close and (not np.isnan(hist_sell)) and hist_sell != 0.0:
                    buy_close = True
                    break
        return buy_open, buy_close, sell_open, sell_close, buy_arrow, sell_arrow

    def next(self):
        self.bar_num += 1
        if self.entry_order is not None:
            return
        if not self._enough_history():
            return
        if self._manage_risk():
            return
        signal_idx = max(int(self.p.signal_bar), 1)
        signal_dt = bt.num2date(self.h6.datetime[-signal_idx])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        buy_open, buy_close, sell_open, sell_close, buy_arrow, sell_arrow = self._evaluate_signals()
        self.log('kaufwmacross buy_arrow={0:.5f} sell_arrow={1:.5f} buy_open={2} sell_open={3}'.format(buy_arrow, sell_arrow, buy_open, sell_open))
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
