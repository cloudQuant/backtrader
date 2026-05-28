from __future__ import absolute_import, division, print_function, unicode_literals

import io
from collections import deque

import backtrader.feeds as btfeeds
import backtrader.indicators as btind
from backtrader.indicator import Indicator
from backtrader.strategy import Strategy
from backtrader.utils.dateintern import num2date
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


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class DigitalMacd(Indicator):
    lines = ('macd', 'signal')
    params = dict(
        signal_period=5,
        point=0.01,
    )

    FAST_COEFFS = [
        0.2149840610, 0.2065763732, 0.1903728890, 0.1675422436, 0.1397053150,
        0.1087951881, 0.0768869405, 0.0460244906, 0.0180517395, -0.0055294579,
        -0.0236660212, -0.0358140055, -0.0419497760, -0.0425331450, -0.0384279507,
        -0.0307917433, -0.0209443384, -0.0102335925, 0.0000932767, 0.0089950015,
        0.0157131144, 0.0198149331, 0.0211989019, 0.0200639819, 0.0168532934,
        0.0121825067, 0.0067474241, 0.0012444305, -0.0037087682, -0.0076300416,
        -0.0102110543, -0.0113306266, -0.0110462105, -0.0095662166, -0.0072080453,
        -0.0043494435, -0.0013771970, 0.0013575268, 0.0035760416, 0.0050946166,
        0.0058339574, 0.0058160431, 0.0051486631, 0.0039984014, 0.0025619380,
        0.0010531475, -0.0003481453, -0.0014937154, -0.0022905986, -0.0027000514,
        -0.0027359080, -0.0024543322, -0.0019409837, -0.0012957482, -0.0006179734,
        0.0000057542, 0.0005111297, 0.0008605279, 0.0010441921, 0.0010775684,
        0.0009966494, 0.0008537300, 0.0007142855, 0.0006599146, -0.0008151017,
    ]

    SLOW_COEFFS = [
        0.0825641231, 0.0822783080, 0.0814249974, 0.0800166909, 0.0780735197,
        0.0756232268, 0.0727009740, 0.0693478349, 0.0656105823, 0.0615409157,
        0.0571939540, 0.0526285643, 0.0479025123, 0.0430785482, 0.0382152880,
        0.0333706133, 0.0286021160, 0.0239614376, 0.0194972056, 0.0152532583,
        0.0112682658, 0.0075745482, 0.0041980052, 0.0011588603, -0.0015292889,
        -0.0038593393, -0.0058303888, -0.0074473108, -0.0087203043, -0.0096645874,
        -0.0102995666, -0.0106483424, -0.0107374524, -0.0105952115, -0.0102516944,
        -0.0097377645, -0.0090838346, -0.0083237046, -0.0074804382, -0.0065902734,
        -0.0056742995, -0.0047554314, -0.0038574209, -0.0029983549, -0.0021924972,
        -0.0014513858, -0.0007848072, -0.0001995891, 0.0003009728, 0.0007162164,
        0.0010478905, 0.0012994016, 0.0014755433, 0.0015824007, 0.0016272598,
        0.0016185271, 0.0015648336, 0.0014747659, 0.0013569946, 0.0012193896,
        0.0010695971, 0.0009140878, 0.0007591540, 0.0016019033,
    ]

    def __init__(self):
        self._fast_coeffs = tuple(float(v) for v in self.FAST_COEFFS)
        self._slow_coeffs = tuple(float(v) for v in self.SLOW_COEFFS)
        self._max_lookback = max(len(self._fast_coeffs), len(self._slow_coeffs))
        self._closes = deque(maxlen=self._max_lookback)
        self.addminperiod(self._max_lookback + max(int(self.p.signal_period), 1))
        self._point = float(self.p.point) if float(self.p.point) else 1.0
        self.l.signal = btind.SimpleMovingAverage(self.l.macd, period=max(int(self.p.signal_period), 1))

    def next(self):
        self._closes.append(float(self.data.close[0]))
        if len(self._closes) < self._max_lookback:
            self.l.macd[0] = float('nan')
            return

        closes = tuple(self._closes)
        fast_dma = 0.0
        for idx, coeff in enumerate(self._fast_coeffs):
            fast_dma += coeff * closes[-(idx + 1)]

        slow_dma = 0.0
        for idx, coeff in enumerate(self._slow_coeffs):
            slow_dma += coeff * closes[-(idx + 1)]

        self.l.macd[0] = (fast_dma - slow_dma) / self._point


