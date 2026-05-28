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


def applied_price_series(df, applied_price):
    key = str(applied_price)
    if key in ('PRICE_CLOSE', 'PRICE_CLOSE_', 'close'):
        return df['close'].astype(float)
    if key in ('PRICE_OPEN', 'PRICE_OPEN_', 'open'):
        return df['open'].astype(float)
    if key in ('PRICE_HIGH', 'PRICE_HIGH_', 'high'):
        return df['high'].astype(float)
    if key in ('PRICE_LOW', 'PRICE_LOW_', 'low'):
        return df['low'].astype(float)
    if key in ('PRICE_MEDIAN', 'PRICE_MEDIAN_'):
        return (df['high'] + df['low']) / 2.0
    if key in ('PRICE_TYPICAL', 'PRICE_TYPICAL_'):
        return (df['high'] + df['low'] + df['close']) / 3.0
    if key in ('PRICE_WEIGHTED', 'PRICE_WEIGHTED_'):
        return (df['high'] + df['low'] + 2.0 * df['close']) / 4.0
    if key in ('PRICE_SIMPLE', 'PRICE_SIMPL_', 'PRICE_SIMPLE_'):
        return (df['open'] + df['close']) / 2.0
    if key in ('PRICE_QUARTER', 'PRICE_QUARTER_'):
        return (df['high'] + df['low'] + df['open'] + df['close']) / 4.0
    raise ValueError('Unsupported applied price: {0}'.format(applied_price))


class JurXState(object):
    def __init__(self, length):
        self.length = None
        self.kg = None
        self.hg = None
        self.ab = 0.5
        self.ac = 1.5
        self.f1 = None
        self.f2 = None
        self.f3 = None
        self.f4 = None
        self.f5 = None
        self.f6 = None
        self.reset(length)

    def reset(self, length, series=None):
        self.length = max(float(length), 1.0)
        self.kg = 3.0 / (self.length + 2.0)
        self.hg = 1.0 - self.kg
        if series is not None:
            self.f1 = self.f2 = self.f3 = self.f4 = self.f5 = self.f6 = float(series)
        else:
            self.f1 = self.f2 = self.f3 = self.f4 = self.f5 = self.f6 = None

    def update(self, series):
        series = float(series)
        if self.f1 is None:
            self.reset(self.length, series=series)
        self.f1 = self.hg * self.f1 + self.kg * series
        self.f2 = self.kg * self.f1 + self.hg * self.f2
        v1 = self.ac * self.f1 - self.ab * self.f2
        self.f3 = self.hg * self.f3 + self.kg * v1
        self.f4 = self.kg * self.f3 + self.hg * self.f4
        v2 = self.ac * self.f3 - self.ab * self.f4
        self.f5 = self.hg * self.f5 + self.kg * v2
        self.f6 = self.kg * self.f5 + self.hg * self.f6
        return self.ac * self.f5 - self.ab * self.f6


