from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
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
    df = df.set_index('datetime').sort_index()
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


class CloudTrade2Strategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        stop_loss_pips=50.0,
        take_profit_pips=50.0,
        trailing_stop_pips=0.0,
        trailing_step_pips=5.0,
        min_profit_money=10.0,
        profit_points_pips=10.0,
        use_fractals=True,
        use_stochastic=True,
        one_day_one_deal=True,
        stochastic_k_period=5,
        stochastic_d_period=3,
        stochastic_slowing=3,
        stochastic_overbought=80.0,
        stochastic_oversold=20.0,
        pip_size=0.01,
        contract_multiplier=100.0,
        fractal_lookback=100,
    )

    def __init__(self):
        self.order = None
        self.entry_side = None
        self.last_entry_date = None
        self.stop_price = None
        self.take_profit_price = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        if self.p.use_stochastic:
            self.stochastic = bt.indicators.StochasticFull(
                self.data,
                period=self.p.stochastic_k_period,
                period_dfast=self.p.stochastic_d_period,
                period_dslow=self.p.stochastic_slowing,
                movav=bt.indicators.SimpleMovingAverage,
                safediv=True,
            )
            self.sto_main = self.stochastic.percK
            self.sto_signal = self.stochastic.percD
        else:
            self.stochastic = None
            self.sto_main = None
            self.sto_signal = None

    def prenext(self):
        self.next()

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _clear_risk(self):
        self.stop_price = None
        self.take_profit_price = None

    def _set_entry_risk(self, price, direction):
        stop_distance = self.p.stop_loss_pips * self.p.pip_size
        take_profit_distance = self.p.take_profit_pips * self.p.pip_size
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stop_loss_pips > 0 else None
            self.take_profit_price = price + take_profit_distance if self.p.take_profit_pips > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stop_loss_pips > 0 else None
            self.take_profit_price = price - take_profit_distance if self.p.take_profit_pips > 0 else None

    def _signal_ready(self):
        needed = max(self.p.stochastic_k_period + self.p.stochastic_d_period + self.p.stochastic_slowing, 8)
        return len(self.data) >= needed

    def _signal_stochastic(self):
        if not self.p.use_stochastic or not self._signal_ready():
            return 0
        values = [self.sto_main[0], self.sto_main[-1], self.sto_main[-2], self.sto_signal[0], self.sto_signal[-1], self.sto_signal[-2]]
        if not all(math.isfinite(v) for v in values):
            return 0
        if self.sto_signal[-1] >= self.p.stochastic_overbought:
            if self.sto_signal[-2] <= self.sto_main[-2] and self.sto_signal[-1] >= self.sto_main[-1]:
                return 2
        if self.sto_signal[-1] <= self.p.stochastic_oversold:
            if self.sto_signal[-2] >= self.sto_main[-2] and self.sto_signal[-1] <= self.sto_main[-1]:
                return 1
        return 0

    def _is_upper_fractal(self, shift):
        candidate = float(self.data.high[-shift])
        return (
            candidate > float(self.data.high[-shift - 1])
            and candidate > float(self.data.high[-shift - 2])
            and candidate >= float(self.data.high[-shift + 1])
            and candidate >= float(self.data.high[-shift + 2])
        )

    def _is_lower_fractal(self, shift):
        candidate = float(self.data.low[-shift])
        return (
            candidate < float(self.data.low[-shift - 1])
            and candidate < float(self.data.low[-shift - 2])
            and candidate <= float(self.data.low[-shift + 1])
            and candidate <= float(self.data.low[-shift + 2])
        )

    def _signal_fractals(self):
        if not self.p.use_fractals or len(self.data) < 8:
            return 0
        fu = 0
        fd = 0
        found = 0
        max_shift = min(self.p.fractal_lookback + 2, len(self.data) - 3)
        for shift in range(3, max_shift + 1):
            if self._is_upper_fractal(shift):
                fu += 1
                found += 1
            if self._is_lower_fractal(shift):
                fd += 1
                found += 1
            if found == 2:
                break
        if fu == 2:
            return 2
        if fd == 2:
            return 1
        return 0

    def _result_signal(self):
        signal_stochastic = self._signal_stochastic()
        signal_fractals = self._signal_fractals()
        if (signal_stochastic == 2 and self.p.use_stochastic) or (signal_fractals == 2 and self.p.use_fractals):
            return 2
        if (signal_stochastic == 1 and self.p.use_stochastic) or (signal_fractals == 1 and self.p.use_fractals):
            return 1
        return 0

    def _update_trailing_stop(self):
        if not self.position or self.p.trailing_stop_pips <= 0:
            return
        trailing_stop = self.p.trailing_stop_pips * self.p.pip_size
        trailing_step = self.p.trailing_step_pips * self.p.pip_size
        if self.position.size > 0:
            current_price = float(self.data.high[0])
            if current_price - self.position.price > trailing_stop + trailing_step:
                threshold = current_price - (trailing_stop + trailing_step)
                candidate = current_price - trailing_stop
                if self.stop_price is None or self.stop_price < threshold:
                    self.stop_price = candidate
        else:
            current_price = float(self.data.low[0])
            if self.position.price - current_price > trailing_stop + trailing_step:
                threshold = current_price + trailing_stop + trailing_step
                candidate = current_price + trailing_stop
                if self.stop_price is None or self.stop_price > threshold:
                    self.stop_price = candidate

    def _check_protective_exit(self):
        if not self.position:
            return False
        low = float(self.data.low[0])
        high = float(self.data.high[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                self.log(f'CLOSE long protective stop={self.stop_price:.5f}')
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                self.log(f'CLOSE long take_profit={self.take_profit_price:.5f}')
                return True
            return False
        if self.stop_price is not None and high >= self.stop_price:
            self.order = self.close()
            self.log(f'CLOSE short protective stop={self.stop_price:.5f}')
            return True
        if self.take_profit_price is not None and low <= self.take_profit_price:
            self.order = self.close()
            self.log(f'CLOSE short take_profit={self.take_profit_price:.5f}')
            return True
        return False

    def _max_profit_points(self):
        if not self.position:
            return 0.0
        if self.position.size > 0:
            return max(0.0, float(self.data.high[0]) - self.position.price)
        return max(0.0, self.position.price - float(self.data.low[0]))

    def _max_profit_money(self):
        return self._max_profit_points() * abs(self.position.size) * self.p.contract_multiplier

    def _check_profit_exit(self):
        if not self.position:
            return False
        if self.p.min_profit_money > 0 and self._max_profit_money() >= self.p.min_profit_money:
            self.order = self.close()
            self.log(f'CLOSE profit_money={self._max_profit_money():.2f}')
            return True
        target_points = self.p.profit_points_pips * self.p.pip_size
        if self.p.profit_points_pips > 0 and self._max_profit_points() >= target_points:
            self.order = self.close()
            self.log(f'CLOSE profit_points={self._max_profit_points():.5f}')
            return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) < 8:
            return
        if self.order is not None:
            return
        if self.position:
            self._update_trailing_stop()
            if self._check_protective_exit():
                return
            if self._check_profit_exit():
                return
        current_dt = self.data.datetime.datetime(0)
        if self.p.one_day_one_deal and self.last_entry_date == current_dt.date():
            return
        if self.position:
            return
        result_signal = self._result_signal()
        if result_signal == 1:
            self.entry_side = 'long'
            self.order = self.buy(size=self.p.fixed_lot)
            self.log(f'OPEN LONG size={self.p.fixed_lot}')
            return
        if result_signal == 2:
            self.entry_side = 'short'
            self.order = self.sell(size=self.p.fixed_lot)
            self.log(f'OPEN SHORT size={self.p.fixed_lot}')

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if order == self.order and self.entry_side == 'long' and order.isbuy() and self.position.size > 0:
                self.buy_count += 1
                self.last_entry_date = bt.num2date(order.executed.dt).date()
                self._set_entry_risk(order.executed.price, 1)
                self.log(f'ENTRY FILLED LONG price={order.executed.price:.5f} size={order.executed.size:.2f}')
            elif order == self.order and self.entry_side == 'short' and order.issell() and self.position.size < 0:
                self.sell_count += 1
                self.last_entry_date = bt.num2date(order.executed.dt).date()
                self._set_entry_risk(order.executed.price, -1)
                self.log(f'ENTRY FILLED SHORT price={order.executed.price:.5f} size={order.executed.size:.2f}')
            elif not self.position:
                self._clear_risk()
                self.log(f'EXIT FILLED price={order.executed.price:.5f} size={order.executed.size:.2f}')
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            if order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
                self.log(f'ORDER FAILED status={order.getstatusname()}')
            self.order = None
            if self.position:
                self.entry_side = None
            elif order.status != bt.Order.Completed:
                self.entry_side = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm > 0:
            self.win_count += 1
        elif trade.pnlcomm < 0:
            self.loss_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self._clear_risk()
            self.entry_side = None
