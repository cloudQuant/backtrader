from __future__ import absolute_import, division, print_function, unicode_literals

import io
import json
import os
from pathlib import Path

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


class BreakoutStrategy(bt.Strategy):
    params = dict(
        bot_name='BreakoutStrategy',
        expert_magic=1,
        entry_period=20,
        entry_shift=1,
        exit_period=20,
        exit_shift=1,
        exit_middle_line=True,
        risk_per_trade=0.01,
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
        self._semantic_log = None
        trade_log_root = os.environ.get('BT_TRADE_LOG_DIR', '').strip()
        if trade_log_root:
            semantic_path = Path(trade_log_root) / 'python' / 'semantic.log'
            semantic_path.parent.mkdir(parents=True, exist_ok=True)
            self._semantic_log = semantic_path.open('w', encoding='utf-8')

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

    def middle(self, period, shift):
        return (self.highest_high(period, shift) + self.lowest_low(period, shift)) / 2.0

    def calculate_lot_size(self, stop_distance, price):
        if stop_distance <= 0:
            return self.p.volume_min
        equity = self.broker.getvalue()
        risk_money = self.p.risk_per_trade * equity
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

    def _manage_existing_position(self):
        if not self.position:
            return 0, 0
        atr = float(self.atr[-1]) if len(self.trading_data) > self.p.atr_period else 0.0
        if self.p.exit_middle_line:
            trail_long = self.middle(self.p.exit_period, self.p.exit_shift)
            trail_short = trail_long
        else:
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
        if self.position:
            return
        current_price = float(self.base_data.close[0])
        trading_hh = self.highest_high(self.p.entry_period, self.p.entry_shift)
        trading_ll = self.lowest_low(self.p.entry_period, self.p.entry_shift)
        trigger_long = trading_hh + self.p.tick_size
        trigger_short = trading_ll - self.p.tick_size
        exit_long = self.lowest_low(self.p.exit_period, self.p.exit_shift)
        exit_short = self.highest_high(self.p.exit_period, self.p.exit_shift)
        if self.p.exit_middle_line:
            mid = self.middle(self.p.exit_period, self.p.exit_shift)
            exit_long = max(mid, exit_long)
            exit_short = min(mid, exit_short)
        if trigger_long - current_price >= self.p.min_stop_distance:
            stop_distance = trigger_long - exit_long
            lot_size = self.calculate_lot_size(stop_distance, trigger_long)
            self._log_entry_semantic('entry_long', current_price, trigger_long, exit_long, stop_distance, lot_size)
            self.long_entry_order = self.buy(exectype=bt.Order.Stop, price=trigger_long, size=lot_size)
            self.long_entry_order.addinfo(kind='entry_long', exit_price=exit_long)
        if current_price - trigger_short >= self.p.min_stop_distance:
            stop_distance = exit_short - trigger_short
            lot_size = self.calculate_lot_size(stop_distance, trigger_short)
            self._log_entry_semantic('entry_short', current_price, trigger_short, exit_short, stop_distance, lot_size)
            self.short_entry_order = self.sell(exectype=bt.Order.Stop, price=trigger_short, size=lot_size)
            self.short_entry_order.addinfo(kind='entry_short', exit_price=exit_short)

    def _log_entry_semantic(self, kind, current_price, trigger, exit_price, stop_distance, lot_size):
        if self._semantic_log is None:
            return
        payload = {
            'kind': kind,
            'base_dt': bt.num2date(self.base_data.datetime[0]).isoformat(),
            'trading_dt': bt.num2date(self.trading_data.datetime[0]).isoformat(),
            'current_price': current_price,
            'trigger': trigger,
            'exit_price': exit_price,
            'stop_distance': stop_distance,
            'lot_size': lot_size,
        }
        self._semantic_log.write(json.dumps(payload, sort_keys=True) + '\n')
        self._semantic_log.flush()

    def next(self):
        self.bar_num += 1
        required = max(self.p.entry_period + self.p.entry_shift, self.p.exit_period + self.p.exit_shift, self.p.atr_period + 1)
        if len(self.trading_data) <= required:
            return
        if not self._new_trading_bar():
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
        self._position_was_open = False
        self.current_exit_price = None
        self.exit_order = None
        self.close_order = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
