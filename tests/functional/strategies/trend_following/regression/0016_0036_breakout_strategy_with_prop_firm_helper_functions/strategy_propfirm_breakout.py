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


class PropFirmBreakoutStrategy(bt.Strategy):
    params = dict(
        bot_name='Breakout Strategy with Prop Firm Challenge Helper',
        expert_magic=1,
        entry_period=20,
        entry_shift=1,
        exit_period=20,
        exit_shift=1,
        is_challenge=False,
        pass_criteria=110100.0,
        daily_loss_limit=4500.0,
        risk_per_trade=1.0,
        atr_period=20,
        tick_size=0.01,
        min_stop_distance=0.0,
        lot_step=0.01,
        volume_min=0.01,
        volume_max=100.0,
        value_per_price_unit=100.0,
    )

    def __init__(self):
        self.base_data = self.datas[0]
        self.trading_data = self.datas[1]
        self.atr = bt.ind.ATR(self.trading_data, period=self.p.atr_period)
        self.last_trading_len = 0
        self.long_entry_order = None
        self.short_entry_order = None
        self.exit_order = None
        self.close_order = None
        self.current_exit_price = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self.challenge_closed = False
        self.daily_closed_pnl = {}

    def log(self, text):
        dt = bt.num2date(self.base_data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _round_lot(self, lots):
        step = self.p.lot_step
        lots = max(lots, self.p.volume_min)
        lots = min(lots, self.p.volume_max)
        lots = int(lots / step) * step
        return round(max(lots, self.p.volume_min), 4)

    def _window_values(self, line, period, shift):
        return [float(line[-shift - i]) for i in range(period)]

    def highest_high(self, period, shift):
        return max(self._window_values(self.trading_data.high, period, shift))

    def lowest_low(self, period, shift):
        return min(self._window_values(self.trading_data.low, period, shift))

    def calculate_lot_size(self, stop_distance):
        if stop_distance <= 0:
            return self.p.volume_min
        equity = self.broker.getvalue()
        risk_money = self.p.risk_per_trade * equity / 100.0
        loss_per_lot = abs(stop_distance) * self.p.value_per_price_unit
        if loss_per_lot <= 0:
            return self.p.volume_min
        lots = risk_money / loss_per_lot
        return self._round_lot(lots)

    def _cancel_order(self, order):
        if order is not None and order.alive():
            self.cancel(order)

    def _cancel_entry_orders(self):
        self._cancel_order(self.long_entry_order)
        self._cancel_order(self.short_entry_order)
        self.long_entry_order = None
        self.short_entry_order = None

    def _cancel_exit_order(self):
        self._cancel_order(self.exit_order)
        self.exit_order = None

    def _new_trading_bar(self):
        current_len = len(self.trading_data)
        if current_len == self.last_trading_len:
            return False
        self.last_trading_len = current_len
        return True

    def _update_exit_stop(self, stop_price):
        self._cancel_exit_order()
        size = abs(self.position.size)
        if size == 0:
            self.current_exit_price = None
            return
        self.current_exit_price = stop_price
        if self.position.size > 0:
            self.exit_order = self.sell(size=size, exectype=bt.Order.Stop, price=stop_price)
        else:
            self.exit_order = self.buy(size=size, exectype=bt.Order.Stop, price=stop_price)

    def _today_key(self):
        return bt.num2date(self.base_data.datetime[0]).date().isoformat()

    def _today_closed_pnl(self):
        return self.daily_closed_pnl.get(self._today_key(), 0.0)

    def _clear_all(self, message):
        self.log(message)
        self.challenge_closed = True
        self._cancel_entry_orders()
        self._cancel_exit_order()
        if self.position and self.close_order is None:
            self.close_order = self.close()

    def _check_challenge_guards(self):
        if not self.p.is_challenge:
            return False
        equity = self.broker.getvalue()
        if equity > self.p.pass_criteria:
            self._clear_all('Prop Firm Challenge Passed!')
            return True
        current_balance = self.broker.getcash()
        starting_balance = current_balance - self._today_closed_pnl()
        if equity < starting_balance - self.p.daily_loss_limit:
            self._clear_all('Daily loss limit exceeded!')
            return True
        return self.challenge_closed

    def _manage_existing_position(self):
        if not self.position:
            return 0, 0
        atr = float(self.atr[-1]) if len(self.trading_data) > self.p.atr_period else 0.0
        trail_long = self.lowest_low(self.p.exit_period, self.p.exit_shift)
        trail_short = self.highest_high(self.p.exit_period, self.p.exit_shift)
        cp = float(self.base_data.close[0])
        if self.position.size > 0:
            if cp < trail_long:
                self._cancel_exit_order()
                if self.close_order is None:
                    self.close_order = self.close()
            else:
                current_stop = self.current_exit_price if self.current_exit_price is not None else 0.0
                if trail_long > current_stop + 0.1 * atr and cp - trail_long >= self.p.min_stop_distance:
                    self._update_exit_stop(trail_long)
            return 1, 0
        if cp > trail_short:
            self._cancel_exit_order()
            if self.close_order is None:
                self.close_order = self.close()
        else:
            current_stop = self.current_exit_price if self.current_exit_price is not None else float('inf')
            if trail_short < current_stop - 0.1 * atr and trail_short - cp >= self.p.min_stop_distance:
                self._update_exit_stop(trail_short)
        return 0, 1

    def _place_entry_orders(self):
        if self.position or self.challenge_closed:
            return
        current_price = float(self.base_data.close[0])
        trading_hh = self.highest_high(self.p.entry_period, self.p.entry_shift)
        trading_ll = self.lowest_low(self.p.entry_period, self.p.entry_shift)
        trigger_long = trading_hh + self.p.tick_size
        trigger_short = trading_ll - self.p.tick_size
        exit_long = self.lowest_low(self.p.exit_period, self.p.exit_shift)
        exit_short = self.highest_high(self.p.exit_period, self.p.exit_shift)
        if trigger_long - current_price >= self.p.min_stop_distance:
            stop_distance = trigger_long - exit_long
            lot_size = self.calculate_lot_size(stop_distance)
            self.long_entry_order = self.buy(exectype=bt.Order.Stop, price=trigger_long, size=lot_size)
            self.long_entry_order.addinfo(kind='entry_long', exit_price=exit_long)
        if current_price - trigger_short >= self.p.min_stop_distance:
            stop_distance = exit_short - trigger_short
            lot_size = self.calculate_lot_size(stop_distance)
            self.short_entry_order = self.sell(exectype=bt.Order.Stop, price=trigger_short, size=lot_size)
            self.short_entry_order.addinfo(kind='entry_short', exit_price=exit_short)

    def next(self):
        self.bar_num += 1
        required = max(self.p.entry_period + self.p.entry_shift, self.p.exit_period + self.p.exit_shift, self.p.atr_period + 1)
        if len(self.trading_data) <= required:
            return
        if not self._new_trading_bar():
            return
        if self._check_challenge_guards():
            return
        self._cancel_entry_orders()
        self._manage_existing_position()
        self._place_entry_orders()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        kind = getattr(order.info, 'kind', None)
        if order.status == order.Completed:
            if kind == 'entry_long':
                self.log(f'long stop filled price={order.executed.price:.2f}')
                self._cancel_order(self.short_entry_order)
                self.short_entry_order = None
                self.long_entry_order = None
                self._update_exit_stop(order.info.exit_price)
            elif kind == 'entry_short':
                self.log(f'short stop filled price={order.executed.price:.2f}')
                self._cancel_order(self.long_entry_order)
                self.long_entry_order = None
                self.short_entry_order = None
                self._update_exit_stop(order.info.exit_price)
            elif order is self.exit_order:
                self.exit_order = None
                self.current_exit_price = None
            elif order is self.close_order:
                self.close_order = None
                self.current_exit_price = None
        else:
            if order is self.long_entry_order:
                self.long_entry_order = None
            if order is self.short_entry_order:
                self.short_entry_order = None
            if order is self.exit_order:
                self.exit_order = None
            if order is self.close_order:
                self.close_order = None

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
        key = self._today_key()
        self.daily_closed_pnl[key] = self.daily_closed_pnl.get(key, 0.0) + trade.pnlcomm
        self._position_was_open = False
        self.current_exit_price = None
        self.exit_order = None
        self.close_order = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
