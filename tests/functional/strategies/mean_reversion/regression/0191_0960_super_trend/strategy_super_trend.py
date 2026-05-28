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


def _get_updown_shift(timeframe_minutes):
    mapping = {
        1: 5,
        5: 10,
        15: 15,
        30: 20,
        60: 30,
        240: 50,
        480: 80,
        1440: 150,
        10080: 250,
        43200: 500,
    }
    return mapping.get(int(timeframe_minutes), 30)


class SuperTrendIndicator(bt.Indicator):
    lines = ('trend_up', 'trend_down', 'sign_up', 'sign_down', 'cci_value')
    params = dict(cci_period=14, level=0, point=0.01, timeframe_minutes=60)

    def __init__(self):
        self.addminperiod(int(self.p.cci_period) + 3)
        self.cci = bt.indicators.CCI(self.data, period=int(self.p.cci_period))
        self.updown_shift = _get_updown_shift(int(self.p.timeframe_minutes)) * float(self.p.point)

    def next(self):
        bar = len(self.data) - 1
        cci_now = float(self.cci[0]) + 70.0
        cci_prev = float(self.cci[-1]) + 70.0 if len(self.data) > 1 else cci_now
        prev_trend_up = float(self.lines.trend_up[-1]) if len(self.data) > 1 else 0.0
        prev_trend_down = float(self.lines.trend_down[-1]) if len(self.data) > 1 else 0.0
        trend_up = prev_trend_up
        trend_down = prev_trend_down
        sign_up = 0.0
        sign_down = 0.0
        if cci_now >= self.p.level and cci_prev < self.p.level:
            trend_up = prev_trend_down
        if cci_now <= self.p.level and cci_prev > self.p.level:
            trend_down = prev_trend_up
        if cci_now > self.p.level:
            trend_down = 0.0
            trend_up = float(self.data.low[0]) - self.updown_shift
            if len(self.data) > 1:
                if float(self.data.close[0]) < float(self.data.open[0]) and prev_trend_down != prev_trend_up:
                    trend_up = prev_trend_up
                if trend_up < prev_trend_up and prev_trend_down != prev_trend_up:
                    trend_up = prev_trend_up
                if float(self.data.high[0]) < float(self.data.high[-1]) and prev_trend_down != prev_trend_up:
                    trend_up = prev_trend_up
        if cci_now < self.p.level:
            trend_up = 0.0
            trend_down = float(self.data.high[0]) + self.updown_shift
            if len(self.data) > 1:
                if float(self.data.close[0]) > float(self.data.open[0]) and prev_trend_up != prev_trend_down:
                    trend_down = prev_trend_down
                if trend_down > prev_trend_down and prev_trend_down != prev_trend_up:
                    trend_down = prev_trend_down
                if float(self.data.low[0]) > float(self.data.low[-1]) and prev_trend_up != prev_trend_down:
                    trend_down = prev_trend_down
        if prev_trend_down != 0.0 and trend_up != 0.0:
            sign_up = prev_trend_down
        if prev_trend_up != 0.0 and trend_down != 0.0:
            sign_down = prev_trend_up
        self.lines.trend_up[0] = trend_up
        self.lines.trend_down[0] = trend_down
        self.lines.sign_up[0] = sign_up
        self.lines.sign_down[0] = sign_down
        self.lines.cci_value[0] = cci_now - 70.0


class SuperTrendStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        risk_percent=0.0,
        point=0.01,
        stop_loss_points=1000,
        take_profit_points=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        cci_period=14,
        level=0,
        signal_bar=1,
        timeframe_minutes=60,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[-1]
        self.indicator = SuperTrendIndicator(
            self.signal_feed,
            cci_period=self.p.cci_period,
            level=self.p.level,
            point=self.p.point,
            timeframe_minutes=self.p.timeframe_minutes,
        )
        self.bar_num = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.order = None
        self.entry_side = None
        self.pending_entry_direction = 0
        self.pending_reverse_direction = 0
        self.last_signal_dt = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.warmup = int(self.p.cci_period) + int(self.p.signal_bar) + 5

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _round_size(self, size):
        bounded = min(max(size, self.p.lot_min), self.p.lot_max)
        steps = round(bounded / self.p.lot_step)
        return min(max(steps * self.p.lot_step, self.p.lot_min), self.p.lot_max)

    def _position_size(self):
        if self.p.fixed_lot > 0:
            return self._round_size(self.p.fixed_lot)
        stop_distance = self.p.stop_loss_points * self.p.point
        if stop_distance <= 0 or self.p.risk_percent <= 0:
            return self._round_size(self.p.lot_min)
        risk_money = self.broker.getvalue() * (self.p.risk_percent / 100.0)
        raw_size = risk_money / (stop_distance * self.p.contract_multiplier)
        return self._round_size(raw_size)

    def _buffer_value(self, line, shift):
        idx = int(shift)
        if len(line.array) <= idx:
            return None
        value = float(line[-idx] if idx else line[0])
        if not math.isfinite(value):
            return None
        return value

    def _signal_present(self, line, shift):
        value = self._buffer_value(line, shift)
        return value is not None and value != 0.0

    def _find_future_signal(self, line):
        bars_available = len(self.signal_feed)
        for bar in range(int(self.p.signal_bar) + 1, bars_available):
            shift = bar - 1
            if len(line.array) <= shift:
                break
            value = float(line[-shift])
            if math.isfinite(value) and value != 0.0:
                return True
        return False

    def _set_entry_risk(self, price, direction):
        stop_distance = self.p.stop_loss_points * self.p.point
        take_distance = self.p.take_profit_points * self.p.point
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price + take_distance if self.p.take_profit_points > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price - take_distance if self.p.take_profit_points > 0 else None

    def _clear_risk(self):
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None

    def _submit_entry(self, direction, reason):
        size = self._position_size()
        if size <= 0:
            return False
        self.pending_entry_direction = direction
        if direction > 0:
            self.entry_side = 'long'
            self.order = self.buy(size=size)
            self.log(f'OPEN LONG size={size:.2f} reason={reason}')
        else:
            self.entry_side = 'short'
            self.order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size:.2f} reason={reason}')
        return True

    def _check_exit_levels(self):
        if not self.position:
            return False
        low = float(self.data0_feed.low[0])
        high = float(self.data0_feed.high[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.pending_reverse_direction = 0
                self.order = self.close()
                self.log(f'CLOSE long protective stop={self.stop_price:.5f}')
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.pending_reverse_direction = 0
                self.order = self.close()
                self.log(f'CLOSE long take_profit={self.take_profit_price:.5f}')
                return True
            return False
        if self.stop_price is not None and high >= self.stop_price:
            self.pending_reverse_direction = 0
            self.order = self.close()
            self.log(f'CLOSE short protective stop={self.stop_price:.5f}')
            return True
        if self.take_profit_price is not None and low <= self.take_profit_price:
            self.pending_reverse_direction = 0
            self.order = self.close()
            self.log(f'CLOSE short take_profit={self.take_profit_price:.5f}')
            return True
        return False

    def next(self):
        self.bar_num += 1
        signal_dt = bt.num2date(self.signal_feed.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        if len(self.signal_feed) < self.warmup:
            return
        if self.order is not None:
            return
        if self.position and self._check_exit_levels():
            return
        buy_open = self.p.buy_pos_open and self._signal_present(self.indicator.sign_up, int(self.p.signal_bar))
        sell_open = self.p.sell_pos_open and self._signal_present(self.indicator.sign_down, int(self.p.signal_bar))
        sell_close = self.p.sell_pos_close and self._find_future_signal(self.indicator.trend_up)
        buy_close = self.p.buy_pos_close and self._find_future_signal(self.indicator.trend_down)
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        if self.position.size > 0:
            if buy_close:
                self.pending_reverse_direction = -1 if sell_open else 0
                self.order = self.close()
                self.log('CLOSE long SuperTrend reverse/close signal')
            return
        if self.position.size < 0:
            if sell_close:
                self.pending_reverse_direction = 1 if buy_open else 0
                self.order = self.close()
                self.log('CLOSE short SuperTrend reverse/close signal')
            return
        if buy_open:
            self._submit_entry(1, 'SuperTrend buy signal')
            return
        if sell_open:
            self._submit_entry(-1, 'SuperTrend sell signal')
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.rejected_order_count += 1
            self.log(f'ORDER FAILED status={order.getstatusname()}')
            self.order = None
            self.pending_entry_direction = 0
            self.pending_reverse_direction = 0
            if not self.position:
                self.entry_side = None
            return
        if order.status != order.Completed:
            return
        self.completed_order_count += 1
        if self.pending_entry_direction == 1 and order.isbuy() and self.position.size > 0:
            self.buy_count += 1
            self.entry_price = order.executed.price
            self._set_entry_risk(self.entry_price, 1)
            self.pending_entry_direction = 0
            self.log(f'ENTRY FILLED LONG price={order.executed.price:.5f} size={order.executed.size:.2f}')
            self.order = None
            return
        if self.pending_entry_direction == -1 and order.issell() and self.position.size < 0:
            self.sell_count += 1
            self.entry_price = order.executed.price
            self._set_entry_risk(self.entry_price, -1)
            self.pending_entry_direction = 0
            self.log(f'ENTRY FILLED SHORT price={order.executed.price:.5f} size={order.executed.size:.2f}')
            self.order = None
            return
        if not self.position:
            self._clear_risk()
            self.log(f'EXIT FILLED price={order.executed.price:.5f} size={order.executed.size:.2f}')
            self.order = None
            self.entry_side = None
            reverse_direction = self.pending_reverse_direction
            self.pending_reverse_direction = 0
            if reverse_direction != 0:
                self._submit_entry(reverse_direction, 'reverse after SuperTrend signal')
            return
        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self._clear_risk()
            self.entry_side = None
