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


def compute_blau_hlm(frame, xma_method='MODE_EMA', xlength=2, xlength1=20, xlength2=5, xlength3=3, xlength4=3, point=0.01):
    out = frame.copy()
    xlength = max(int(xlength), 1)
    xlength1 = max(int(xlength1), 1)
    xlength2 = max(int(xlength2), 1)
    xlength3 = max(int(xlength3), 1)
    xlength4 = max(int(xlength4), 1)
    bars = len(out)
    hlm = pd.Series(index=out.index, dtype=float)
    for i in range(bars):
        if i < xlength - 1:
            hlm.iloc[i] = np.nan
            continue
        hmu = float(out['high'].iloc[i] - out['high'].iloc[i - (xlength - 1)])
        lmd = float(-(out['low'].iloc[i] - out['low'].iloc[i - (xlength - 1)]))
        hmu = hmu if hmu > 0 else 0.0
        lmd = lmd if lmd > 0 else 0.0
        hlm.iloc[i] = (hmu - lmd) / point
    xhlm = smooth_series(hlm, xlength1, xma_method)
    xxhlm = smooth_series(xhlm, xlength2, xma_method)
    xxxhlm = smooth_series(xxhlm, xlength3, xma_method)
    sign = smooth_series(xxxhlm, xlength4, xma_method)
    color = pd.Series(index=out.index, dtype=float)
    for i in range(bars):
        if i == 0 or pd.isna(xxxhlm.iloc[i]) or pd.isna(xxxhlm.iloc[i - 1]):
            color.iloc[i] = np.nan
            continue
        curr = float(xxxhlm.iloc[i])
        prev = float(xxxhlm.iloc[i - 1])
        clr = 2.0
        if curr > 0:
            if curr > prev:
                clr = 4.0
            elif curr < prev:
                clr = 3.0
        elif curr < 0:
            if curr < prev:
                clr = 0.0
            elif curr > prev:
                clr = 1.0
        color.iloc[i] = clr
    out['up'] = xxxhlm
    out['dn'] = sign
    out['hist'] = xxxhlm
    out['color'] = color
    out = out.dropna(subset=['up', 'dn', 'hist'])
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5),
    )


class BlauHLMFeed(bt.feeds.PandasData):
    lines = ('up', 'dn', 'hist', 'color',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('up', 6), ('dn', 7), ('hist', 8), ('color', 9),
    )


class BlauHLMStrategy(bt.Strategy):
    params = dict(
        mode='twist',
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
        xma_method='MODE_EMA',
        xlength=2,
        xlength1=20,
        xlength2=5,
        xlength3=3,
        xlength4=3,
        xphase=15,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.signal = self.datas[1]
        self.up = self.signal.up
        self.dn = self.signal.dn
        self.hist = self.signal.hist

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
            if self.p.mode == 'breakdown':
                _ = float(self.hist[-idx])
                _ = float(self.hist[-(idx + 1)])
            elif self.p.mode == 'twist':
                _ = float(self.hist[-idx])
                _ = float(self.hist[-(idx + 1)])
                _ = float(self.hist[-(idx + 2)])
            else:
                _ = float(self.up[-idx])
                _ = float(self.up[-(idx + 1)])
                _ = float(self.dn[-idx])
                _ = float(self.dn[-(idx + 1)])
            return True
        except (TypeError, ValueError, IndexError):
            return False

    def _evaluate_signals(self):
        idx = max(int(self.p.signal_bar), 1)
        buy_open = sell_open = buy_close = sell_close = False
        if self.p.mode == 'breakdown':
            hist_curr = float(self.hist[-idx])
            hist_prev = float(self.hist[-(idx + 1)])
            if hist_prev > 0:
                if self.p.buy_pos_open and hist_curr <= 0:
                    buy_open = True
                if self.p.sell_pos_close:
                    sell_close = True
            if hist_prev < 0:
                if self.p.sell_pos_open and hist_curr >= 0:
                    sell_open = True
                if self.p.buy_pos_close:
                    buy_close = True
            debug = 'mode=breakdown hist_curr={0:.5f} hist_prev={1:.5f}'.format(hist_curr, hist_prev)
            return buy_open, buy_close, sell_open, sell_close, debug
        if self.p.mode == 'twist':
            hist_curr = float(self.hist[-idx])
            hist_prev = float(self.hist[-(idx + 1)])
            hist_prev2 = float(self.hist[-(idx + 2)])
            if hist_prev < hist_prev2:
                if self.p.buy_pos_open and hist_curr > hist_prev:
                    buy_open = True
                if self.p.sell_pos_close:
                    sell_close = True
            if hist_prev > hist_prev2:
                if self.p.sell_pos_open and hist_curr < hist_prev:
                    sell_open = True
                if self.p.buy_pos_close:
                    buy_close = True
            debug = 'mode=twist hist_curr={0:.5f} hist_prev={1:.5f} hist_prev2={2:.5f}'.format(hist_curr, hist_prev, hist_prev2)
            return buy_open, buy_close, sell_open, sell_close, debug
        up_curr = float(self.up[-idx])
        up_prev = float(self.up[-(idx + 1)])
        dn_curr = float(self.dn[-idx])
        dn_prev = float(self.dn[-(idx + 1)])
        if up_prev > dn_prev:
            if self.p.buy_pos_open and up_curr <= dn_curr:
                buy_open = True
            if self.p.sell_pos_close:
                sell_close = True
        if up_prev < dn_prev:
            if self.p.sell_pos_open and up_curr >= dn_curr:
                sell_open = True
            if self.p.buy_pos_close:
                buy_close = True
        debug = 'mode=cloudtwist up_curr={0:.5f} dn_curr={1:.5f} up_prev={2:.5f} dn_prev={3:.5f}'.format(up_curr, dn_curr, up_prev, dn_prev)
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
        self.log('blauhlm {0} buy_open={1} sell_open={2}'.format(debug, buy_open, sell_open))
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
