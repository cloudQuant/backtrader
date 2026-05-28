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


class MalrIndicator(bt.Indicator):
    lines = ('malr', 'malrh', 'malrl', 'malrhh', 'malrll')
    params = dict(
        ma_period=120,
        ma_shift=0,
        channel_reversal=1.1,
        channel_breakout=1.1,
    )

    def __init__(self):
        sma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.ma_period)
        lwma = bt.indicators.WeightedMovingAverage(self.data.close, period=self.p.ma_period)
        self._ff = 3.0 * lwma - 2.0 * sma
        diff = self.data.close - self._ff
        self._std = bt.indicators.StandardDeviation(diff, period=self.p.ma_period)
        self.addminperiod(int(self.p.ma_period) * 2 + 3)

    def next(self):
        ff = float(self._ff[0])
        std = float(self._std[0])
        t1 = std * float(self.p.channel_reversal)
        t2 = std * (float(self.p.channel_reversal) + float(self.p.channel_breakout))
        self.lines.malr[0] = ff
        self.lines.malrh[0] = ff + t1
        self.lines.malrl[0] = ff - t1
        self.lines.malrhh[0] = ff + t2
        self.lines.malrll[0] = ff - t2

    def once(self, start, end):
        ff_array = self._ff.array
        std_array = self._std.array
        lines = (
            self.lines.malr.array,
            self.lines.malrh.array,
            self.lines.malrl.array,
            self.lines.malrhh.array,
            self.lines.malrll.array,
        )
        for line in lines:
            while len(line) < end:
                line.append(float('nan'))

        actual_end = min(end, len(ff_array), len(std_array))
        for i in range(start, actual_end):
            ff = float(ff_array[i])
            std = float(std_array[i])
            t1 = std * float(self.p.channel_reversal)
            t2 = std * (float(self.p.channel_reversal) + float(self.p.channel_breakout))
            lines[0][i] = ff
            lines[1][i] = ff + t1
            lines[2][i] = ff - t1
            lines[3][i] = ff + t2
            lines[4][i] = ff - t2


