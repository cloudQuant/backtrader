from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd


PRICE_MAP = {
    'PRICE_CLOSE': 'close',
    'PRICE_CLOSE_': 'close',
    'PRICE_OPEN': 'open',
    'PRICE_OPEN_': 'open',
    'PRICE_HIGH': 'high',
    'PRICE_HIGH_': 'high',
    'PRICE_LOW': 'low',
    'PRICE_LOW_': 'low',
}


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


def _price_series(frame, ipc):
    ipc = str(ipc)
    if ipc in PRICE_MAP:
        return frame[PRICE_MAP[ipc]].astype(float)
    if ipc == 'PRICE_MEDIAN_':
        return (frame['high'] + frame['low']) / 2.0
    if ipc == 'PRICE_TYPICAL_':
        return (frame['high'] + frame['low'] + frame['close']) / 3.0
    if ipc == 'PRICE_WEIGHTED_':
        return (frame['high'] + frame['low'] + frame['close'] + frame['close']) / 4.0
    if ipc == 'PRICE_SIMPLE':
        return (frame['open'] + frame['close']) / 2.0
    if ipc == 'PRICE_QUARTER_':
        return (frame['high'] + frame['low'] + frame['open'] + frame['close']) / 4.0
    if ipc == 'PRICE_TRENDFOLLOW0_':
        return (frame['high'] + frame['low'] + frame['close']) / 3.0
    if ipc == 'PRICE_TRENDFOLLOW1_':
        return (frame['high'] + frame['low'] + 2.0 * frame['close']) / 4.0
    if ipc == 'PRICE_DEMARK_':
        out = []
        for _, row in frame.iterrows():
            if row['close'] < row['open']:
                out.append((row['high'] + 2.0 * row['low'] + row['close']) / 4.0)
            elif row['close'] > row['open']:
                out.append((2.0 * row['high'] + row['low'] + row['close']) / 4.0)
            else:
                out.append((row['high'] + row['low'] + 2.0 * row['close']) / 4.0)
        return pd.Series(out, index=frame.index, dtype=float)
    return frame['close'].astype(float)


def _smooth(series, method, length):
    length = max(int(length), 1)
    method = str(method)
    if method in {'MODE_EMA', 'MODE_EMA_', 'EMA'}:
        return series.ewm(span=length, adjust=False).mean()
    if method in {'MODE_SMMA', 'MODE_SMMA_', 'SMMA', 'MODE_RMA'}:
        return series.ewm(alpha=1.0 / length, adjust=False).mean()
    if method in {'MODE_LWMA', 'MODE_LWMA_', 'LWMA'}:
        weights = np.arange(1, length + 1, dtype=float)
        return series.rolling(length).apply(lambda x: float(np.dot(x, weights) / weights.sum()), raw=True)
    return series.rolling(length).mean()


def compute_color_tsi_oscillator(frame, first_method='MODE_SMA', first_length=12, second_method='MODE_SMA', second_length=12, ipc='PRICE_CLOSE', trigger_shift=1):
    price = _price_series(frame, ipc)
    dprice = price.diff()
    absdprice = dprice.abs()
    mtm1 = _smooth(dprice, first_method, first_length)
    absmtm1 = _smooth(absdprice, first_method, first_length)
    mtm2 = _smooth(mtm1, second_method, second_length)
    absmtm2 = _smooth(absmtm1, second_method, second_length)
    tsi = 100.0 * mtm2 / absmtm2.replace(0.0, np.nan)
    trigger = tsi.shift(int(trigger_shift))
    out = frame.copy()
    out['tsi'] = tsi
    out['trigger'] = trigger
    return out.dropna(subset=['tsi', 'trigger'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class ColorTsiOscillatorFeed(bt.feeds.PandasData):
    lines = ('tsi', 'trigger')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('tsi', 6), ('trigger', 7),
    )


class ColorTsiOscillatorStrategy(bt.Strategy):
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
        first_method='MODE_SMA',
        first_length=12,
        first_phase=15,
        second_method='MODE_SMA',
        second_length=12,
        second_phase=15,
        ipc='PRICE_CLOSE',
        shift=0,
        trigger_shift=1,
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h4 = self.datas[1]
        self.tsi = self.h4.tsi
        self.trigger = self.h4.trigger

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
            values = [float(self.tsi[-idx]), float(self.tsi[-(idx + 1)]), float(self.trigger[-idx]), float(self.trigger[-(idx + 1)])]
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
        ind0 = float(self.tsi[-idx])
        ind1 = float(self.tsi[-(idx + 1)])
        sign0 = float(self.trigger[-idx])
        sign1 = float(self.trigger[-(idx + 1)])
        buy_open = buy_close = sell_open = sell_close = False
        if ind1 > sign1:
            if self.p.buy_pos_open and ind0 <= sign0:
                buy_open = True
                self.buy_signal_count += 1
            if self.p.sell_pos_close:
                sell_close = True
        if ind1 < sign1:
            if self.p.sell_pos_open and ind0 >= sign0:
                sell_open = True
                self.sell_signal_count += 1
            if self.p.buy_pos_close:
                buy_close = True
        return buy_open, buy_close, sell_open, sell_close

    def next(self):
        self.bar_num += 1
        if self.entry_order is not None:
            return
        if not self._enough_history():
            return
        if self._manage_risk():
            return
        signal_dt = bt.num2date(self.h4.datetime[-max(int(self.p.signal_bar), 1)])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        buy_open, buy_close, sell_open, sell_close = self._evaluate_signals()
        self.log('color-tsi-oscillator buy_open={0} buy_close={1} sell_open={2} sell_close={3}'.format(buy_open, buy_close, sell_open, sell_close))
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
