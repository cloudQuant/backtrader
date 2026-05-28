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


def compute_highs_lows_signal(frame, how_many_candles=3, atr_period=15):
    count = max(int(how_many_candles), 1)
    high = frame['high'].astype(float)
    low = frame['low'].astype(float)
    close = frame['close'].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / atr_period, adjust=False).mean()
    buy = np.zeros(len(frame), dtype=float)
    sell = np.zeros(len(frame), dtype=float)
    highs = high.to_numpy(dtype=float)
    lows = low.to_numpy(dtype=float)
    atr_vals = atr.to_numpy(dtype=float)

    for i in range(count, len(frame)):
        higher_highs = 0
        higher_lows = 0
        lower_highs = 0
        lower_lows = 0
        for k in range(count):
            if highs[i - k] > highs[i - k - 1]:
                higher_highs += 1
            if lows[i - k] > lows[i - k - 1]:
                higher_lows += 1
            if highs[i - k] < highs[i - k - 1]:
                lower_highs += 1
            if lows[i - k] < lows[i - k - 1]:
                lower_lows += 1
        if higher_highs == count and higher_lows == count:
            buy[i] = lows[i] - atr_vals[i] * 3.0 / 8.0
        elif lower_highs == count and lower_lows == count:
            sell[i] = highs[i] + atr_vals[i] * 3.0 / 8.0

    out = frame.copy()
    out['sell_signal'] = sell
    out['buy_signal'] = buy
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class HighsLowsSignalFeed(bt.feeds.PandasData):
    lines = ('sell_signal', 'buy_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('sell_signal', 6), ('buy_signal', 7),
    )


class HighsLowsSignalStrategy(bt.Strategy):
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
        how_many_candles=3,
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h4 = self.datas[1]
        self.sell_signal = self.h4.sell_signal
        self.buy_signal = self.h4.buy_signal

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
        self.min_signal_bars = max(15, 4) + max(int(self.p.signal_bar), 1)

    def log(self, text):
        dt = bt.num2date(self.m15.datetime[0])
        print('{0}, {1}'.format(dt.isoformat(), text))

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _present(self, value):
        value = float(value)
        return not np.isnan(value) and value != 0.0

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        if len(self.h4) < self.min_signal_bars:
            return False
        try:
            return self._present(self.buy_signal[-idx]) or self._present(self.sell_signal[-idx]) or self._present(self.buy_signal[-idx - 1]) or self._present(self.sell_signal[-idx - 1]) or True
        except (TypeError, ValueError, IndexError):
            return False

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

    def _search_prior_close_signals(self, signal_idx):
        buy_close = False
        sell_close = False
        if ((self.p.buy_pos_open and self.p.buy_pos_close) or (self.p.sell_pos_open and self.p.sell_pos_close)):
            for shift in range(signal_idx + 1, len(self.h4)):
                if self.p.sell_pos_close and self._present(self.buy_signal[-shift]):
                    sell_close = True
                    break
                if self.p.buy_pos_close and self._present(self.sell_signal[-shift]):
                    buy_close = True
                    break
        return buy_close, sell_close

    def _evaluate_signals(self):
        idx = max(int(self.p.signal_bar), 1)
        buy_value = float(self.buy_signal[-idx])
        sell_value = float(self.sell_signal[-idx])
        buy_open = buy_close = sell_open = sell_close = False
        if self._present(buy_value):
            if self.p.buy_pos_open:
                buy_open = True
                self.buy_signal_count += 1
            if self.p.sell_pos_close:
                sell_close = True
        if self._present(sell_value):
            if self.p.sell_pos_open:
                sell_open = True
                self.sell_signal_count += 1
            if self.p.buy_pos_close:
                buy_close = True
        if not buy_close and not sell_close:
            prior_buy_close, prior_sell_close = self._search_prior_close_signals(idx)
            buy_close = buy_close or prior_buy_close
            sell_close = sell_close or prior_sell_close
        return buy_open, buy_close, sell_open, sell_close, buy_value, sell_value

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
        buy_open, buy_close, sell_open, sell_close, buy_value, sell_value = self._evaluate_signals()
        self.log('highs-lows buy_signal={0:.5f} sell_signal={1:.5f} buy_open={2} buy_close={3} sell_open={4} sell_close={5}'.format(buy_value, sell_value, buy_open, buy_close, sell_open, sell_close))
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
