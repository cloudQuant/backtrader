from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import backtrader.feeds as btfeeds
import pandas as pd


TO_DOWN = -1
NO_TREND = 0
TO_UP = 1
DOWN = -2
UP = 2


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


class RenkoLineBreak(bt.Indicator):
    lines = ('upper', 'lower', 'boxes')
    params = dict(
        min_box_size=500,
        point=0.01,
    )

    def __init__(self):
        box_size = float(self.p.min_box_size)
        if box_size < 0:
            box_size = 300.0
        self._box_size = box_size * float(self.p.point)
        self._seed_close = None
        self._initialized = False
        self._up = False
        self.addminperiod(1)

    def next(self):
        price = float(self.data.close[0])

        if self._seed_close is None:
            self._seed_close = price
            self.lines.upper[0] = 0.0
            self.lines.lower[0] = 0.0
            self.lines.boxes[0] = 0.0
            return

        if not self._initialized:
            if abs(price - self._seed_close) < self._box_size:
                self.lines.upper[0] = 0.0
                self.lines.lower[0] = 0.0
                self.lines.boxes[0] = 0.0
                return
            if price > self._seed_close:
                self.lines.upper[0] = price
                self.lines.lower[0] = self._seed_close
                self.lines.boxes[0] = 1.0
                self._up = True
            else:
                self.lines.upper[0] = self._seed_close
                self.lines.lower[0] = price
                self.lines.boxes[0] = -1.0
                self._up = False
            self._initialized = True
            return

        prev_up = float(self.lines.upper[-1])
        prev_dn = float(self.lines.lower[-1])
        prev_boxes = float(self.lines.boxes[-1])

        if price >= prev_up + self._box_size:
            self.lines.upper[0] = price
            self.lines.lower[0] = prev_up
            if self._up:
                self.lines.boxes[0] = prev_boxes + 1.0
            else:
                self._up = True
                self.lines.boxes[0] = 1.0
            return

        if price <= prev_dn - self._box_size:
            self.lines.upper[0] = prev_dn
            self.lines.lower[0] = price
            if self._up:
                self._up = False
                self.lines.boxes[0] = -1.0
            else:
                self.lines.boxes[0] = prev_boxes - 1.0
            return

        self.lines.upper[0] = prev_up
        self.lines.lower[0] = prev_dn
        self.lines.boxes[0] = prev_boxes


class RenkoLineBreakVsRsiStrategy(bt.Strategy):
    params = dict(
        min_box_size=500,
        rsi_period=4,
        rsi_vertical_shift=20,
        take_profit=1000,
        indent_from_hl=50,
        volume=1.0,
        point=0.01,
        spread_points=0.0,
    )

    def __init__(self):
        self.rlb = RenkoLineBreak(self.data, min_box_size=self.p.min_box_size, point=self.p.point)
        self.rsi = bt.indicators.RSI(self.data.close, period=int(self.p.rsi_period), safediv=True)

        self.order = None
        self.stop_price = None
        self.take_price = None
        self.pending_direction = None
        self.pending_open = None
        self.pending_stop = None
        self.pending_target = None

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

        self.addminperiod(max(5, int(self.p.rsi_period) + 2))

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _trend(self):
        if len(self) < 2:
            return NO_TREND
        current = float(self.rlb.boxes[0])
        previous = float(self.rlb.boxes[-1])
        if current > 0.0:
            return TO_UP if previous < 0.0 else UP
        if current < 0.0:
            return TO_DOWN if previous > 0.0 else DOWN
        return NO_TREND

    def _clear_pending(self):
        self.pending_direction = None
        self.pending_open = None
        self.pending_stop = None
        self.pending_target = None

    def _queue_pending(self, direction):
        if len(self) < 4:
            return False

        indent = float(self.p.indent_from_hl) * float(self.p.point)
        spread = float(self.p.spread_points) * float(self.p.point)
        take_profit = float(self.p.take_profit) * float(self.p.point)

        highs = [float(self.data.high[-i]) for i in range(3, 0, -1)]
        lows = [float(self.data.low[-i]) for i in range(3, 0, -1)]

        if direction > 0:
            open_price = highs[-1] + indent + spread
            stop_price = min(lows) - indent
            target_price = open_price + take_profit
        else:
            open_price = lows[-1] - indent
            stop_price = max(highs) + indent + spread
            target_price = open_price - take_profit

        self.pending_direction = int(direction)
        self.pending_open = open_price
        self.pending_stop = stop_price
        self.pending_target = target_price
        return True

    def _check_pending_trigger(self):
        if self.pending_direction is None or self.position or self.order is not None:
            return False

        high = float(self.data.high[0])
        low = float(self.data.low[0])
        size = max(float(self.p.volume), 0.01)

        if self.pending_direction > 0 and high >= float(self.pending_open):
            self.signal_count += 1
            self.stop_price = float(self.pending_stop)
            self.take_price = float(self.pending_target)
            self.log(f'buy stop triggered open={self.pending_open:.5f} size={size:.2f}')
            self._clear_pending()
            self.order = self.buy(size=size)
            return True

        if self.pending_direction < 0 and low <= float(self.pending_open):
            self.signal_count += 1
            self.stop_price = float(self.pending_stop)
            self.take_price = float(self.pending_target)
            self.log(f'sell stop triggered open={self.pending_open:.5f} size={size:.2f}')
            self._clear_pending()
            self.order = self.sell(size=size)
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
        if self.order is not None:
            return

        trend = self._trend()
        rsi_value = float(self.rsi[0])
        upper_rsi = 50.0 + float(self.p.rsi_vertical_shift)
        lower_rsi = 50.0 - float(self.p.rsi_vertical_shift)

        if self.position:
            if self._check_exit_levels():
                return
            close_condition = False
            if self.position.size > 0:
                if trend == TO_DOWN or rsi_value > upper_rsi:
                    close_condition = True
            elif self.position.size < 0:
                if trend == TO_UP or (rsi_value >= 0.0 and rsi_value < lower_rsi):
                    close_condition = True
            if close_condition:
                self.log(f'close by trend/rsi trend={trend} rsi={rsi_value:.2f}')
                self.order = self.close()
            return

        if trend in (TO_UP, TO_DOWN):
            self._clear_pending()

        if self._check_pending_trigger():
            return

        desired_direction = None
        if trend == UP and rsi_value < lower_rsi and rsi_value >= 0.0:
            desired_direction = 1
        elif trend == DOWN and rsi_value > upper_rsi:
            desired_direction = -1

        if desired_direction is not None:
            if self._queue_pending(desired_direction):
                side = 'buy_stop' if desired_direction > 0 else 'sell_stop'
                self.log(f'queue {side} open={self.pending_open:.5f} stop={self.pending_stop:.5f} target={self.pending_target:.5f}')

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
