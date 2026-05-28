from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import backtrader.feeds as btfeeds
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


class Mt5PandasFeed(btfeeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6),
    )


class AccumulationDistributionLine(bt.Indicator):
    lines = ('adl',)

    def next(self):
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        close = float(self.data.close[0])
        volume = float(self.data.volume[0])
        if high == low:
            money_flow_multiplier = 0.0
        else:
            money_flow_multiplier = ((close - low) - (high - close)) / (high - low)
        previous = float(self.lines.adl[-1]) if len(self) > 1 else 0.0
        self.lines.adl[0] = previous + money_flow_multiplier * volume


class ChaikinOscillator(bt.Indicator):
    lines = ('cho',)
    params = dict(fast_period=3, slow_period=10)

    def __init__(self):
        self.adl = AccumulationDistributionLine(self.data)
        fast = bt.indicators.ExponentialMovingAverage(self.adl, period=self.p.fast_period)
        slow = bt.indicators.ExponentialMovingAverage(self.adl, period=self.p.slow_period)
        self.lines.cho = fast - slow


class LineCCI(bt.Indicator):
    lines = ('cci',)
    params = dict(period=14)

    def next(self):
        if len(self.data) < self.p.period:
            self.lines.cci[0] = 0.0
            return
        values = [float(self.data[-i]) for i in range(self.p.period)]
        mean_value = sum(values) / self.p.period
        mean_dev = sum(abs(v - mean_value) for v in values) / self.p.period
        if mean_dev == 0:
            self.lines.cci[0] = 0.0
            return
        self.lines.cci[0] = (float(self.data[0]) - mean_value) / (0.015 * mean_dev)


class CCIDualOnMA(bt.Indicator):
    lines = ('fast', 'slow')
    params = dict(ma_period=12, fast_period=14, slow_period=50)

    def __init__(self):
        self.ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.ma_period)
        self.lines.fast = LineCCI(self.ma, period=self.p.fast_period)
        self.lines.slow = LineCCI(self.ma, period=self.p.slow_period)


