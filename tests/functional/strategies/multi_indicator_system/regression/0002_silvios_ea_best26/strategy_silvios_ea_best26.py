from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

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


class SilviosEABest26Strategy(bt.Strategy):
    params = dict(
        magic_number=20260111,
        risk_percent=1.0,
        max_spread_pips=3.0,
        stop_loss_pips=25,
        take_profit_pips=75,
        break_even_pips=5,
        trailing_stop_pips=15,
        rsi_period=14,
        lookback_period=48,
        zone_buffer_pips=10,
        long_rsi_entry=40.0,
        short_rsi_entry=55.0,
        long_rsi_exit=65.0,
        short_rsi_exit=35.0,
        point=0.01,
        price_digits=2,
        tick_value=1.0,
        margin_required_per_lot=250.0,
        volume_step=0.01,
        volume_min=0.01,
        volume_max=100.0,
    )

    def __init__(self):
        self.rsi = bt.ind.RSI(self.data.close, period=self.p.rsi_period)
        self.entry_order = None
        self.stop_order = None
        self.tp_order = None
        self.close_order = None
        self.entry_price = None
        self.stop_price = None
        self.tp_price = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _pip_size(self):
        return self.p.point * 10.0

    def _round_price(self, price):
        return round(price, self.p.price_digits)

    def _round_volume(self, volume):
        step = self.p.volume_step
        volume = round(volume / step) * step if step > 0 else 0.0
        volume = max(self.p.volume_min, min(self.p.volume_max, volume))
        return round(volume, 8)

    def _calculate_lot_size(self):
        if self.p.tick_value <= 0:
            return 0.0
        account_value = self.broker.getvalue()
        free_cash = self.broker.getcash()
        risk_amount = account_value * (self.p.risk_percent / 100.0)
        per_lot_risk = self.p.stop_loss_pips * 10.0 * self.p.tick_value
        if per_lot_risk <= 0:
            return 0.0
        lot = risk_amount / per_lot_risk
        if self.p.margin_required_per_lot > 0:
            max_lot_possible = free_cash / self.p.margin_required_per_lot
            if lot > max_lot_possible:
                lot = max_lot_possible * 0.90
        lot = self._round_volume(lot)
        if self.p.margin_required_per_lot > 0 and lot * self.p.margin_required_per_lot > free_cash:
            return 0.0
        return lot

    def _recent_low(self):
        return min(float(self.data.low[-i]) for i in range(1, self.p.lookback_period + 1))

    def _recent_high(self):
        return max(float(self.data.high[-i]) for i in range(1, self.p.lookback_period + 1))

    def _cancel_exit_orders(self):
        for order in (self.stop_order, self.tp_order):
            if order is not None and order.alive():
                self.cancel(order)
        self.stop_order = None
        self.tp_order = None

    def _submit_exit_orders(self):
        size = abs(self.position.size)
        if size <= 0:
            return
        if self.position.size > 0:
            self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.stop_price)
            self.tp_order = self.sell(size=size, exectype=bt.Order.Limit, price=self.tp_price, oco=self.stop_order)
        else:
            self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.stop_price)
            self.tp_order = self.buy(size=size, exectype=bt.Order.Limit, price=self.tp_price, oco=self.stop_order)

    def _replace_stop(self, new_stop):
        size = abs(self.position.size)
        if size <= 0:
            return
        if self.position.size > 0 and new_stop <= self.stop_price:
            return
        if self.position.size < 0 and new_stop >= self.stop_price:
            return
        if self.stop_order is not None and self.stop_order.alive():
            self.cancel(self.stop_order)
        self.stop_price = self._round_price(new_stop)
        if self.position.size > 0:
            self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.stop_price, oco=self.tp_order)
        else:
            self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.stop_price, oco=self.tp_order)
        self.log(f'update stop -> {self.stop_price:.2f}')

    def _reset_trade_state(self):
        self.entry_order = None
        self.stop_order = None
        self.tp_order = None
        self.close_order = None
        self.entry_price = None
        self.stop_price = None
        self.tp_price = None

    def _sync_trade_state_from_position(self):
        if not self.position:
            return
        if self.entry_price is None:
            self.entry_price = float(self.position.price)
        pip = self._pip_size()
        if self.position.size > 0:
            if self.stop_price is None:
                self.stop_price = self._round_price(self.entry_price - (self.p.stop_loss_pips * pip))
            if self.tp_price is None:
                self.tp_price = self._round_price(self.entry_price + (self.p.take_profit_pips * pip))
        else:
            if self.stop_price is None:
                self.stop_price = self._round_price(self.entry_price + (self.p.stop_loss_pips * pip))
            if self.tp_price is None:
                self.tp_price = self._round_price(self.entry_price - (self.p.take_profit_pips * pip))
        if self.stop_order is None and self.tp_order is None and self.close_order is None:
            self._submit_exit_orders()

    def _manage_position(self):
        if self.close_order is not None and self.close_order.alive():
            return
        self._sync_trade_state_from_position()
        rsi_now = float(self.rsi[0])
        close_price = float(self.data.close[0])
        pip = self._pip_size()
        if self.position.size > 0:
            if rsi_now > self.p.long_rsi_exit and self.close_order is None:
                self._cancel_exit_orders()
                self.close_order = self.close()
                self.log(f'early-exit long rsi={rsi_now:.2f}')
                return
            new_stop = self.stop_price
            if close_price >= self.entry_price + (self.p.break_even_pips * pip) and new_stop < self.entry_price:
                new_stop = self.entry_price + (2.0 * pip)
            trail_price = close_price - (self.p.trailing_stop_pips * pip)
            if trail_price > new_stop + (3.0 * pip):
                new_stop = trail_price
            if new_stop > self.stop_price + self.p.point:
                self._replace_stop(new_stop)
        else:
            if rsi_now < self.p.short_rsi_exit and self.close_order is None:
                self._cancel_exit_orders()
                self.close_order = self.close()
                self.log(f'early-exit short rsi={rsi_now:.2f}')
                return
            new_stop = self.stop_price
            if close_price <= self.entry_price - (self.p.break_even_pips * pip) and new_stop >= self.entry_price:
                new_stop = self.entry_price - (2.0 * pip)
            trail_price = close_price + (self.p.trailing_stop_pips * pip)
            if trail_price < new_stop - (3.0 * pip):
                new_stop = trail_price
            if new_stop < self.stop_price - self.p.point:
                self._replace_stop(new_stop)

    def next(self):
        self.bar_num += 1
        required_bars = max(self.p.lookback_period + 1, self.p.rsi_period + 2)
        if len(self.data) < required_bars:
            return
        rsi_now = float(self.rsi[0])
        if math.isnan(rsi_now):
            return
        if self.position:
            self._manage_position()
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        spread_value = float(self.data.spread[0])
        spread_pips = spread_value / 10.0 if not math.isnan(spread_value) else 0.0
        if spread_pips > self.p.max_spread_pips:
            return
        size = self._calculate_lot_size()
        if size <= 0:
            return
        close_price = float(self.data.close[0])
        buffer_price = self.p.zone_buffer_pips * self._pip_size()
        recent_low = self._recent_low()
        recent_high = self._recent_high()
        if close_price <= recent_low + buffer_price and rsi_now < self.p.long_rsi_entry:
            self.entry_order = self.buy(size=size)
            self.buy_count += 1
            self.log(f'long signal close={close_price:.2f} zone={recent_low + buffer_price:.2f} rsi={rsi_now:.2f} size={size:.2f}')
        elif close_price >= recent_high - buffer_price and rsi_now > self.p.short_rsi_entry:
            self.entry_order = self.sell(size=size)
            self.sell_count += 1
            self.log(f'short signal close={close_price:.2f} zone={recent_high - buffer_price:.2f} rsi={rsi_now:.2f} size={size:.2f}')

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order is self.entry_order:
            if order.status == order.Completed:
                self.entry_price = float(order.executed.price)
                pip = self._pip_size()
                if order.isbuy():
                    self.stop_price = self._round_price(self.entry_price - (self.p.stop_loss_pips * pip))
                    self.tp_price = self._round_price(self.entry_price + (self.p.take_profit_pips * pip))
                    self.log(f'long filled price={self.entry_price:.2f} sl={self.stop_price:.2f} tp={self.tp_price:.2f}')
                else:
                    self.stop_price = self._round_price(self.entry_price + (self.p.stop_loss_pips * pip))
                    self.tp_price = self._round_price(self.entry_price - (self.p.take_profit_pips * pip))
                    self.log(f'short filled price={self.entry_price:.2f} sl={self.stop_price:.2f} tp={self.tp_price:.2f}')
                self.entry_order = None
                self._submit_exit_orders()
            else:
                self.log(f'entry status={order.getstatusname()}')
                self.entry_order = None
            return
        if order is self.stop_order:
            if order.status == order.Completed:
                self.log(f'stop filled price={order.executed.price:.2f}')
                self.stop_order = None
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.stop_order = None
            return
        if order is self.tp_order:
            if order.status == order.Completed:
                self.log(f'take-profit filled price={order.executed.price:.2f}')
                self.tp_order = None
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.tp_order = None
            return
        if order is self.close_order:
            if order.status == order.Completed:
                self.log(f'manual close filled price={order.executed.price:.2f}')
                self.close_order = None
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.close_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f} pnl_net={trade.pnlcomm:.2f}')
        self._reset_trade_state()