class JJMAState(object):
    def __init__(self, length, phase):
        self.length = float(length)
        self.phase_input = float(phase)
        self.array = [0.0] * 62
        self.hoop1 = [0.0] * 128
        self.hoop2 = [0.0] * 11
        self.data = [0.0] * 129
        self.reset(length, phase)

    def reset(self, length=None, phase=None, series=None):
        if length is not None:
            self.length = max(float(length), 1.0)
        if phase is not None:
            self.phase_input = float(phase)
        self.midd1 = 63
        self.midd2 = 64
        self.start = False
        for idx in range(0, self.midd1 + 1):
            self.data[idx] = -1000000.0
        for idx in range(self.midd2, 128):
            self.data[idx] = 1000000.0
        self.hoop1 = [0.0] * 128
        self.hoop2 = [0.0] * 11
        self.array = [0.0] * 62
        self.djma = 0.0
        self.sum1 = 0.0
        self.sum2 = 0.0
        self.ser1 = 0.0
        self.ser2 = 0.0
        self.pos1 = 0
        self.pos2 = 0
        self.loop1 = 0
        self.loop2 = 0
        self.count1 = 0
        self.count2 = 0
        self.count3 = 0
        self.storage1 = 0.0
        self.storage2 = 0.0
        self.jma = float(series) if series is not None else 0.0
        if -100.0 <= self.phase_input <= 100.0:
            self.phase = self.phase_input / 100.0 + 1.5
        elif self.phase_input > 100.0:
            self.phase = 2.5
        else:
            self.phase = 0.5
        vel_a = (self.length - 1.0) / 2.0 if self.length >= 1.0000000002 else 0.0000000001
        vel_a *= 0.9
        self.krj = vel_a / (vel_a + 2.0)
        vel_c = math.sqrt(vel_a)
        vel_d = math.log(vel_c)
        sense = max((vel_d / math.log(2.0)) + 2.0, 0.0)
        self.kfd = sense
        self.degree = self.kfd - 2.0 if self.kfd >= 2.5 else 0.5
        self.krx = vel_c * self.kfd
        self.kct = self.krx / (self.krx + 1.0)

    def update(self, series):
        series = float(series)
        if self.loop1 == 0 and self.jma == 0.0:
            self.reset(series=series)
        if self.loop1 < 61:
            self.loop1 += 1
            self.array[self.loop1] = series

        extent = 0.0
        if self.loop1 > 30:
            if not self.start:
                self.start = True
                back = 29
                self.ser2 = self.array[1]
                self.ser1 = self.ser2
            else:
                back = 0

            for rrr in range(back, -1, -1):
                ser0 = series if rrr == 0 else self.array[31 - rrr]
                dser1 = ser0 - self.ser1
                dser2 = ser0 - self.ser2
                var2 = max(abs(dser1), abs(dser2))
                res = var2
                newvel = res + 1e-10

                if self.count1 <= 1:
                    self.count1 = 127
                else:
                    self.count1 -= 1

                if self.count2 <= 1:
                    self.count2 = 10
                else:
                    self.count2 -= 1

                if self.count3 < 128:
                    self.count3 += 1

                self.sum1 += newvel - self.hoop2[self.count2]
                self.hoop2[self.count2] = newvel
                sm_vel = self.sum1 / 10.0 if self.count3 > 10 else self.sum1 / float(self.count3)

                if self.count3 > 127:
                    hoop1 = self.hoop1[self.count1]
                    self.hoop1[self.count1] = sm_vel
                    numb = 64
                    pos_b = numb
                    while numb > 1:
                        if self.data[pos_b] < hoop1:
                            numb = int(numb / 2.0)
                            pos_b += numb
                        elif self.data[pos_b] <= hoop1:
                            numb = 1
                        else:
                            numb = int(numb / 2.0)
                            pos_b -= numb
                else:
                    self.hoop1[self.count1] = sm_vel
                    if self.midd1 + self.midd2 > 127:
                        self.midd2 -= 1
                        pos_b = self.midd2
                    else:
                        self.midd1 += 1
                        pos_b = self.midd1
                    self.pos2 = 96 if self.midd1 > 96 else self.midd1
                    self.pos1 = 32 if self.midd2 < 32 else self.midd2

                numb = 64
                pos_a = numb
                while numb > 1:
                    if self.data[pos_a] >= sm_vel:
                        if self.data[pos_a - 1] <= sm_vel:
                            numb = 1
                        else:
                            numb = int(numb / 2.0)
                            pos_a -= numb
                    else:
                        numb = int(numb / 2.0)
                        pos_a += numb
                    if pos_a == 127 and sm_vel > self.data[127]:
                        pos_a = 128

                if self.count3 > 127:
                    if pos_b >= pos_a:
                        if self.pos2 + 1 > pos_a:
                            if self.pos1 - 1 < pos_a:
                                self.sum2 += sm_vel
                        elif self.pos1 + 0 > pos_a:
                            if self.pos1 - 1 < pos_b:
                                self.sum2 += self.data[self.pos1 - 1]
                    elif self.pos1 >= pos_a:
                        if self.pos2 + 1 < pos_a:
                            if self.pos2 + 1 > pos_b:
                                self.sum2 += self.data[self.pos2 + 1]
                    elif self.pos2 + 2 > pos_a:
                        self.sum2 += sm_vel
                    elif self.pos2 + 1 < pos_a:
                        if self.pos2 + 1 > pos_b:
                            self.sum2 += self.data[self.pos2 + 1]

                    if pos_b > pos_a:
                        if self.pos1 - 1 < pos_b:
                            if self.pos2 + 1 > pos_b:
                                self.sum2 -= self.data[pos_b]
                        elif self.pos2 < pos_b:
                            if self.pos2 + 1 > pos_a:
                                self.sum2 -= self.data[self.pos2]
                    else:
                        if self.pos2 + 1 > pos_b and self.pos1 - 1 < pos_b:
                            self.sum2 -= self.data[pos_b]
                        elif self.pos1 + 0 > pos_b:
                            if self.pos1 - 0 < pos_a:
                                self.sum2 -= self.data[self.pos1]

                if pos_b <= pos_a:
                    if pos_b == pos_a:
                        self.data[pos_a] = sm_vel
                    else:
                        for idx in range(pos_b + 1, pos_a):
                            self.data[idx - 1] = self.data[idx]
                        self.data[pos_a - 1] = sm_vel
                else:
                    for idx in range(pos_b - 1, pos_a - 1, -1):
                        self.data[idx + 1] = self.data[idx]
                    self.data[pos_a] = sm_vel

                if self.count3 <= 127:
                    self.sum2 = 0.0
                    for idx in range(self.pos1, self.pos2 + 1):
                        self.sum2 += self.data[idx]

                resalt = self.sum2 / (self.pos2 - self.pos1 + 1.0)
                if self.loop2 > 30:
                    self.loop2 = 31
                else:
                    self.loop2 += 1

                if self.loop2 <= 30:
                    if dser1 > 0.0:
                        self.ser1 = ser0
                    else:
                        self.ser1 = ser0 - dser1 * self.kct
                    if dser2 < 0.0:
                        self.ser2 = ser0
                    else:
                        self.ser2 = ser0 - dser2 * self.kct
                    self.jma = series
                    if self.loop2 == 30:
                        self.storage1 = series
                        dsupr = math.ceil(self.krx) if math.ceil(self.krx) >= 1 else 1.0
                        if dsupr > 0:
                            suprem2 = math.floor(dsupr)
                        elif dsupr < 0:
                            suprem2 = math.ceil(dsupr)
                        else:
                            suprem2 = 0.0
                        var2_floor = math.floor(self.krx) if math.floor(self.krx) >= 1 else 1.0
                        if var2_floor > 0:
                            suprem1 = math.floor(var2_floor)
                        elif var2_floor < 0:
                            suprem1 = math.ceil(var2_floor)
                        else:
                            suprem1 = 0.0
                        if suprem2 == suprem1:
                            factor = 1.0
                        else:
                            dsupr = suprem2 - suprem1
                            factor = (self.krx - suprem1) / dsupr
                        shift1 = int(suprem1) if suprem1 <= 29 else 29
                        shift2 = int(suprem2) if suprem2 <= 29 else 29
                        dser3 = series - self.array[self.loop1 - shift1]
                        dser4 = series - self.array[self.loop1 - shift2]
                        self.djma = dser3 * (1.0 - factor) / suprem1 + dser4 * factor / suprem2
                    else:
                        continue
                else:
                    res_pow = math.pow(res / resalt, self.degree) if resalt else 0.0
                    var1 = res_pow if self.kfd >= res_pow else self.kfd
                    if var1 < 1.0:
                        var2 = 1.0
                    else:
                        sense = res_pow if self.kfd >= res_pow else self.kfd
                        var2 = sense
                    extent = var2
                    pow1 = math.pow(self.kct, math.sqrt(extent))
                    if dser1 > 0.0:
                        self.ser1 = ser0
                    else:
                        self.ser1 = ser0 - dser1 * pow1
                    if dser2 < 0.0:
                        self.ser2 = ser0
                    else:
                        self.ser2 = ser0 - dser2 * pow1

            if self.loop2 > 30:
                pow2 = math.pow(self.krj, extent)
                self.storage1 *= pow2
                self.storage1 += (1.0 - pow2) * series
                self.storage2 *= self.krj
                self.storage2 += (series - self.storage1) * (1.0 - self.krj)
                extr = self.phase * self.storage2 + self.storage1
                pow2x2 = pow2 * pow2
                ratio = pow2x2 - 2.0 * pow2 + 1.0
                self.djma *= pow2x2
                self.djma += (extr - self.jma) * ratio
                self.jma += self.djma

        if self.loop1 <= 30:
            return math.nan
        return self.jma


