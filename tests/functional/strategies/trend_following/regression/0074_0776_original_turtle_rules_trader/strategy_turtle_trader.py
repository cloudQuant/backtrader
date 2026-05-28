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


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class TurtleTraderStrategy(bt.Strategy):
    params = dict(
        n_exit=10,
        n_st=20,
        n_lt=55,
        atr_period=20,
        max_risk=0.01,
        volume_limit=4.0,
        volume_min=0.01,
        volume_step=0.01,
        adding_interval=1.0,
        stop_loss=1.0,
        take_profit=1.0,
        sar_flag=False,
        af_step=0.02,
        af_cap=0.2,
        multiplier=100.0,
        price_digits=2,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.atr = bt.indicators.AverageTrueRange(self.data0, period=self.p.atr_period)
        self.psar = bt.indicators.ParabolicSAR(self.data0, af=self.p.af_step, afmax=self.p.af_cap)

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.entry_order = None
        self.direction = 0
        self.prev_breakout = False
        self.stop_price = None
        self.take_profit_price = None
        self.entry_count = 0
        self.last_entry_price = None
        self.last_exit_direction = 0
        self.last_trade_was_profit = False
        self.last_signal_bar = None

    def log(self, text):
        dt = bt.num2date(self.data0.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _enough_history(self):
        need = max(self.p.n_exit, self.p.n_st, self.p.n_lt) + 2
        return len(self.data0) >= need

    def _round_volume(self, value):
        if value <= self.p.volume_min:
            return self.p.volume_min
        step = self.p.volume_step
        digits = max(0, int(round(-math.log10(step)))) if step < 1 else 0
        rounded = math.floor(value / step) * step
        return round(max(self.p.volume_min, min(self.p.volume_limit, rounded)), digits)

    def _unit_size(self):
        atr = float(self.atr[-1]) if len(self) > 1 else float(self.atr[0])
        if atr <= 0:
            return self.p.volume_min
        equity = self.broker.getvalue()
        risk_budget = equity * self.p.max_risk
        unit = risk_budget / max(atr * self.p.stop_loss * self.p.multiplier, 1e-9)
        return self._round_volume(unit)

    def _channel_max(self, period):
        return max(float(self.data0.high[-i]) for i in range(1, period + 1))

    def _channel_min(self, period):
        return min(float(self.data0.low[-i]) for i in range(1, period + 1))

    def _breakout(self, price, upper, lower):
        if price > upper:
            return 1
        if price < lower:
            return -1
        return 0

    def _set_risk_prices(self, direction, base_price):
        atr = float(self.atr[0])
        if direction > 0:
            self.stop_price = round(base_price - self.p.stop_loss * atr, self.p.price_digits)
            self.take_profit_price = round(base_price + self.p.take_profit * atr, self.p.price_digits) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(base_price + self.p.stop_loss * atr, self.p.price_digits)
            self.take_profit_price = round(base_price - self.p.take_profit * atr, self.p.price_digits) if self.p.take_profit > 0 else None

    def _reset_position_state(self):
        self.stop_price = None
        self.take_profit_price = None
        self.entry_count = 0
        self.last_entry_price = None
        self.direction = 0

    def _manage_open_position(self):
        if not self.position:
            return False
        high = float(self.data0.high[0])
        low = float(self.data0.low[0])
        close = float(self.data0.close[0])

        if self.p.sar_flag:
            psar = float(self.psar[0])
            if self.position.size > 0 and psar < close:
                if self.stop_price is None or psar > self.stop_price:
                    self.stop_price = round(psar, self.p.price_digits)
            elif self.position.size < 0 and psar > close:
                if self.stop_price is None or psar < self.stop_price:
                    self.stop_price = round(psar, self.p.price_digits)

        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.last_exit_direction = 1
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.last_exit_direction = 1
                self.entry_order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.last_exit_direction = -1
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.last_exit_direction = -1
                self.entry_order = self.close()
                return True

        exit_upper = self._channel_max(self.p.n_exit)
        exit_lower = self._channel_min(self.p.n_exit)
        backward = self._breakout(close, exit_upper, exit_lower)
        current_direction = 1 if self.position.size > 0 else -1
        if backward == -current_direction:
            self.last_exit_direction = current_direction
            self.entry_order = self.close()
            return True

        unit = self._unit_size()
        current_volume = abs(float(self.position.size))
        atr = float(self.atr[0])
        if self.last_entry_price is not None and current_volume + unit <= self.p.volume_limit + 1e-9:
            if (close - self.last_entry_price) * current_direction > self.p.adding_interval * atr:
                self._set_risk_prices(current_direction, close)
                self.last_entry_price = close
                self.entry_count += 1
                self.entry_order = self.buy(size=unit) if current_direction > 0 else self.sell(size=unit)
                return True
        return False

    def next(self):
        self.bar_num += 1
        if not self._enough_history():
            return
        if self.entry_order is not None:
            return

        current_bar = bt.num2date(self.data0.datetime[0])
        if self.last_signal_bar == current_bar:
            return
        self.last_signal_bar = current_bar

        if self._manage_open_position():
            return
        if self.position:
            return

        close = float(self.data0.close[0])
        exit_upper = self._channel_max(self.p.n_exit)
        exit_lower = self._channel_min(self.p.n_exit)
        st_upper = self._channel_max(self.p.n_st)
        st_lower = self._channel_min(self.p.n_st)
        lt_upper = self._channel_max(self.p.n_lt)
        lt_lower = self._channel_min(self.p.n_lt)

        if self.prev_breakout and self.last_exit_direction != 0:
            backward = self._breakout(close, exit_upper, exit_lower)
            if backward == -self.last_exit_direction:
                self.prev_breakout = False
                self.last_exit_direction = 0
                return
            lt_breakout = self._breakout(close, lt_upper, lt_lower)
            if lt_breakout == self.last_exit_direction:
                unit = self._unit_size()
                self.direction = lt_breakout
                self._set_risk_prices(lt_breakout, close)
                self.last_entry_price = close
                self.entry_count = 1
                self.entry_order = self.buy(size=unit) if lt_breakout > 0 else self.sell(size=unit)
                self.log(f'lt breakout={lt_breakout} unit={unit:.2f}')
                return
            return

        st_breakout = self._breakout(close, st_upper, st_lower)
        if st_breakout == 0:
            return
        unit = self._unit_size()
        self.direction = st_breakout
        self.prev_breakout = True
        self.last_exit_direction = st_breakout
        self._set_risk_prices(st_breakout, close)
        self.last_entry_price = close
        self.entry_count = 1
        self.entry_order = self.buy(size=unit) if st_breakout > 0 else self.sell(size=unit)
        self.log(f'st breakout={st_breakout} unit={unit:.2f}')

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
                if self.last_entry_price is None:
                    self.last_entry_price = order.executed.price
                self.log(f'entry filled price={order.executed.price:.2f} size={order.executed.size:.2f}')
            else:
                self.log(f'position closed price={order.executed.price:.2f} size={order.executed.size:.2f}')
                self._reset_position_state()
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.log(f'order failed status={order.getstatusname()}')
        if self.entry_order is not None and order.ref == self.entry_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.last_trade_was_profit = trade.pnlcomm > 0
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        if trade.pnlcomm <= 0:
            self.prev_breakout = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
