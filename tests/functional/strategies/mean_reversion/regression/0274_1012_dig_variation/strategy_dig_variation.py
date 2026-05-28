from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import numpy as np
import pandas as pd


SP_COEFFICIENTS = {
    0: [1.0],
    1: [
        0.2926875484300, 0.2698679548204, 0.2277786802786, 0.1726588586020,
        0.1124127695806, 0.0550645669333, 0.00733791069745, -0.02637426808863,
        -0.0445334647733, -0.0483673837716, -0.0412219004631, -0.02759007317598,
        -0.01206738017651, 0.001567315986223, 0.01094916192054, 0.01530469318242,
        0.01532526278128, 0.01296015381098, 0.01157140552294, -0.00533181209765,
    ],
    2: [
        0.2447098565978, 0.2313977400697, 0.2061379694732, 0.1716623034064,
        0.1314690790360, 0.0895038754956, 0.0496009165125, 0.01502270569607,
        -0.01188033734430, -0.02989873856137, -0.0389896710490, -0.0401411362639,
        -0.0351196808580, -0.02611613850342, -0.01539056955666, -0.00495353651394,
        0.00368588764825, 0.00963614049782, 0.01265138888314, 0.01307496106868,
        0.01169702291063, 0.00974841844086, 0.00898900012545, -0.00649745721156,
    ],
    3: [
        0.2101888714743, 0.2017361306871, 0.1854987469779, 0.1627557943437,
        0.1352455218956, 0.1049955517302, 0.0741580960823, 0.0448262586090,
        0.01870440453637, -0.002814841280245, -0.01891352345654, -0.02929206622741,
        -0.0341888300133, -0.0342703255777, -0.03055656616909, -0.02422648959598,
        -0.01651476470542, -0.00857503584404, -0.001351831295525, 0.00448511071596,
        0.00855374511399, 0.01076725654789, 0.01131091969998, 0.01057394212462,
        0.00912947281517, 0.00771484446233, 0.00732318993223, -0.00726358358348,
    ],
    4: [
        0.1841600001487, 0.1784754786728, 0.1674508960246, 0.1517504699970,
        0.1323034848757, 0.1102401824660, 0.0867964146007, 0.0632389269284,
        0.0407389647190, 0.02035075474450, 0.002915227087755, -0.01100443994875,
        -0.02116075293157, -0.02747786871251, -0.03024034479978, -0.02988490637108,
        -0.02702558542347, -0.02236077351054, -0.01662176948519, -0.01050105629699,
        -0.00460605501191, 0.000582766458037, 0.00473324688655, 0.00766855376673,
        0.00936273985238, 0.00991966879705, 0.00955690928799, 0.00857195408578,
        0.00734849040305, 0.00634910972836, 0.00617002099346, -0.00780070803276,
    ],
    5: [
        0.1638504429550, 0.1598485090620, 0.1520285056667, 0.1407759621461,
        0.1266145946036, 0.1101999467868, 0.0922810246421, 0.0736414430377,
        0.0550613836268, 0.0372780690048, 0.02094281812508, 0.00658930585105,
        -0.00538855535197, -0.01474498292814, -0.02139199173398, -0.02541417253316,
        -0.02702341057229, -0.02647614727071, -0.02421775125345, -0.02065411010395,
        -0.01625074823286, -0.01145130552469, -0.00665356586398, -0.002196710270528,
        0.001656596678561, 0.00473296009497, 0.00694308970535, 0.00827947138512,
        0.00880879507493, 0.00865791955067, 0.00800414344065, 0.00706330074106,
        0.00608814048308, 0.00538380036114, 0.00532891349043, -0.00819568487412,
    ],
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


def apply_ma(series, period, method):
    period = max(1, int(period))
    mode = str(method).lower()
    if mode in ('mode_sma', 'sma', '0'):
        return series.rolling(period, min_periods=period).mean()
    if mode in ('mode_ema', 'ema', '1'):
        return series.ewm(span=period, adjust=False, min_periods=period).mean()
    if mode in ('mode_smma', 'smma', '2'):
        return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    weights = np.arange(1, period + 1, dtype='float64')
    weight_sum = float(weights.sum())
    return series.rolling(period, min_periods=period).apply(lambda values: float(np.dot(values, weights)) / weight_sum, raw=True)


def apply_sp(series, smooth_power):
    coeffs = SP_COEFFICIENTS.get(int(smooth_power), SP_COEFFICIENTS[1])
    window = len(coeffs)
    values = series.to_numpy(dtype='float64')
    out = np.full_like(values, np.nan, dtype='float64')
    for idx in range(window - 1, len(values)):
        window_values = values[idx - window + 1:idx + 1]
        if np.isnan(window_values).any():
            continue
        out[idx] = float(np.dot(window_values[::-1], np.array(coeffs, dtype='float64')))
    return pd.Series(out, index=series.index, dtype='float64')


def compute_dig_variation(frame, period_=12, ma_method='mode_sma', smooth_power=1):
    price = frame['close'].astype(float)
    ma = apply_ma(price, period_, ma_method)
    vr = apply_ma(price - ma, period_, ma_method)
    ext_calc = 1000.0 * (price - (ma + vr))
    variation = apply_sp(ext_calc, smooth_power)

    buy_signal = (variation.shift(1) < variation.shift(2)) & (variation > variation.shift(1))
    sell_signal = (variation.shift(1) > variation.shift(2)) & (variation < variation.shift(1))

    out = frame.copy()
    out['variation'] = variation
    out['buy_signal'] = buy_signal.astype(float)
    out['sell_signal'] = sell_signal.astype(float)
    return out.dropna(subset=['variation'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class DigVariationFeed(bt.feeds.PandasData):
    lines = ('variation', 'buy_signal', 'sell_signal')
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('variation', 6),
        ('buy_signal', 7),
        ('sell_signal', 8),
    )


class DigVariationStrategy(bt.Strategy):
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
        period=12,
        ma_method='mode_sma',
        smooth_power=1,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h8 = self.datas[1]
        self.variation = self.h8.variation
        self.buy_signal = self.h8.buy_signal
        self.sell_signal = self.h8.sell_signal

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

    def _signal_flag(self, line, idx):
        try:
            value = float(line[-idx])
        except (TypeError, ValueError, IndexError):
            return False
        return not math.isnan(value) and value > 0.5

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        try:
            float(self.variation[-idx])
        except (TypeError, ValueError, IndexError):
            return False
        return True

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

    def next(self):
        self.bar_num += 1
        if self.entry_order is not None:
            return
        if not self._enough_history():
            return
        if self._manage_risk():
            return

        idx = max(int(self.p.signal_bar), 1)
        signal_dt = bt.num2date(self.h8.datetime[-idx])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        buy_open = self.p.buy_pos_open and self._signal_flag(self.buy_signal, idx)
        sell_open = self.p.sell_pos_open and self._signal_flag(self.sell_signal, idx)
        buy_close = self.p.buy_pos_close and sell_open
        sell_close = self.p.sell_pos_close and buy_open

        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1

        self.log('variation={0:.6f} buy_open={1} sell_open={2}'.format(float(self.variation[-idx]), buy_open, sell_open))

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