def compute_color_jjrsx(frame, jurx_period=8, jma_period=3, jma_phase=100, applied_price='PRICE_CLOSE'):
    prices = applied_price_series(frame, applied_price).to_numpy(dtype=float)
    jur_up = JurXState(jurx_period)
    jur_dn = JurXState(jurx_period)
    jjma = JJMAState(jma_period, jma_phase)
    values = np.full(len(frame), np.nan, dtype=float)

    for idx in range(len(prices)):
        if idx == 0:
            continue
        dprice = prices[idx] - prices[idx - 1]
        absd = abs(dprice)
        if absd == 0:
            absd = 1e-10
        uprsx = jur_up.update(dprice)
        dnrsx = jur_dn.update(absd)
        if dnrsx == 0:
            continue
        jrsx = 100.0 * uprsx / dnrsx
        values[idx] = jjma.update(jrsx)

    return pd.Series(values, index=frame.index, name='jjrsx')


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class Mt5JJRSXFeed(bt.feeds.PandasData):
    lines = ('jjrsx',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('jjrsx', 6),
    )


class ColorJJRSXStrategy(bt.Strategy):
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
        jurx_period=8,
        jma_period=3,
        jma_phase=100,
        applied_price='PRICE_CLOSE',
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h4 = self.datas[1]
        self.jjrsx = self.h4.jjrsx

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.entry_order = None
        self.stop_price = None
        self.take_profit_price = None
        self.current_side = None
        self.last_signal_dt = None

    def log(self, text):
        dt = bt.num2date(self.m15.datetime[0])
        print('{0}, {1}'.format(dt.isoformat(), text))

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        needed = [self.jjrsx[-idx], self.jjrsx[-idx - 1], self.jjrsx[-idx - 2]]
        return not any(math.isnan(float(v)) for v in needed)

    def _close_long_signal(self, buy_close):
        return buy_close and self.position and self.position.size > 0

    def _close_short_signal(self, sell_close):
        return sell_close and self.position and self.position.size < 0

    def _evaluate_signals(self):
        idx = max(int(self.p.signal_bar), 1)
        v0 = float(self.jjrsx[-idx])
        v1 = float(self.jjrsx[-idx - 1])
        v2 = float(self.jjrsx[-idx - 2])

        buy_open = buy_close = sell_open = sell_close = False

        if v1 < v2:
            if self.p.buy_pos_open and v0 > v1:
                buy_open = True
                self.buy_signal_count += 1
            if self.p.sell_pos_close:
                sell_close = True
        if v1 > v2:
            if self.p.sell_pos_open and v0 < v1:
                sell_open = True
                self.sell_signal_count += 1
            if self.p.buy_pos_close:
                buy_close = True
        return buy_open, buy_close, sell_open, sell_close, v0, v1, v2

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
        self.current_side = side

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

        buy_open, buy_close, sell_open, sell_close, v0, v1, v2 = self._evaluate_signals()
        self.log('jjrsx signal v2={0:.4f} v1={1:.4f} v0={2:.4f} buy_open={3} sell_open={4}'.format(v2, v1, v0, buy_open, sell_open))

        if self._close_long_signal(buy_close):
            self.entry_order = self.close()
            return
        if self._close_short_signal(sell_close):
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
                self.log('entry filled price={0:.2f} size={1:.2f}'.format(order.executed.price, order.executed.size))
            else:
                self.stop_price = None
                self.take_profit_price = None
                self.current_side = None
                self.log('position closed price={0:.2f} size={1:.2f}'.format(order.executed.price, order.executed.size))
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
            self.log('order failed status={0}'.format(order.getstatusname()))
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
        self.log('trade closed pnl={0:.2f}'.format(trade.pnlcomm))