class EaMalrStrategy(bt.Strategy):
    params = dict(
        lot=0.1,
        sl=2550,
        tp=2578,
        use_averaging=False,
        loss_for_averaging=500,
        position_overturn=True,
        koff_multiplication=2.0,
        use_increase=True,
        max_drawdown=5000,
        trail_stoploss=False,
        trail=200,
        activate_by_profit=True,
        profit=50,
        ma_period=120,
        ma_shift=0,
        channel_reversal=1.1,
        channel_breakout=1.1,
        point=0.01,
        max_lot=100.0,
        min_lot=0.01,
    )

    def __init__(self):
        self.malr = MalrIndicator(
            self.data,
            ma_period=self.p.ma_period,
            ma_shift=self.p.ma_shift,
            channel_reversal=self.p.channel_reversal,
            channel_breakout=self.p.channel_breakout,
        )
        self.order = None
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.prev_open = None
        self.prev_avlot = None
        self.stop_price = None
        self.take_price = None
        self._pending_entry_mode = None
        self._pending_overturn = None
        self._pending_after_close = None
        self._position_was_open = False
        self.addminperiod(self.p.ma_period + 5)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _cross_to_sell(self):
        return float(self.malr.malrhh[-1]) <= float(self.data.close[-1]) and float(self.malr.malrhh[-2]) >= float(self.data.close[-2])

    def _cross_to_buy(self):
        return float(self.malr.malrll[-1]) >= float(self.data.close[-1]) and float(self.malr.malrll[-2]) <= float(self.data.close[-2])

    def _floating_loss_points(self):
        if not self.position or self.prev_open is None:
            return 0.0
        if self.position.size > 0:
            return max(0.0, (float(self.prev_open) - float(self.data.close[0])) / float(self.p.point))
        return max(0.0, (float(self.data.close[0]) - float(self.prev_open)) / float(self.p.point))

    def _clamp_lot(self, lot):
        lot = round(float(lot), 2)
        lot = min(lot, float(self.p.max_lot))
        lot = max(lot, float(self.p.min_lot))
        return lot

    def _base_lot(self):
        lot = float(self.p.lot)
        if self.p.use_increase and not self.position and self.p.max_drawdown:
            lot = float(self.p.lot) * float(self.broker.getvalue()) / float(self.p.max_drawdown)
        return self._clamp_lot(lot)

    def _prepare_exit_levels(self, direction, entry_price):
        if direction > 0:
            self.stop_price = entry_price - float(self.p.sl) * float(self.p.point) if int(self.p.sl) > 0 else None
            self.take_price = entry_price + float(self.p.tp) * float(self.p.point) if int(self.p.tp) > 0 else None
        else:
            self.stop_price = entry_price + float(self.p.sl) * float(self.p.point) if int(self.p.sl) > 0 else None
            self.take_price = entry_price - float(self.p.tp) * float(self.p.point) if int(self.p.tp) > 0 else None

    def _place_entry(self, direction, mode):
        if self.order is not None:
            return False
        if mode == 1:
            lot = self._base_lot()
        elif mode == 2:
            lot = self._clamp_lot(self.prev_avlot if self.prev_avlot else self._base_lot())
        else:
            current_size = abs(float(self.position.size)) if self.position else self._base_lot()
            lot = self._clamp_lot(current_size * float(self.p.koff_multiplication) if float(self.p.koff_multiplication) > 0 else current_size)
        self.signal_count += 1
        side = 'buy' if direction > 0 else 'sell'
        self.log(f'open {side} mode={mode} lot={lot:.2f}')
        self._pending_entry_mode = mode
        self.order = self.buy(size=lot) if direction > 0 else self.sell(size=lot)
        self._pending_after_close = None
        self._pending_overturn = (direction, mode)
        return True

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

    def _apply_trailing(self):
        if not self.position or self.order is not None or not self.p.trail_stoploss:
            return False
        close_px = float(self.data.close[0])
        if self.position.size > 0:
            activate = float(self.position.price) + float(self.p.profit) * float(self.p.point)
            if (not self.p.activate_by_profit) or close_px >= activate:
                price = close_px - float(self.p.trail) * float(self.p.point)
                if self.stop_price is None or price > self.stop_price:
                    self.stop_price = price
        else:
            activate = float(self.position.price) - float(self.p.profit) * float(self.p.point)
            if (not self.p.activate_by_profit) or close_px <= activate:
                price = close_px + float(self.p.trail) * float(self.p.point)
                if self.stop_price is None or price < self.stop_price:
                    self.stop_price = price
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < self.p.ma_period + 3:
            return
        if self.order is not None:
            return

        self._apply_trailing()
        if self._check_exit_levels():
            return

        sell_signal = self._cross_to_sell()
        buy_signal = self._cross_to_buy()
        if not sell_signal and not buy_signal:
            return

        if sell_signal:
            if self.position and self.position.size > 0 and self.p.position_overturn:
                self._pending_after_close = (-1, 3)
                self.log('reverse long to short')
                self.order = self.close()
                return
            if self.position and not self.p.use_averaging:
                return
            if self.position and self.position.size < 0 and self.p.use_averaging:
                if self._floating_loss_points() >= float(self.p.loss_for_averaging):
                    self._place_entry(-1, 2)
                return
            if not self.position:
                self._place_entry(-1, 1)
                return

        if buy_signal:
            if self.position and self.position.size < 0 and self.p.position_overturn:
                self._pending_after_close = (1, 3)
                self.log('reverse short to long')
                self.order = self.close()
                return
            if self.position and not self.p.use_averaging:
                return
            if self.position and self.position.size > 0 and self.p.use_averaging:
                if self._floating_loss_points() >= float(self.p.loss_for_averaging):
                    self._place_entry(1, 2)
                return
            if not self.position:
                self._place_entry(1, 1)
                return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy() and order.executed.size > 0:
                self.prev_open = float(order.executed.price)
                if self._pending_entry_mode in (1, 2) and self.prev_avlot is None:
                    self.prev_avlot = float(order.executed.size)
                elif self._pending_entry_mode in (1, 2) and self.position.size > 0:
                    self.prev_avlot = float(order.executed.size)
                self._prepare_exit_levels(1, self.prev_open)
            elif order.issell() and order.executed.size < 0:
                self.prev_open = float(order.executed.price)
                if self._pending_entry_mode in (1, 2) and self.prev_avlot is None:
                    self.prev_avlot = abs(float(order.executed.size))
                elif self._pending_entry_mode in (1, 2) and self.position.size < 0:
                    self.prev_avlot = abs(float(order.executed.size))
                self._prepare_exit_levels(-1, self.prev_open)
            elif order.exectype == bt.Order.Close:
                self.stop_price = None
                self.take_price = None
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
        completed = order.status == order.Completed
        self.order = None
        self._pending_entry_mode = None
        if completed and not self.position and self._pending_after_close is not None:
            direction, mode = self._pending_after_close
            self._pending_after_close = None
            self._place_entry(direction, mode)

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
