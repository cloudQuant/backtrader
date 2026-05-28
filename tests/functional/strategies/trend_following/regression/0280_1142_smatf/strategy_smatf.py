from __future__ import absolute_import, division, print_function, unicode_literals

import io

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


class AcceleratorOscillator(bt.Indicator):
    lines = ('ac',)
    params = dict()

    def __init__(self):
        median = (self.data.high + self.data.low) / 2.0
        ao = bt.indicators.SimpleMovingAverage(median, period=5) - bt.indicators.SimpleMovingAverage(median, period=34)
        self.lines.ac = ao - bt.indicators.SimpleMovingAverage(ao, period=5)


class SmatfStrategy(bt.Strategy):
    params = dict(
        shift=1,
        open_level=0,
        close_level=0,
        lots=0.1,
        stop_loss=550,
        take_profit=550,
        trailing=0,
        ma_periods=(5, 8, 13, 21, 34),
        point=0.01,
    )

    def __init__(self):
        self.tf1 = self.datas[0]
        self.tf2 = self.datas[1]
        self.tf3 = self.datas[2]

        self.ma_tf1 = [bt.indicators.SimpleMovingAverage(self.tf1.close, period=p) for p in self.p.ma_periods]
        self.ma_tf2 = [bt.indicators.SimpleMovingAverage(self.tf2.close, period=p) for p in self.p.ma_periods]
        self.ma_tf3 = [bt.indicators.SimpleMovingAverage(self.tf3.close, period=p) for p in self.p.ma_periods]

        self.ac_tf1 = AcceleratorOscillator(self.tf1)
        self.ac_tf3 = AcceleratorOscillator(self.tf3)

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.signal_count = 0

        self.order = None
        self.stop_price = None
        self.take_price = None
        self._position_was_open = False

        self.addminperiod(max(self.p.ma_periods) + int(self.p.shift) + 10)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _dir_score(self, curr, prev):
        if curr > prev:
            return 1.0, 0.0
        if curr < prev:
            return 0.0, 1.0
        return 0.0, 0.0

    def _ac_score(self, ac0, ac1, ac2, ac3):
        up = down = 0.0
        if ((ac1 > ac2 and ac2 > ac3 and ac0 < 0 and ac0 > ac1) or (ac0 > ac1 and ac1 > ac2 and ac0 > 0)):
            up, down = 3.0, 0.0
        elif ((ac1 < ac2 and ac2 < ac3 and ac0 > 0 and ac0 < ac1) or (ac0 < ac1 and ac1 < ac2 and ac0 < 0)):
            up, down = 0.0, 3.0
        elif ((((ac1 < ac2 or ac2 < ac3) and ac0 < 0 and ac0 > ac1) or (ac0 > ac1 and ac1 < ac2 and ac0 > 0))
              or (((ac1 > ac2 or ac2 > ac3) and ac0 > 0 and ac0 < ac1) or (ac0 < ac1 and ac1 > ac2 and ac0 < 0))):
            up, down = 0.0, 0.0
        return up, down

    def _line_value(self, line, shift):
        idx = -shift if shift > 0 else 0
        return float(line[idx])

    def _signal_value(self):
        s = int(self.p.shift)

        up_scores = []
        down_scores = []

        for ma_group in (self.ma_tf1, self.ma_tf2, self.ma_tf3):
            tf_up = 0.0
            tf_down = 0.0
            for line in ma_group:
                curr = self._line_value(line, s)
                prev = self._line_value(line, s + 1)
                u, d = self._dir_score(curr, prev)
                tf_up += u
                tf_down += d
            up_scores.append(tf_up)
            down_scores.append(tf_down)

        ac1_vals = [self._line_value(self.ac_tf1.ac, s + i) for i in range(4)]
        ac3_vals = [self._line_value(self.ac_tf3.ac, s + i) for i in range(4)]
        u1ac, d1ac = self._ac_score(ac1_vals[0], ac1_vals[1], ac1_vals[2], ac1_vals[3])
        u3ac, d3ac = self._ac_score(ac3_vals[0], ac3_vals[1], ac3_vals[2], ac3_vals[3])
        u2ac = d2ac = 0.0

        uitog1 = (up_scores[0] + u1ac) * 12.5
        uitog2 = (up_scores[1] + u2ac) * 12.5
        uitog3 = (up_scores[2] + u3ac) * 12.5
        ditog1 = (down_scores[0] + d1ac) * 12.5
        ditog2 = (down_scores[1] + d2ac) * 12.5
        ditog3 = (down_scores[2] + d3ac) * 12.5

        signal = 0
        if uitog1 > 50 and uitog2 > 50 and uitog3 > 50:
            signal = 1
        if ditog1 > 50 and ditog2 > 50 and ditog3 > 50:
            signal = -1
        if uitog1 >= 75 and uitog2 >= 75 and uitog3 >= 75:
            signal = 2
        if ditog1 >= 75 and ditog2 >= 75 and ditog3 >= 75:
            signal = -2
        return signal

    def _apply_trailing(self):
        if int(self.p.trailing) <= 0 or not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            nsl = float(self.data.close[0]) - float(self.p.point) * float(self.p.trailing)
            if nsl >= float(self.position.price) and (self.stop_price is None or nsl > self.stop_price):
                self.stop_price = nsl
        else:
            nsl = float(self.data.close[0]) + float(self.p.point) * float(self.p.trailing)
            if nsl <= float(self.position.price) and (self.stop_price is None or nsl < self.stop_price):
                self.stop_price = nsl
        if self.position.size > 0 and self.stop_price is not None and low <= self.stop_price:
            self.log(f'close long by trailing={self.stop_price:.5f}')
            self.order = self.close()
            return True
        if self.position.size < 0 and self.stop_price is not None and high >= self.stop_price:
            self.log(f'close short by trailing={self.stop_price:.5f}')
            self.order = self.close()
            return True
        return False

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
        if min(len(self.tf1), len(self.tf2), len(self.tf3)) < max(self.p.ma_periods) + int(self.p.shift) + 4:
            return
        if self.order is not None:
            return

        if self._apply_trailing():
            return
        if self._check_exit_levels():
            return

        signal = self._signal_value()
        open_buy = signal > int(self.p.open_level)
        open_sell = signal < -int(self.p.open_level)
        close_buy = signal < -int(self.p.close_level)
        close_sell = signal > int(self.p.close_level)

        if self.position:
            if self.position.size > 0 and close_buy:
                self.log(f'close long by signal={signal}')
                self.order = self.close()
                return
            if self.position.size < 0 and close_sell:
                self.log(f'close short by signal={signal}')
                self.order = self.close()
                return
            return

        lot = max(round(float(self.p.lots), 2), 0.01)
        px = float(self.data.close[0])
        if open_buy and not open_sell and not close_buy:
            self.signal_count += 1
            self.stop_price = px - float(self.p.point) * float(self.p.stop_loss) if int(self.p.stop_loss) > 0 else None
            self.take_price = px + float(self.p.point) * float(self.p.take_profit) if int(self.p.take_profit) > 0 else None
            self.log(f'buy signal={signal} lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return
        if open_sell and not open_buy and not close_sell:
            self.signal_count += 1
            self.stop_price = px + float(self.p.point) * float(self.p.stop_loss) if int(self.p.stop_loss) > 0 else None
            self.take_price = px - float(self.p.point) * float(self.p.take_profit) if int(self.p.take_profit) > 0 else None
            self.log(f'sell signal={signal} lot={lot:.2f}')
            self.order = self.sell(size=lot)
            return

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