class ICHOTrendCCIDualOnMAFilterStrategy(bt.Strategy):
    params = dict(
        fixed_lot=3.0,
        stop_loss_points=150,
        take_profit_points=460,
        trailing_stop_points=250,
        trailing_step_points=50,
        cho_fast_period=3,
        cho_slow_period=10,
        cci_fast_period=14,
        cci_slow_period=50,
        ma_period=12,
        trade_mode='buy_sell',
        only_one_position=True,
        reverse=False,
        close_opposite=True,
        use_time_control=True,
        start_hour=10,
        start_minute=1,
        end_hour=15,
        end_minute=2,
        point_size=0.01,
        verbose=False,
    )

    def __init__(self):
        self.cho = ChaikinOscillator(self.data, fast_period=self.p.cho_fast_period, slow_period=self.p.cho_slow_period)
        self.cci_dual = CCIDualOnMA(self.data, ma_period=self.p.ma_period, fast_period=self.p.cci_fast_period, slow_period=self.p.cci_slow_period)
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.stop_price = None
        self.limit_price = None
        self.pending_entry_signal = None
        self.last_signal_bar = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        if not self.p.verbose:
            return
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _current_dt(self):
        return bt.num2date(self.data.datetime[0])

    def _bar_seconds(self, dt):
        return dt.hour * 3600 + dt.minute * 60

    def _time_allowed(self):
        if not self.p.use_time_control:
            return True
        dt = self._current_dt()
        current = self._bar_seconds(dt)
        start = self.p.start_hour * 3600 + self.p.start_minute * 60
        end = self.p.end_hour * 3600 + self.p.end_minute * 60
        if start < end:
            return start <= current < end
        if start > end:
            return current >= start or current < end
        return False

    def _buy_allowed(self):
        return self.p.trade_mode in ('buy', 'buy_sell')

    def _sell_allowed(self):
        return self.p.trade_mode in ('sell', 'buy_sell')

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None
        self.stop_price = None
        self.limit_price = None

    def _place_exit_orders(self):
        if not self.position:
            return
        self._cancel_exit_orders()
        stop_distance = float(self.p.stop_loss_points) * float(self.p.point_size)
        limit_distance = float(self.p.take_profit_points) * float(self.p.point_size)
        size = abs(self.position.size)
        if self.position.size > 0:
            if stop_distance > 0:
                self.stop_price = self.position.price - stop_distance
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.stop_price)
            if limit_distance > 0:
                self.limit_price = self.position.price + limit_distance
                self.limit_order = self.sell(size=size, exectype=bt.Order.Limit, price=self.limit_price, oco=self.stop_order)
        else:
            if stop_distance > 0:
                self.stop_price = self.position.price + stop_distance
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.stop_price)
            if limit_distance > 0:
                self.limit_price = self.position.price - limit_distance
                self.limit_order = self.buy(size=size, exectype=bt.Order.Limit, price=self.limit_price, oco=self.stop_order)

    def _update_trailing_stop(self):
        if not self.position or self.p.trailing_stop_points <= 0:
            return
        trailing_distance = float(self.p.trailing_stop_points) * float(self.p.point_size)
        trailing_step = float(self.p.trailing_step_points) * float(self.p.point_size)
        close_price = float(self.data.close[0])
        if self.position.size > 0:
            candidate = close_price - trailing_distance
            if self.stop_price is None:
                return
            if candidate > self.stop_price + trailing_step:
                self.stop_price = candidate
                size = abs(self.position.size)
                if self.stop_order is not None:
                    self.cancel(self.stop_order)
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.stop_price, oco=self.limit_order)
        else:
            candidate = close_price + trailing_distance
            if self.stop_price is None:
                return
            if candidate < self.stop_price - trailing_step:
                self.stop_price = candidate
                size = abs(self.position.size)
                if self.stop_order is not None:
                    self.cancel(self.stop_order)
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.stop_price, oco=self.limit_order)

    def _enqueue_signal(self, signal):
        if signal is None:
            return
        self.pending_entry_signal = signal

    def _open_signal(self, signal):
        size = max(0.01, float(self.p.fixed_lot))
        if signal == 'buy':
            self.entry_order = self.buy(size=size)
            self.buy_count += 1
            self.log('OPEN BUY')
        elif signal == 'sell':
            self.entry_order = self.sell(size=size)
            self.sell_count += 1
            self.log('OPEN SELL')

    def _signal(self):
        if len(self.data) < max(self.p.cho_slow_period, self.p.cci_slow_period, self.p.ma_period) + 5:
            return None
        cho_cur = float(self.cho[0])
        cho_prev = float(self.cho[-1])
        fast_cur = float(self.cci_dual.fast[0])
        fast_prev = float(self.cci_dual.fast[-1])
        slow_cur = float(self.cci_dual.slow[0])
        slow_prev = float(self.cci_dual.slow[-1])

        if cho_prev < 0.0 and cho_cur > 0.0:
            if not self.p.reverse:
                close_side = 'sell'
                open_side = 'buy' if self._buy_allowed() else None
            else:
                close_side = 'buy'
                open_side = 'sell' if self._sell_allowed() else None
            return dict(close_side=close_side, open_side=open_side)

        if cho_prev > 0.0 and cho_cur < 0.0:
            if not self.p.reverse:
                close_side = 'buy'
                open_side = 'sell' if self._sell_allowed() else None
            else:
                close_side = 'sell'
                open_side = 'buy' if self._buy_allowed() else None
            return dict(close_side=close_side, open_side=open_side)

        if cho_cur > 0.0 and fast_prev < 0.0 and fast_prev < slow_prev and fast_cur > slow_cur:
            if not self.p.reverse:
                if self._buy_allowed():
                    return dict(close_side=None, open_side='buy')
                return dict(close_side='sell', open_side=None)
            if self._sell_allowed():
                return dict(close_side=None, open_side='sell')
            return dict(close_side='buy', open_side=None)

        if cho_cur < 0.0 and fast_prev > 0.0 and fast_prev > slow_prev and fast_cur < slow_cur:
            if not self.p.reverse:
                if self._sell_allowed():
                    return dict(close_side=None, open_side='sell')
                return dict(close_side='buy', open_side=None)
            if self._buy_allowed():
                return dict(close_side=None, open_side='buy')
            return dict(close_side='sell', open_side=None)

        return None

    def next(self):
        self.bar_num += 1
        current_bar = self._current_dt()
        if self.position:
            self._update_trailing_stop()
        if self.entry_order is not None:
            return
        if self.last_signal_bar == current_bar:
            return

        if self.pending_entry_signal and not self.position and self._time_allowed():
            signal = self.pending_entry_signal
            self.pending_entry_signal = None
            self.last_signal_bar = current_bar
            self._open_signal(signal)
            return

        if not self._time_allowed():
            return

        signal = self._signal()
        if signal is None:
            return

        self.last_signal_bar = current_bar
        close_side = signal.get('close_side')
        open_side = signal.get('open_side')

        if close_side == 'buy' and self.position.size > 0:
            self._cancel_exit_orders()
            self.pending_entry_signal = open_side
            self.close()
            self.log('CLOSE BUY BY SIGNAL')
            return
        if close_side == 'sell' and self.position.size < 0:
            self._cancel_exit_orders()
            self.pending_entry_signal = open_side
            self.close()
            self.log('CLOSE SELL BY SIGNAL')
            return

        if open_side is None:
            return

        if self.position:
            if open_side == 'buy' and self.position.size < 0 and self.p.close_opposite:
                self._cancel_exit_orders()
                self.pending_entry_signal = 'buy'
                self.close()
                self.log('CLOSE SHORT THEN OPEN BUY')
                return
            if open_side == 'sell' and self.position.size > 0 and self.p.close_opposite:
                self._cancel_exit_orders()
                self.pending_entry_signal = 'sell'
                self.close()
                self.log('CLOSE LONG THEN OPEN SELL')
                return
            if self.p.only_one_position:
                return

        self._open_signal(open_side)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order == self.entry_order:
            if order.status == order.Completed:
                self.entry_order = None
                self._place_exit_orders()
                return
            if order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.entry_order = None
                return
        if order == self.stop_order:
            if order.status == order.Completed:
                self.stop_order = None
                self.limit_order = None
                self.stop_price = None
                self.limit_price = None
                self.pending_entry_signal = None
                return
            if order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.stop_order = None
                return
        if order == self.limit_order:
            if order.status == order.Completed:
                self.limit_order = None
                self.stop_order = None
                self.stop_price = None
                self.limit_price = None
                self.pending_entry_signal = None
                return
            if order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._cancel_exit_orders()
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
