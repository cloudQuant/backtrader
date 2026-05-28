from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd

PRICE_CLOSE = 'PRICE_CLOSE'
PRICE_OPEN = 'PRICE_OPEN'
PRICE_HIGH = 'PRICE_HIGH'
PRICE_LOW = 'PRICE_LOW'
PRICE_MEDIAN = 'PRICE_MEDIAN'
PRICE_TYPICAL = 'PRICE_TYPICAL'
PRICE_WEIGHTED = 'PRICE_WEIGHTED'
PRICE_SIMPL = 'PRICE_SIMPL'
PRICE_QUARTER = 'PRICE_QUARTER'
PRICE_TRENDFOLLOW0 = 'PRICE_TRENDFOLLOW0'
PRICE_TRENDFOLLOW1 = 'PRICE_TRENDFOLLOW1'
PRICE_DEMARK = 'PRICE_DEMARK'


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
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'tick_volume', 'real_volume', 'openinterest']]
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
        'tick_volume': 'sum',
        'real_volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


def resolve_price(frame, price_mode):
    if price_mode == PRICE_OPEN:
        return frame['open']
    if price_mode == PRICE_HIGH:
        return frame['high']
    if price_mode == PRICE_LOW:
        return frame['low']
    if price_mode == PRICE_MEDIAN:
        return (frame['high'] + frame['low']) / 2.0
    if price_mode == PRICE_TYPICAL:
        return (frame['high'] + frame['low'] + frame['close']) / 3.0
    if price_mode == PRICE_WEIGHTED:
        return (frame['high'] + frame['low'] + frame['close'] + frame['close']) / 4.0
    if price_mode == PRICE_SIMPL:
        return (frame['open'] + frame['close']) / 2.0
    if price_mode == PRICE_QUARTER:
        return (frame['high'] + frame['low'] + frame['open'] + frame['close']) / 4.0
    if price_mode == PRICE_TRENDFOLLOW0:
        return (frame['high'] + frame['low'] + frame['close']) / 3.0 + (frame['close'] - frame['open'])
    if price_mode == PRICE_TRENDFOLLOW1:
        return (frame['high'] + frame['low'] + frame['close']) / 3.0 + (frame['open'] - frame['close'])
    if price_mode == PRICE_DEMARK:
        x = frame['close'] * 2 + frame['low'] + frame['high']
        x = np.where(frame['close'] < frame['open'], frame['high'] + frame['low'] + frame['close'] * 2, x)
        x = np.where(frame['close'] > frame['open'], frame['high'] + frame['low'] + frame['high'] + frame['low'], x)
        return pd.Series(x / 4.0, index=frame.index)
    return frame['close']


def smooth_series(series, period, method='MODE_EMA'):
    period = max(int(period), 1)
    if method == 'MODE_SMA':
        return series.rolling(period, min_periods=period).mean()
    if method == 'MODE_SMMA':
        return series.ewm(alpha=1.0 / period, adjust=False).mean()
    if method == 'MODE_LWMA':
        weights = np.arange(1, period + 1, dtype=float)
        return series.rolling(period, min_periods=period).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)
    return series.ewm(span=period, adjust=False).mean()


def compute_xpvt(frame, volume_type='VOLUME_TICK', xma_method='MODE_EMA', xlength=5, ipc=PRICE_CLOSE):
    out = frame.copy()
    price = resolve_price(out, ipc)
    volume = out['tick_volume'] if volume_type == 'VOLUME_TICK' else out['real_volume']
    pvt = pd.Series(index=out.index, dtype=float)
    if len(out) == 0:
        out['ind'] = pvt
        out['sign'] = pvt
        return out
    pvt.iloc[0] = float(volume.iloc[0])
    for i in range(1, len(out)):
        prev_price = float(price.iloc[i - 1])
        curr_price = float(price.iloc[i])
        vol = float(volume.iloc[i])
        delta = 0.0 if prev_price == 0 else vol * (curr_price - prev_price) / prev_price
        pvt.iloc[i] = pvt.iloc[i - 1] + delta
    sign = smooth_series(pvt, xlength, xma_method)
    out['ind'] = pvt
    out['sign'] = sign
    out = out.dropna(subset=['ind', 'sign'])
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5),
    )


class XPVTFeed(bt.feeds.PandasData):
    lines = ('ind', 'sign',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('ind', 6), ('sign', 7),
    )


class XPVTStrategy(bt.Strategy):
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
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        volume_type='VOLUME_TICK',
        xma_method='MODE_EMA',
        xlength=5,
        xphase=15,
        ipc='PRICE_CLOSE',
        shift=0,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.signal = self.datas[1]
        self.ind = self.signal.ind
        self.sign = self.signal.sign

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

    def _set_risk_prices(self, side):
        price = float(self.m15.close[0])
        unit = self._trade_unit()
        if side == 'buy':
            self.stop_price = round(price - self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None

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

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        try:
            _ = float(self.ind[-idx])
            _ = float(self.ind[-(idx + 1)])
            _ = float(self.sign[-idx])
            _ = float(self.sign[-(idx + 1)])
            return True
        except (TypeError, ValueError, IndexError):
            return False

    def _evaluate_signals(self):
        idx = max(int(self.p.signal_bar), 1)
        ind_curr = float(self.ind[-idx])
        ind_prev = float(self.ind[-(idx + 1)])
        sign_curr = float(self.sign[-idx])
        sign_prev = float(self.sign[-(idx + 1)])
        buy_open = sell_open = buy_close = sell_close = False
        if ind_curr > sign_curr:
            if self.p.buy_pos_open and ind_prev <= sign_prev:
                buy_open = True
            if self.p.sell_pos_close:
                sell_close = True
        if ind_curr < sign_curr:
            if self.p.sell_pos_open and ind_prev >= sign_prev:
                sell_open = True
            if self.p.buy_pos_close:
                buy_close = True
        debug = 'ind_curr={0:.5f} sign_curr={1:.5f} ind_prev={2:.5f} sign_prev={3:.5f}'.format(ind_curr, sign_curr, ind_prev, sign_prev)
        return buy_open, buy_close, sell_open, sell_close, debug

    def next(self):
        self.bar_num += 1
        if self.entry_order is not None:
            return
        if not self._enough_history():
            return
        if self._manage_risk():
            return
        signal_idx = max(int(self.p.signal_bar), 1)
        signal_dt = bt.num2date(self.signal.datetime[-signal_idx])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        buy_open, buy_close, sell_open, sell_close, debug = self._evaluate_signals()
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        self.log('xpvt {0} buy_open={1} sell_open={2}'.format(debug, buy_open, sell_open))
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
