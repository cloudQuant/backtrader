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


class T3AlarmIndicator(bt.Indicator):
    lines = ('ma2', 'direction', 'buy_sig', 'sell_sig')
    params = dict(ma_period=19, ma_shift=0, ma_method='ema', ma_price='close')

    def __init__(self):
        price = self._price_line(self.p.ma_price)
        ma_cls = self._ma_class(self.p.ma_method)
        ma1 = ma_cls(price, period=self.p.ma_period)
        self.lines.ma2 = ma_cls(ma1, period=self.p.ma_period)
        self._ma_shift = int(self.p.ma_shift)
        self._prev_direction = 0

    def next(self):
        shift = self._ma_shift
        ma2_curr = self.lines.ma2[-shift] if shift > 0 else self.lines.ma2[0]
        ma2_prev = self.lines.ma2[-(shift + 1)] if True else self.lines.ma2[-1]

        if ma2_curr > ma2_prev:
            direction = 1
        elif ma2_curr < ma2_prev:
            direction = -1
        else:
            direction = self._prev_direction

        prev_dir = self._prev_direction
        self._prev_direction = direction
        self.lines.direction[0] = float(direction)
        self.lines.buy_sig[0] = 1.0 if (direction == 1 and prev_dir == -1) else 0.0
        self.lines.sell_sig[0] = 1.0 if (direction == -1 and prev_dir == 1) else 0.0

    def once(self, start, end):
        ma2 = self.lines.ma2.array
        direction_line = self.lines.direction.array
        buy_line = self.lines.buy_sig.array
        sell_line = self.lines.sell_sig.array
        for line in (direction_line, buy_line, sell_line):
            while len(line) < end:
                line.append(float('nan'))

        shift = self._ma_shift
        prev_direction = 0
        actual_end = min(end, len(ma2))
        for i in range(start, actual_end):
            curr_idx = i - shift if shift > 0 else i
            prev_idx = i - shift - 1
            if curr_idx < 0 or prev_idx < 0:
                direction = prev_direction
            else:
                ma2_curr = ma2[curr_idx]
                ma2_prev = ma2[prev_idx]
                if ma2_curr > ma2_prev:
                    direction = 1
                elif ma2_curr < ma2_prev:
                    direction = -1
                else:
                    direction = prev_direction

            prev_dir = prev_direction
            prev_direction = direction
            direction_line[i] = float(direction)
            buy_line[i] = 1.0 if (direction == 1 and prev_dir == -1) else 0.0
            sell_line[i] = 1.0 if (direction == -1 and prev_dir == 1) else 0.0
        self._prev_direction = prev_direction

    def _ma_class(self, method):
        name = str(method).lower()
        mapping = {
            'sma': bt.indicators.SimpleMovingAverage,
            'ema': bt.indicators.ExponentialMovingAverage,
            'smma': bt.indicators.SmoothedMovingAverage,
            'lwma': bt.indicators.WeightedMovingAverage,
            'wma': bt.indicators.WeightedMovingAverage,
        }
        return mapping.get(name, bt.indicators.ExponentialMovingAverage)

    def _price_line(self, price_name):
        name = str(price_name).lower()
        if name == 'open':
            return self.data.open
        if name == 'high':
            return self.data.high
        if name == 'low':
            return self.data.low
        if name == 'median':
            return (self.data.high + self.data.low) / 2.0
        if name == 'typical':
            return (self.data.high + self.data.low + self.data.close) / 3.0
        if name == 'weighted':
            return (self.data.high + self.data.low + self.data.close + self.data.close) / 4.0
        return self.data.close


class T3MAMTCStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        stop_loss=0,
        take_profit=300,
        shift=1,
        rev_close=True,
        ma_period=19,
        ma_shift=0,
        ma_method='ema',
        ma_price='close',
        point=0.01,
    )

    def __init__(self):
        self.t3alarm = T3AlarmIndicator(
            self.data,
            ma_period=self.p.ma_period,
            ma_shift=self.p.ma_shift,
            ma_method=self.p.ma_method,
            ma_price=self.p.ma_price,
        )

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.order = None
        self.stop_price = None
        self.take_price = None
        self._position_was_open = False

        self.addminperiod(self.p.ma_period * 2 + int(self.p.shift) + int(self.p.ma_shift) + 10)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _signal_buy(self):
        idx = -int(self.p.shift) if int(self.p.shift) > 0 else 0
        return bool(self.t3alarm.buy_sig[idx])

    def _signal_sell(self):
        idx = -int(self.p.shift) if int(self.p.shift) > 0 else 0
        return bool(self.t3alarm.sell_sig[idx])

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

        if self._check_exit_levels():
            return

        open_buy = self._signal_buy()
        open_sell = self._signal_sell()
        close_buy = open_sell if bool(self.p.rev_close) else False
        close_sell = open_buy if bool(self.p.rev_close) else False
        if (open_buy and not open_sell and not close_buy) or (open_sell and not open_buy and not close_sell):
            self.signal_count += 1

        if self.position:
            if self.position.size > 0 and close_buy:
                self.log('close long by reverse signal')
                self.order = self.close()
                return
            if self.position.size < 0 and close_sell:
                self.log('close short by reverse signal')
                self.order = self.close()
                return
            return

        lot = max(round(float(self.p.lots), 2), 0.01)
        px = float(self.data.close[0])
        if open_buy and not open_sell and not close_buy:
            self.stop_price = px - float(self.p.point) * float(self.p.stop_loss) if int(self.p.stop_loss) > 0 else None
            self.take_price = px + float(self.p.point) * float(self.p.take_profit) if int(self.p.take_profit) > 0 else None
            self.log(f'buy signal lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return

        if open_sell and not open_buy and not close_sell:
            self.stop_price = px + float(self.p.point) * float(self.p.stop_loss) if int(self.p.stop_loss) > 0 else None
            self.take_price = px - float(self.p.point) * float(self.p.take_profit) if int(self.p.take_profit) > 0 else None
            self.log(f'sell signal lot={lot:.2f}')
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
