from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import backtrader.feeds as btfeeds
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


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class BreakoutBarsTrendV2(bt.Indicator):
    lines = ('value',)
    params = dict(
        reversal_mode='PERCENT',
        delta=1.0,
        point=0.01,
    )

    def __init__(self):
        self._mode = str(self.p.reversal_mode).upper()
        self._delta = float(self.p.delta)
        if self._mode == 'PIPS':
            if self._delta < 30.0:
                self._delta = 1000.0
        else:
            if self._delta < 0.03 or self._delta > 30.0:
                self._delta = 1.0
        self._seed_close = None
        self._seed_high = None
        self._seed_low = None
        self._initialized = False
        self._uptrend = None
        self._min_price = None
        self._max_price = None
        self.addminperiod(1)

    def _reversal_distance(self, price):
        if self._mode == 'PIPS':
            return float(self._delta) * float(self.p.point)
        return (float(price) / 100.0) * float(self._delta)

    def next(self):
        close = float(self.data.close[0])
        high = float(self.data.high[0])
        low = float(self.data.low[0])

        if self._seed_close is None:
            self._seed_close = close
            self._seed_high = high
            self._seed_low = low
            self.lines.value[0] = 0.0
            return

        if not self._initialized:
            reversal = self._reversal_distance(self._seed_close)
            if abs(close - self._seed_close) - reversal <= 0.00001:
                self.lines.value[0] = 0.0
                return
            if close > self._seed_close:
                self._initialized = True
                self._uptrend = True
                self._min_price = self._seed_low
                self._max_price = high
                self.lines.value[0] = 1.0
            else:
                self._initialized = True
                self._uptrend = False
                self._min_price = low
                self._max_price = self._seed_high
                self.lines.value[0] = -1.0
            return

        prev_value = float(self.lines.value[-1])
        prev_high = float(self.data.high[-1])
        prev_low = float(self.data.low[-1])

        self._min_price = min(float(self._min_price), prev_low)
        self._max_price = max(float(self._max_price), prev_high)

        if self._uptrend:
            reversal = self._reversal_distance(self._max_price)
            if close > float(self._max_price):
                self.lines.value[0] = prev_value + 1.0
            elif close < max(float(self._max_price), high) - reversal and close < prev_low:
                self._uptrend = False
                self.lines.value[0] = -1.0
                self._max_price = high
                self._min_price = low
            else:
                self.lines.value[0] = prev_value
        else:
            reversal = self._reversal_distance(self._min_price)
            if close < float(self._min_price):
                self.lines.value[0] = prev_value - 1.0
            elif close > min(float(self._min_price), low) + reversal and close > prev_high:
                self._uptrend = True
                self.lines.value[0] = 1.0
                self._min_price = low
                self._max_price = high
            else:
                self.lines.value[0] = prev_value


class BreakoutBarsTrendEaStrategy(bt.Strategy):
    params = dict(
        reversal_mode='PERCENT',
        delta=1.0,
        negatives=1,
        stop_loss=1.0,
        take_profit=4.0,
        lot=1.0,
        point=0.01,
        min_lot=0.01,
        max_lot=100.0,
        volume_step=0.01,
    )

    def __init__(self):
        self.bbt = BreakoutBarsTrendV2(
            self.data,
            reversal_mode=self.p.reversal_mode,
            delta=self.p.delta,
            point=self.p.point,
        )
        self.order = None
        self.stop_price = None
        self.take_price = None

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

        self.addminperiod(3)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _distance(self, price, distance):
        if str(self.p.reversal_mode).upper() == 'PIPS':
            return float(distance) * float(self.p.point)
        return (float(price) / 100.0) * float(distance)

    def _clamp_volume(self, volume):
        volume = min(max(float(volume), float(self.p.min_lot)), float(self.p.max_lot))
        step = max(float(self.p.volume_step), 1e-8)
        digits = 0 if step >= 1.0 else max(0, int(round(-math.log10(step))))
        return round(volume, digits)

    def _trend_change(self):
        if len(self) < 2:
            return 0
        cur = float(self.bbt.value[0])
        prev = float(self.bbt.value[-1])
        if cur * prev < 0:
            return 1 if cur > 0 else -1
        return 0

    def _is_negative_series(self):
        negatives = max(int(self.p.negatives), 0)
        if negatives <= 0:
            return True
        size = negatives * 100
        if len(self) < size:
            return False

        closes = [float(self.data.close[-i]) for i in range(size - 1, -1, -1)]
        values = [float(self.bbt.value[-i]) for i in range(size - 1, -1, -1)]

        last_price = closes[size - 2]
        up = False if values[size - 2] > 0 else True
        counter = 0

        for bar in range(size - 3, 0, -1):
            if values[bar] * values[bar - 1] < 0:
                first_price = closes[bar]
                result = (last_price - first_price) if up else (first_price - last_price)
                if result > 0.0:
                    return False
                counter += 1
                if counter >= negatives:
                    return True
                up = not up
                last_price = first_price
        return False

    def _set_exit_levels(self, direction, price):
        stop_distance = self._distance(price, self.p.stop_loss) if float(self.p.stop_loss) > 0 else None
        take_distance = self._distance(price, self.p.take_profit) if float(self.p.take_profit) > 0 else None
        if direction > 0:
            self.stop_price = price - stop_distance if stop_distance is not None else None
            self.take_price = price + take_distance if take_distance is not None else None
        else:
            self.stop_price = price + stop_distance if stop_distance is not None else None
            self.take_price = price - take_distance if take_distance is not None else None

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and high >= self.take_price:
                self.log(f'close long by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and low <= self.take_price:
                self.log(f'close short by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if len(self) < 3:
            return
        if self._check_exit_levels():
            return

        reverse = self._trend_change()
        if self.position:
            if (self.position.size > 0 and reverse < 0) or (self.position.size < 0 and reverse > 0):
                self.log('close by trend reversal')
                self.order = self.close()
            return

        if reverse == 0:
            return
        if int(self.p.negatives) > 0 and not self._is_negative_series():
            return

        volume = self._clamp_volume(self.p.lot)
        price = float(self.data.close[0])
        self.signal_count += 1

        if reverse > 0:
            self._set_exit_levels(1, price)
            self.log(f'buy lot={volume:.2f}')
            self.order = self.buy(size=volume)
            return

        self._set_exit_levels(-1, price)
        self.log(f'sell lot={volume:.2f}')
        self.order = self.sell(size=volume)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
        self.order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.stop_price = None
        self.take_price = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
