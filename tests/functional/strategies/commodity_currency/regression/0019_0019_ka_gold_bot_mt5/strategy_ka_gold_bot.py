from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
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
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('spread', 6),
    )


class HighLowAverage(bt.Indicator):
    lines = ('avg',)
    params = (('period', 50),)

    def __init__(self):
        self.addminperiod(self.p.period)

    def next(self):
        total = 0.0
        for i in range(self.p.period):
            total += float(self.data.high[-i] - self.data.low[-i])
        self.lines.avg[0] = total / self.p.period


class KAGoldBotStrategy(bt.Strategy):
    params = dict(
        inp_keltner_period=50,
        inp_ema10=10,
        inp_ema200=200,
        inpuser_lot=0.01,
        inp_sl_pips=500,
        inp_tp_pips=500,
        inp_max_slippage=3,
        inp_max_spread=65,
        inp_trailing_trigger=300,
        inp_trailing_stop=300,
        inp_trailing_step=100,
        inp_time_filter=True,
        inp_start_hour=2,
        inp_start_minute=30,
        inp_end_hour=21,
        inp_end_minute=0,
        isvolume_percent=True,
        inp_risk=1.0,
        inp_magic=240219,
        point=0.01,
        price_digits=2,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
    )

    def __init__(self):
        self.ema10 = bt.ind.EMA(self.data.close, period=self.p.inp_ema10)
        self.ema200 = bt.ind.EMA(self.data.close, period=self.p.inp_ema200)
        self.keltner_mid = bt.ind.EMA(self.data.close, period=self.p.inp_keltner_period)
        self.range_avg = HighLowAverage(self.data, period=self.p.inp_keltner_period)

        self.entry_order = None
        self.stop_order = None
        self.tp_order = None
        self.stop_price = None
        self.tp_price = None
        self.trailing_active_buy = False
        self.trailing_active_sell = False

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _pips_to_price(self, pips):
        if self.p.price_digits % 2 == 1:
            return pips * self.p.point * 10.0
        return pips * self.p.point

    def _current_time_allowed(self, dt):
        if not self.p.inp_time_filter:
            return True
        current = dt.hour * 60 + dt.minute
        start = self.p.inp_start_hour * 60 + self.p.inp_start_minute
        end = self.p.inp_end_hour * 60 + self.p.inp_end_minute
        return start <= current < end

    def _check_spread_allow(self):
        return self.p.inp_max_spread == 0 or float(self.data.spread[0]) <= self.p.inp_max_spread

    def _round_volume(self, volume):
        step = self.p.volume_step
        volume = step * int(volume / step)
        volume = max(volume, self.p.volume_min)
        volume = min(volume, self.p.volume_max)
        return round(volume, 4)

    def _calculate_volume(self):
        if not self.p.isvolume_percent:
            return self._round_volume(self.p.inpuser_lot)
        lot_size = self.p.inp_risk * self.broker.get_cash() / 100000.0
        base = self.p.inpuser_lot
        n = int(lot_size / base)
        lot_size = n * base
        if lot_size < base:
            lot_size = base
        return self._round_volume(lot_size)

    def _cancel_exit_orders(self):
        for order in (self.stop_order, self.tp_order):
            if order is not None and order.alive():
                self.cancel(order)
        self.stop_order = None
        self.tp_order = None

    def _submit_exit_orders(self):
        self._cancel_exit_orders()
        if not self.position:
            return
        if self.position.size > 0:
            self.stop_order = self.sell(size=abs(self.position.size), exectype=bt.Order.Stop, price=self.stop_price)
            if self.tp_price:
                self.tp_order = self.sell(size=abs(self.position.size), exectype=bt.Order.Limit, price=self.tp_price)
        else:
            self.stop_order = self.buy(size=abs(self.position.size), exectype=bt.Order.Stop, price=self.stop_price)
            if self.tp_price:
                self.tp_order = self.buy(size=abs(self.position.size), exectype=bt.Order.Limit, price=self.tp_price)

    def _calculate_signal(self):
        upper1 = float(self.keltner_mid[0] + self.range_avg[0])
        lower1 = float(self.keltner_mid[0] - self.range_avg[0])
        upper2 = float(self.keltner_mid[-1] + self.range_avg[-1])
        lower2 = float(self.keltner_mid[-1] - self.range_avg[-1])
        ema10_1 = float(self.ema10[0])
        ema10_2 = float(self.ema10[-1])
        ema200_1 = float(self.ema200[0])
        close1 = float(self.data.close[0])

        entry_buy1 = close1 > upper1
        entry_buy2 = close1 > ema200_1
        entry_buy3 = ema10_2 < upper2 and ema10_1 > upper1
        if entry_buy1 and entry_buy2 and entry_buy3:
            return 'buy'

        entry_sell1 = close1 < lower1
        entry_sell2 = close1 < ema200_1
        entry_sell3 = ema10_2 > lower2 and ema10_1 < lower1
        if entry_sell1 and entry_sell2 and entry_sell3:
            return 'sell'
        return None

    def _open_trade(self, side):
        if not self._check_spread_allow():
            return
        volume = self._calculate_volume()
        open_price = float(self.data.close[0])
        sl_distance = self._pips_to_price(self.p.inp_sl_pips)
        tp_distance = self._pips_to_price(self.p.inp_tp_pips)

        if side == 'buy':
            self.stop_price = round(open_price - sl_distance, self.p.price_digits)
            self.tp_price = round(open_price + tp_distance, self.p.price_digits) if self.p.inp_tp_pips != 0 else None
            self.entry_order = self.buy(size=volume)
            self.log(f'buy signal open={open_price:.2f} sl={self.stop_price:.2f} tp={self.tp_price}')
        else:
            self.stop_price = round(open_price + sl_distance, self.p.price_digits)
            self.tp_price = round(open_price - tp_distance, self.p.price_digits) if self.p.inp_tp_pips != 0 else None
            self.entry_order = self.sell(size=volume)
            self.log(f'sell signal open={open_price:.2f} sl={self.stop_price:.2f} tp={self.tp_price}')

    def _update_trailing(self):
        if not self.position:
            return
        close_price = float(self.data.close[0])
        trigger = self._pips_to_price(self.p.inp_trailing_trigger)
        trailing_stop = self._pips_to_price(self.p.inp_trailing_stop)
        trailing_step = self._pips_to_price(self.p.inp_trailing_step)

        if self.position.size > 0:
            profit = close_price - self.position.price
            if not self.trailing_active_buy and profit > trigger:
                self.trailing_active_buy = True
            if self.trailing_active_buy:
                candidate = round(close_price - trailing_stop, self.p.price_digits)
                if self.stop_price is None or candidate > self.stop_price + trailing_step:
                    self.stop_price = candidate
                    self._submit_exit_orders()
                    self.log(f'update trailing buy sl={self.stop_price:.2f}')
        else:
            profit = self.position.price - close_price
            if not self.trailing_active_sell and profit > trigger:
                self.trailing_active_sell = True
            if self.trailing_active_sell:
                candidate = round(close_price + trailing_stop, self.p.price_digits)
                if self.stop_price is None or candidate < self.stop_price - trailing_step:
                    self.stop_price = candidate
                    self._submit_exit_orders()
                    self.log(f'update trailing sell sl={self.stop_price:.2f}')

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(self.p.inp_keltner_period, self.p.inp_ema200) + 2:
            return
        self._update_trailing()
        if self.position or self.entry_order is not None:
            return
        dt = bt.num2date(self.data.datetime[0])
        if not self._current_time_allowed(dt):
            return
        signal = self._calculate_signal()
        if signal is not None:
            self._open_trade(signal)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order is self.entry_order:
            if order.status == order.Completed:
                self.entry_order = None
                self._submit_exit_orders()
                if order.isbuy():
                    self.log(f'buy filled price={order.executed.price:.2f}')
                else:
                    self.log(f'sell filled price={order.executed.price:.2f}')
            else:
                self.entry_order = None
            return
        if order in (self.stop_order, self.tp_order):
            if order.status == order.Completed:
                sibling = self.tp_order if order is self.stop_order else self.stop_order
                if sibling is not None and sibling.alive():
                    self.cancel(sibling)
            if order is self.stop_order and order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.stop_order = None
            if order is self.tp_order and order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.tp_order = None

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
        self.trailing_active_buy = False
        self.trailing_active_sell = False
        self._position_was_open = False
        self.stop_price = None
        self.tp_price = None
        self.stop_order = None
        self.tp_order = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