class DigitalMacdStrategy(Strategy):
    params = dict(
        mode='MACDtwist',
        signal_bar=1,
        signal_period=5,
        stop_loss_points=1000,
        take_profit_points=2000,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.indicator = DigitalMacd(
            self.data,
            signal_period=self.p.signal_period,
            point=self.p.point,
        )
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
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.pending_entry_direction = 0
        self.warmup = max(len(DigitalMacd.FAST_COEFFS), len(DigitalMacd.SLOW_COEFFS)) + max(int(self.p.signal_period), 1) + 5

    def log(self, text):
        dt = num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _signal_indexes(self):
        current = -max(int(self.p.signal_bar), 1)
        previous = current - 1
        older = current - 2
        return current, previous, older

    def _breakdown_signals(self):
        current, previous, _ = self._signal_indexes()
        macd_now = float(self.indicator.macd[current])
        macd_prev = float(self.indicator.macd[previous])
        return macd_prev <= 0.0 and macd_now > 0.0, macd_prev >= 0.0 and macd_now < 0.0

    def _macd_twist_signals(self):
        current, previous, older = self._signal_indexes()
        macd_now = float(self.indicator.macd[current])
        macd_prev = float(self.indicator.macd[previous])
        macd_older = float(self.indicator.macd[older])
        return macd_prev < macd_older and macd_now > macd_prev, macd_prev > macd_older and macd_now < macd_prev

    def _signal_twist_signals(self):
        current, previous, older = self._signal_indexes()
        signal_now = float(self.indicator.signal[current])
        signal_prev = float(self.indicator.signal[previous])
        signal_older = float(self.indicator.signal[older])
        return signal_prev < signal_older and signal_now > signal_prev, signal_prev > signal_older and signal_now < signal_prev

    def _macd_disposition_signals(self):
        current, previous, _ = self._signal_indexes()
        macd_now = float(self.indicator.macd[current])
        macd_prev = float(self.indicator.macd[previous])
        signal_now = float(self.indicator.signal[current])
        signal_prev = float(self.indicator.signal[previous])
        return macd_prev <= signal_prev and macd_now > signal_now, macd_prev >= signal_prev and macd_now < signal_now

    def _get_signals(self):
        mode = str(self.p.mode)
        if mode == 'breakdown':
            return self._breakdown_signals()
        if mode == 'SIGNALtwist':
            return self._signal_twist_signals()
        if mode == 'MACDdisposition':
            return self._macd_disposition_signals()
        return self._macd_twist_signals()

    def _reset_levels(self):
        self.entry_price = None
        self.stop_price = None
        self.target_price = None

    def _open_long(self):
        self.pending_entry_direction = 1
        self.buy(size=self.p.lot)

    def _open_short(self):
        self.pending_entry_direction = -1
        self.sell(size=self.p.lot)

    def _close_position(self, reason):
        self.log(reason)
        self.close()
        self._reset_levels()

    def _manage_protective_levels(self):
        if not self.position or self.entry_price is None:
            return False

        low = float(self.data.low[0])
        high = float(self.data.high[0])

        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self._close_position(f'close long stop={self.stop_price:.2f}')
                return True
            if self.target_price is not None and high >= self.target_price:
                self._close_position(f'close long target={self.target_price:.2f}')
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self._close_position(f'close short stop={self.stop_price:.2f}')
                return True
            if self.target_price is not None and low <= self.target_price:
                self._close_position(f'close short target={self.target_price:.2f}')
                return True

        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.warmup + max(int(self.p.signal_bar), 1) + 2:
            return

        if self._manage_protective_levels():
            return

        buy_signal, sell_signal = self._get_signals()
        macd_now = float(self.indicator.macd[0])
        signal_now = float(self.indicator.signal[0])

        if buy_signal:
            self.buy_signal_count += 1
        if sell_signal:
            self.sell_signal_count += 1

        if self.position:
            if self.position.size > 0 and sell_signal:
                self.log(f'close long & sell macd={macd_now:.4f} signal={signal_now:.4f}')
                self.close()
                self._reset_levels()
                self._open_short()
                return
            if self.position.size < 0 and buy_signal:
                self.log(f'close short & buy macd={macd_now:.4f} signal={signal_now:.4f}')
                self.close()
                self._reset_levels()
                self._open_long()
                return
        else:
            if buy_signal:
                self.log(f'buy macd={macd_now:.4f} signal={signal_now:.4f}')
                self._open_long()
                return
            if sell_signal:
                self.log(f'sell macd={macd_now:.4f} signal={signal_now:.4f}')
                self._open_short()
                return

    def notify_order(self, order):
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.rejected_order_count += 1
            self.pending_entry_direction = 0
            self.log(f'order {order.getstatusname()}')
            return

        if order.status != order.Completed:
            return

        self.completed_order_count += 1

        if self.pending_entry_direction == 1 and order.isbuy():
            self.buy_count += 1
            self.entry_price = order.executed.price
            self.stop_price = self.entry_price - self.p.stop_loss_points * self.p.point if self.p.stop_loss_points > 0 else None
            self.target_price = self.entry_price + self.p.take_profit_points * self.p.point if self.p.take_profit_points > 0 else None
            self.pending_entry_direction = 0
            return

        if self.pending_entry_direction == -1 and order.issell():
            self.sell_count += 1
            self.entry_price = order.executed.price
            self.stop_price = self.entry_price + self.p.stop_loss_points * self.p.point if self.p.stop_loss_points > 0 else None
            self.target_price = self.entry_price - self.p.take_profit_points * self.p.point if self.p.take_profit_points > 0 else None
            self.pending_entry_direction = 0
            return

        if not self.position:
            self._reset_levels()

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
