from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class OpeningClosingOnTimeV2Strategy(bt.Strategy):
    params = dict(
        open_time='05:00',
        close_time='21:01',
        lots=1.0,
        stop_loss=30,
        take_profit=50,
        trade_mode='buy_and_sell',
        slow_ma_period=200,
        slow_ma_method='EMA',
        slow_ma_applied_price='median',
        fast_ma_period=50,
        fast_ma_method='EMA',
        fast_ma_applied_price='median',
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.order = None
        self.exit_reason = None
        self.stop_price = None
        self.take_profit_price = None
        self.position_cycle_active = False
        self.last_open_day = None
        self.last_close_day = None

        self.open_clock = self._parse_clock(self.p.open_time)
        self.close_clock = self._parse_clock(self.p.close_time)
        fast_price = self._price_line(self.p.fast_ma_applied_price)
        slow_price = self._price_line(self.p.slow_ma_applied_price)
        self.fast_ma = self._make_ma(fast_price, self.p.fast_ma_period, self.p.fast_ma_method)
        self.slow_ma = self._make_ma(slow_price, self.p.slow_ma_period, self.p.slow_ma_method)
        self.addminperiod(max(int(self.p.fast_ma_period), int(self.p.slow_ma_period)) + 2)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _parse_clock(self, text):
        hour, minute = [int(part) for part in text.strip().split(':')]
        return datetime.time(hour=hour, minute=minute)

    def _price_line(self, applied_price):
        name = str(applied_price).strip().lower()
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

    def _make_ma(self, price_line, period, method):
        method_name = str(method).strip().upper()
        if method_name == 'SMA':
            return bt.indicators.SimpleMovingAverage(price_line, period=int(period))
        if method_name == 'SMMA':
            return bt.indicators.SmoothedMovingAverage(price_line, period=int(period))
        if method_name in ('LWMA', 'WMA'):
            return bt.indicators.WeightedMovingAverage(price_line, period=int(period))
        return bt.indicators.ExponentialMovingAverage(price_line, period=int(period))

    def _is_first_bar_after(self, current_dt, target_clock, last_day):
        if current_dt.date() == last_day:
            return False
        current_clock = current_dt.time().replace(second=0, microsecond=0)
        if current_clock < target_clock:
            return False
        if len(self.data) < 2:
            return True
        previous_dt = bt.num2date(self.data.datetime[-1])
        previous_clock = previous_dt.time().replace(second=0, microsecond=0)
        if previous_dt.date() != current_dt.date():
            return True
        return previous_clock < target_clock <= current_clock

    def _distance(self, points):
        return float(points) * float(self.p.point)

    def _reset_risk(self):
        self.stop_price = None
        self.take_profit_price = None
        self.exit_reason = None

    def _set_risk(self, side, entry_price):
        stop_dist = self._distance(self.p.stop_loss)
        take_dist = self._distance(self.p.take_profit)
        self.stop_price = None if float(self.p.stop_loss) <= 0 else round(
            entry_price - stop_dist if side == 'buy' else entry_price + stop_dist,
            int(self.p.price_digits),
        )
        self.take_profit_price = None if float(self.p.take_profit) <= 0 else round(
            entry_price + take_dist if side == 'buy' else entry_price - take_dist,
            int(self.p.price_digits),
        )

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            stop_hit = self.stop_price is not None and low <= self.stop_price
            take_hit = self.take_profit_price is not None and high >= self.take_profit_price
        else:
            stop_hit = self.stop_price is not None and high >= self.stop_price
            take_hit = self.take_profit_price is not None and low <= self.take_profit_price
        if not stop_hit and not take_hit:
            return False
        self.exit_reason = 'take_profit' if take_hit and not stop_hit else 'stop_loss'
        self.log(f'close by {self.exit_reason}')
        self.order = self.close()
        return True

    def _trend_side(self):
        fast_prev = float(self.fast_ma[-1])
        slow_prev = float(self.slow_ma[-1])
        if fast_prev > slow_prev:
            return 'buy'
        if fast_prev < slow_prev:
            return 'sell'
        return None

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(int(self.p.fast_ma_period), int(self.p.slow_ma_period)) + 1:
            return
        if self.order is not None:
            return
        if self._check_exit_levels():
            return

        dt = bt.num2date(self.data.datetime[0])
        if self.position_cycle_active:
            should_close_cycle = self._is_first_bar_after(dt, self.close_clock, self.last_close_day)
            if should_close_cycle:
                self.last_close_day = dt.date()
                self.position_cycle_active = False
                if self.position:
                    self.exit_reason = 'scheduled_close'
                    self.log('close position by schedule')
                    self.order = self.close()
                else:
                    self.log('close cycle reached with no open position')
            return

        should_open_cycle = self._is_first_bar_after(dt, self.open_clock, self.last_open_day)
        if not should_open_cycle:
            return

        self.last_open_day = dt.date()
        self.position_cycle_active = True
        trend_side = self._trend_side()
        trade_mode = str(self.p.trade_mode).strip().lower()
        if trade_mode == 'buy':
            desired_side = 'buy' if trend_side == 'buy' else None
        elif trade_mode == 'sell':
            desired_side = 'sell' if trend_side == 'sell' else None
        else:
            desired_side = trend_side

        if desired_side is None:
            self.log('open cycle reached but MA condition did not allow a trade')
            return

        self.signal_count += 1
        size = float(self.p.lots)
        if desired_side == 'buy':
            self.log(f'open buy by schedule size={size:.2f}')
            self.order = self.buy(size=size)
        else:
            self.log(f'open sell by schedule size={size:.2f}')
            self.order = self.sell(size=size)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.position:
                side = 'buy' if self.position.size > 0 else 'sell'
                self._set_risk(side, float(order.executed.price))
                if side == 'buy':
                    self.buy_count += 1
                else:
                    self.sell_count += 1
                self.log(
                    f'{side} filled price={float(order.executed.price):.2f} size={abs(float(order.executed.size)):.2f} '
                    f'sl={self.stop_price} tp={self.take_profit_price}'
                )
            else:
                self.log(f'position closed price={float(order.executed.price):.2f} reason={self.exit_reason}')
                self._reset_risk()
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.log(f'order failed status={order.getstatusname()}')
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
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
