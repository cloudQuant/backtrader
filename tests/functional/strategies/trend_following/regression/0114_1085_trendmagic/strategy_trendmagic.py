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


def compute_cci(frame, period=50):
    typical = (frame['high'] + frame['low'] + frame['close']) / 3.0
    sma = typical.rolling(int(period)).mean()
    mad = typical.rolling(int(period)).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    cci = (typical - sma) / (0.015 * mad)
    return cci


def compute_atr(frame, period=5):
    prev_close = frame['close'].shift(1)
    tr = pd.concat([
        frame['high'] - frame['low'],
        (frame['high'] - prev_close).abs(),
        (frame['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(int(period)).mean()


def compute_trendmagic(frame, cci_period=50, atr_period=5, price_shift=0.0):
    cci = compute_cci(frame, cci_period)
    atr = compute_atr(frame, atr_period)
    line = np.full(len(frame), np.nan, dtype=float)
    color = np.full(len(frame), np.nan, dtype=float)
    high = frame['high'].to_numpy(dtype=float)
    low = frame['low'].to_numpy(dtype=float)
    cci_values = cci.to_numpy(dtype=float)
    atr_values = atr.to_numpy(dtype=float)
    for idx in range(len(frame) - 1, -1, -1):
        if np.isnan(cci_values[idx]) or np.isnan(atr_values[idx]):
            continue
        next_idx = idx + 1
        next_line = line[next_idx] if next_idx < len(frame) and not np.isnan(line[next_idx]) else np.nan
        if cci_values[idx] >= 0.0:
            curr = low[idx] - atr_values[idx] + price_shift
            if not np.isnan(next_line) and curr < next_line:
                curr = next_line
            line[idx] = curr
            color[idx] = 0.0
        else:
            curr = high[idx] + atr_values[idx] + price_shift
            if not np.isnan(next_line) and curr > next_line:
                curr = next_line
            line[idx] = curr
            color[idx] = 1.0
    out = frame.copy()
    out['trendmagic'] = line
    out['color'] = color
    return out.dropna(subset=['trendmagic', 'color'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class TrendMagicFeed(bt.feeds.PandasData):
    lines = ('trendmagic', 'color')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('trendmagic', 6), ('color', 7),
    )


class TrendMagicStrategy(bt.Strategy):
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
        cci_period=50,
        cci_price='PRICE_MEDIAN',
        atr_period=5,
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        price_shift=0.0,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h4 = self.datas[1]
        self.color = self.h4.color
        self.trendmagic = self.h4.trendmagic

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
        self.min_signal_bars = max(int(self.p.cci_period), int(self.p.atr_period)) + max(int(self.p.signal_bar), 1) + 3

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
            values = [float(self.color[-idx]), float(self.color[-(idx + 1)]), float(self.trendmagic[-idx]), float(self.trendmagic[-(idx + 1)])]
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
        curr_color = int(round(float(self.color[-idx])))
        prev_color = int(round(float(self.color[-(idx + 1)])))
        buy_open = buy_close = sell_open = sell_close = False
        if prev_color == 0:
            if self.p.buy_pos_open and curr_color == 1:
                buy_open = True
                self.buy_signal_count += 1
            if self.p.sell_pos_close:
                sell_close = True
        if prev_color == 1:
            if self.p.sell_pos_open and curr_color == 0:
                sell_open = True
                self.sell_signal_count += 1
            if self.p.buy_pos_close:
                buy_close = True
        return buy_open, buy_close, sell_open, sell_close, prev_color, curr_color

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
        buy_open, buy_close, sell_open, sell_close, prev_color, curr_color = self._evaluate_signals()
        self.log('trendmagic prev_color={0} curr_color={1} buy_open={2} sell_open={3}'.format(prev_color, curr_color, buy_open, sell_open))
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
