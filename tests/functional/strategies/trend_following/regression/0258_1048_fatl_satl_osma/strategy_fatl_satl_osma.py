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


FATL_COEFFS = np.array([
    0.4360409450, 0.3658689069, 0.2460452079, 0.1104506886, -0.0054034585,
    -0.0760367731, -0.0933058722, -0.0670110374, -0.0190795053, 0.0259609206,
    0.0502044896, 0.0477818607, 0.0249252327, -0.0047706151, -0.0272432537,
    -0.0338917071, -0.0244141482, -0.0055774838, 0.0128149838, 0.0226522218,
    0.0208778257, 0.0100299086, -0.0036771622, -0.0136744850, -0.0160483392,
    -0.0108597376, -0.0016060704, 0.0069480557, 0.0110573605, 0.0095711419,
    0.0040444064, -0.0023824623, -0.0067093714, -0.0072003400, -0.0047717710,
    0.0005541115, 0.0007860160, 0.0130129076, 0.0040364019,
], dtype=float)

SATL_COEFFS = np.array([
    0.0982862174, 0.0975682269, 0.0961401078, 0.0940230544, 0.0912437090,
    0.0878391006, 0.0838544303, 0.0793406350, 0.0743569346, 0.0689666682,
    0.0632381578, 0.0572428925, 0.0510534242, 0.0447468229, 0.0383959950,
    0.0320735368, 0.0258537721, 0.0198005183, 0.0139807863, 0.0084512448,
    0.0032639979, -0.0015350359, -0.0059060082, -0.0098190256, -0.0132507215,
    -0.0161875265, -0.0186164872, -0.0205446727, -0.0219739146, -0.0229204861,
    -0.0234080863, -0.0234566315, -0.0231017777, -0.0223796900, -0.0213300463,
    -0.0199924534, -0.0184126992, -0.0166377699, -0.0147139428, -0.0126796776,
    -0.0105938331, -0.0084736770, -0.0063841850, -0.0043466731, -0.0023956944,
    -0.0005535180, 0.0011421469, 0.0026845693, 0.0040471369, 0.0052380201,
    0.0062194591, 0.0070340085, 0.0076266453, 0.0080376628, 0.0083037666,
    0.0083694798, 0.0082901022, 0.0080741359, 0.0077543820, 0.0073260526,
    0.0068163569, 0.0062325477, 0.0056078229, 0.0049516078, 0.0161380976,
], dtype=float)


def compute_fatl_satl_osma(frame, point=0.01):
    price = frame['close'].to_numpy(dtype=float)
    values = np.full(len(frame), np.nan, dtype=float)
    min_rates_total = int(max(len(FATL_COEFFS), len(SATL_COEFFS)))
    for idx in range(min_rates_total - 1, len(frame)):
        fatl = float(np.dot(FATL_COEFFS, price[idx - np.arange(len(FATL_COEFFS))]))
        satl = float(np.dot(SATL_COEFFS, price[idx - np.arange(len(SATL_COEFFS))]))
        values[idx] = (fatl - satl) / point
    out = frame.copy()
    out['fatl_satl_osma'] = values
    return out.dropna(subset=['fatl_satl_osma'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class FatlSatlOsmaFeed(bt.feeds.PandasData):
    lines = ('fatl_satl_osma',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('fatl_satl_osma', 6),
    )


class FatlSatlOsmaStrategy(bt.Strategy):
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
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h12 = self.datas[1]
        self.osma = self.h12.fatl_satl_osma

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
            values = [float(self.osma[-idx]), float(self.osma[-(idx + 1)]), float(self.osma[-(idx + 2)])]
        except (TypeError, ValueError, IndexError):
            return False
        return not any(math.isnan(v) for v in values)

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
        curr_val = float(self.osma[-idx])
        prev_val = float(self.osma[-(idx + 1)])
        prev2_val = float(self.osma[-(idx + 2)])
        buy_open = buy_close = sell_open = sell_close = False
        if prev_val < prev2_val:
            if self.p.buy_pos_open and curr_val > prev_val:
                buy_open = True
                self.buy_signal_count += 1
            if self.p.sell_pos_close:
                sell_close = True
        if prev_val > prev2_val:
            if self.p.sell_pos_open and curr_val < prev_val:
                sell_open = True
                self.sell_signal_count += 1
            if self.p.buy_pos_close:
                buy_close = True
        return buy_open, buy_close, sell_open, sell_close, prev2_val, prev_val, curr_val

    def next(self):
        self.bar_num += 1
        if self.entry_order is not None:
            return
        if not self._enough_history():
            return
        if self._manage_risk():
            return
        signal_dt = bt.num2date(self.h12.datetime[-max(int(self.p.signal_bar), 1)])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        buy_open, buy_close, sell_open, sell_close, prev2_val, prev_val, curr_val = self._evaluate_signals()
        self.log('fatlsatlosma prev2={0:.4f} prev={1:.4f} curr={2:.4f} buy_open={3} sell_open={4}'.format(prev2_val, prev_val, curr_val, buy_open, sell_open))
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
