from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
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
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum', 'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


def compute_atr(frame, period=100):
    prev_close = frame['close'].shift(1)
    tr = pd.concat([
        frame['high'] - frame['low'],
        (frame['high'] - prev_close).abs(),
        (frame['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(int(period)).mean()


def compute_hlrsign(frame, mode='OUT', hlr_range=40, hlr_up_level=80, hlr_dn_level=20, atr_period=100):
    hlr_range = max(int(hlr_range), 1)
    mode = str(mode).upper()
    atr = compute_atr(frame, atr_period)
    high = frame['high'].to_numpy(dtype=float)
    low = frame['low'].to_numpy(dtype=float)
    buy_arrow = np.full(len(frame), np.nan, dtype=float)
    sell_arrow = np.full(len(frame), np.nan, dtype=float)
    hlr_prev = 0.0
    min_rates_total = max(hlr_range + 1, atr_period)

    for idx in range(len(frame) - 1, -1, -1):
        if len(frame) - idx < min_rates_total or np.isnan(float(atr.iloc[idx])):
            continue
        hh = np.max(high[idx:min(len(frame), idx + hlr_range)])
        ll = np.min(low[idx:min(len(frame), idx + hlr_range)])
        m_pr = (high[idx] + low[idx]) / 2.0
        hl = hh - ll
        hlr0 = 100.0 * (m_pr - ll) / hl if hl else 0.0
        if mode == 'IN':
            if hlr0 > hlr_up_level and hlr_prev <= hlr_up_level:
                buy_arrow[idx] = low[idx] - atr.iloc[idx] * 3.0 / 8.0
            if hlr0 < hlr_dn_level and hlr_prev >= hlr_dn_level:
                sell_arrow[idx] = high[idx] + atr.iloc[idx] * 3.0 / 8.0
        else:
            if hlr0 < hlr_up_level and hlr_prev >= hlr_up_level:
                sell_arrow[idx] = high[idx] + atr.iloc[idx] * 3.0 / 8.0
            if hlr0 > hlr_dn_level and hlr_prev <= hlr_dn_level:
                buy_arrow[idx] = low[idx] - atr.iloc[idx] * 3.0 / 8.0
        if idx > 0:
            hlr_prev = hlr0

    out = frame.copy()
    out['buy_arrow'] = buy_arrow
    out['sell_arrow'] = sell_arrow
    return out.dropna(subset=['buy_arrow', 'sell_arrow'], how='all')


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class HLRSignFeed(bt.feeds.PandasData):
    lines = ('buy_arrow', 'sell_arrow')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('buy_arrow', 6), ('sell_arrow', 7),
    )


class HLRSignStrategy(bt.Strategy):
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
        mode='OUT',
        hlr_range=40,
        hlr_up_level=80,
        hlr_dn_level=20,
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h1 = self.datas[1]
        self.buy_arrow = self.h1.buy_arrow
        self.sell_arrow = self.h1.sell_arrow

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

    def log(self, text):
        dt = bt.num2date(self.m15.datetime[0])
        print('{0}, {1}'.format(dt.isoformat(), text))

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        try:
            values = [float(self.buy_arrow[-idx]), float(self.sell_arrow[-idx])]
        except (TypeError, ValueError, IndexError):
            return False
        return True

    def _has_buy_signal(self, idx):
        value = float(self.buy_arrow[-idx])
        return not math.isnan(value) and value != 0.0

    def _has_sell_signal(self, idx):
        value = float(self.sell_arrow[-idx])
        return not math.isnan(value) and value != 0.0

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
        buy_open = buy_close = sell_open = sell_close = False
        has_buy = self._has_buy_signal(idx)
        has_sell = self._has_sell_signal(idx)

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
            bars_available = len(self.h1)
            for back in range(idx + 1, bars_available):
                if self.p.sell_pos_close and self._has_buy_signal(back):
                    sell_close = True
                    break
                if self.p.buy_pos_close and self._has_sell_signal(back):
                    buy_close = True
                    break

        return buy_open, buy_close, sell_open, sell_close, has_buy, has_sell

    def next(self):
        self.bar_num += 1
        if self.entry_order is not None:
            return
        if not self._enough_history():
            return
        if self._manage_risk():
            return

        signal_dt = bt.num2date(self.h1.datetime[-max(int(self.p.signal_bar), 1)])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        buy_open, buy_close, sell_open, sell_close, has_buy, has_sell = self._evaluate_signals()
        self.log('hlrsign buy_signal={0} sell_signal={1} buy_open={2} sell_open={3}'.format(has_buy, has_sell, buy_open, sell_open))

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
            if order.executed.size > 0:
                self.buy_count += 1
            elif order.executed.size < 0:
                self.sell_count += 1
            if not self.position:
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
