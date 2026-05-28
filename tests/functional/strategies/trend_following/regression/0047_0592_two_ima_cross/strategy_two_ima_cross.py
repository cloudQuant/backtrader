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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume']
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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class TwoIMACrossStrategy(bt.Strategy):
    params = dict(
        ma_period_first=5,
        ma_shift_first=3,
        ma_method_first='smma',
        ma_period_second=8,
        ma_shift_second=5,
        ma_method_second='smma',
        filter_ma=True,
        ma_period_third=13,
        ma_shift_third=8,
        ma_method_third='smma',
        lots=0.1,
        price_level=0,
        stop_loss=50,
        take_profit=50,
        trailing_stop=10,
        trailing_step=4,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ma_first = self._build_ma(self.data.close, self.p.ma_period_first, self.p.ma_method_first)
        self.ma_second = self._build_ma(self.data.close, self.p.ma_period_second, self.p.ma_method_second)
        self.ma_third = self._build_ma(self.data.close, self.p.ma_period_third, self.p.ma_method_third) if self.p.filter_ma else None

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.order = None
        self.pending_setup = None
        self.stop_price = None
        self.take_profit_price = None

    def _build_ma(self, data, period, method):
        method = str(method).lower()
        if method in ('sma', 'mode_sma'):
            return bt.indicators.SimpleMovingAverage(data, period=int(period))
        if method in ('ema', 'mode_ema'):
            return bt.indicators.ExponentialMovingAverage(data, period=int(period))
        if method in ('lwma', 'wma', 'mode_lwma'):
            return bt.indicators.WeightedMovingAverage(data, period=int(period))
        return bt.indicators.SmoothedMovingAverage(data, period=int(period))

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _val(self, line, shift, lookback=0):
        idx = int(shift) + int(lookback)
        return float(line[-idx])

    def _build_trade_setup(self, direction, base_price):
        level = abs(float(self.p.price_level)) * self._point()
        sl = float(self.p.stop_loss) * self._point()
        tp = float(self.p.take_profit) * self._point()

        if direction == 'buy':
            if float(self.p.price_level) == 0:
                entry = base_price
                stop_price = self._round(entry - sl) if sl > 0 else None
                take_profit_price = self._round(entry + tp) if tp > 0 else None
                order_type = 'market'
            elif float(self.p.price_level) < 0:
                entry = self._round(base_price + level)
                stop_price = self._round(entry - sl + level) if sl > 0 else None
                take_profit_price = self._round(entry + tp + level) if tp > 0 else None
                order_type = 'stop'
            else:
                entry = self._round(base_price - level)
                stop_price = self._round(entry - sl - level) if sl > 0 else None
                take_profit_price = self._round(entry + tp - level) if tp > 0 else None
                order_type = 'limit'
        else:
            if float(self.p.price_level) == 0:
                entry = base_price
                stop_price = self._round(entry + sl) if sl > 0 else None
                take_profit_price = self._round(entry - tp) if tp > 0 else None
                order_type = 'market'
            elif float(self.p.price_level) < 0:
                entry = self._round(base_price - level)
                stop_price = self._round(entry + sl - level) if sl > 0 else None
                take_profit_price = self._round(entry - tp - level) if tp > 0 else None
                order_type = 'stop'
            else:
                entry = self._round(base_price + level)
                stop_price = self._round(entry + sl + level) if sl > 0 else None
                take_profit_price = self._round(entry - tp + level) if tp > 0 else None
                order_type = 'limit'

        return {
            'direction': direction,
            'entry': self._round(entry),
            'stop_price': stop_price,
            'take_profit_price': take_profit_price,
            'order_type': order_type,
        }

    def _maybe_trigger_pending(self):
        if self.pending_setup is None or self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        setup = self.pending_setup
        entry = float(setup['entry'])
        triggered = False

        if setup['direction'] == 'buy':
            if setup['order_type'] == 'stop' and high >= entry:
                triggered = True
            elif setup['order_type'] == 'limit' and low <= entry:
                triggered = True
            if triggered:
                self.stop_price = setup['stop_price']
                self.take_profit_price = setup['take_profit_price']
                self.signal_count += 1
                self.order = self.buy(size=self.p.lots)
                self.pending_setup = None
        else:
            if setup['order_type'] == 'stop' and low <= entry:
                triggered = True
            elif setup['order_type'] == 'limit' and high >= entry:
                triggered = True
            if triggered:
                self.stop_price = setup['stop_price']
                self.take_profit_price = setup['take_profit_price']
                self.signal_count += 1
                self.order = self.sell(size=self.p.lots)
                self.pending_setup = None

    def _trailing(self):
        if not self.position or self.order is not None or float(self.p.trailing_stop) <= 0:
            return
        ts = float(self.p.trailing_stop) * self._point()
        step = float(self.p.trailing_step) * self._point()
        current = float(self.data.close[0])
        entry = float(self.position.price)
        if self.position.size > 0:
            if current - entry > ts + step:
                new_sl = self._round(current - ts)
                if self.stop_price is None or new_sl > float(self.stop_price) + step:
                    self.stop_price = new_sl
        else:
            if entry - current > ts + step:
                new_sl = self._round(current + ts)
                if self.stop_price is None or new_sl < float(self.stop_price) - step:
                    self.stop_price = new_sl

    def _check_exit(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return

    def next(self):
        self.bar_num += 1
        warmup = max(
            int(self.p.ma_period_first) + int(self.p.ma_shift_first),
            int(self.p.ma_period_second) + int(self.p.ma_shift_second),
            int(self.p.ma_period_third) + int(self.p.ma_shift_third) if self.p.filter_ma else 0,
        ) + 5
        if len(self) < warmup:
            return
        if self.order is not None:
            return

        self._maybe_trigger_pending()
        if self.order is not None:
            return

        if self.position:
            self._trailing()
            self._check_exit()
            return

        f0 = self._val(self.ma_first, self.p.ma_shift_first, 0)
        f1 = self._val(self.ma_first, self.p.ma_shift_first, 1)
        f2 = self._val(self.ma_first, self.p.ma_shift_first, 2)
        s0 = self._val(self.ma_second, self.p.ma_shift_second, 0)
        s1 = self._val(self.ma_second, self.p.ma_shift_second, 1)
        s2 = self._val(self.ma_second, self.p.ma_shift_second, 2)
        t0 = self._val(self.ma_third, self.p.ma_shift_third, 0) if self.p.filter_ma else None

        buy_signal = (f0 > s0 and f1 < s1) or (f0 > s0 and f2 < s2)
        sell_signal = (f0 < s0 and f1 > s1) or (f0 < s0 and f2 > s2)

        if self.p.filter_ma and t0 is not None:
            if buy_signal and t0 >= f0:
                buy_signal = False
            if sell_signal and t0 <= f0:
                sell_signal = False

        base_price = float(self.data.close[0])
        if buy_signal:
            setup = self._build_trade_setup('buy', base_price)
            if setup['order_type'] == 'market':
                self.stop_price = setup['stop_price']
                self.take_profit_price = setup['take_profit_price']
                self.signal_count += 1
                self.order = self.buy(size=self.p.lots)
            else:
                self.pending_setup = setup
            return

        if sell_signal:
            setup = self._build_trade_setup('sell', base_price)
            if setup['order_type'] == 'market':
                self.stop_price = setup['stop_price']
                self.take_profit_price = setup['take_profit_price']
                self.signal_count += 1
                self.order = self.sell(size=self.p.lots)
            else:
                self.pending_setup = setup

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
