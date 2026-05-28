from __future__ import absolute_import, division, print_function, unicode_literals

import io

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


class ColorMetroStochasticIndicator(bt.Indicator):
    lines = ('fast_line', 'slow_line', 'stochastic')
    params = dict(k_period=5, d_period=3, slowing=3, ma_method='simple', step_size_fast=5, step_size_slow=15)

    def __init__(self):
        self.stoch = bt.indicators.Stochastic(
            self.data,
            period=int(self.p.k_period),
            period_dfast=int(self.p.slowing),
            period_dslow=int(self.p.d_period),
            movav=bt.indicators.SimpleMovingAverage if str(self.p.ma_method).lower() == 'simple' else bt.indicators.ExponentialMovingAverage,
        )
        self.addminperiod(int(self.p.k_period) + int(self.p.d_period) + int(self.p.slowing) + 3)
        self._fmin1 = 999999.0
        self._fmax1 = -999999.0
        self._smin1 = 999999.0
        self._smax1 = -999999.0
        self._ftrend = 0
        self._strend = 0

    def next(self):
        stoch0 = float(self.stoch.percD[0])
        fmax0 = stoch0 + 2.0 * float(self.p.step_size_fast)
        fmin0 = stoch0 - 2.0 * float(self.p.step_size_fast)
        if stoch0 > self._fmax1:
            self._ftrend = 1
        if stoch0 < self._fmin1:
            self._ftrend = -1
        if self._ftrend > 0 and fmin0 < self._fmin1:
            fmin0 = self._fmin1
        if self._ftrend < 0 and fmax0 > self._fmax1:
            fmax0 = self._fmax1
        smax0 = stoch0 + 2.0 * float(self.p.step_size_slow)
        smin0 = stoch0 - 2.0 * float(self.p.step_size_slow)
        if stoch0 > self._smax1:
            self._strend = 1
        if stoch0 < self._smin1:
            self._strend = -1
        if self._strend > 0 and smin0 < self._smin1:
            smin0 = self._smin1
        if self._strend < 0 and smax0 > self._smax1:
            smax0 = self._smax1
        fast_line = fmin0 + float(self.p.step_size_fast) if self._ftrend > 0 else fmax0 - float(self.p.step_size_fast)
        slow_line = smin0 + float(self.p.step_size_slow) if self._strend > 0 else smax0 - float(self.p.step_size_slow)
        self.lines.fast_line[0] = fast_line
        self.lines.slow_line[0] = slow_line
        self.lines.stochastic[0] = stoch0
        self._fmin1 = fmin0
        self._fmax1 = fmax0
        self._smin1 = smin0
        self._smax1 = smax0


class ColorMetroStochasticStrategy(bt.Strategy):
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
        k_period=5,
        d_period=3,
        slowing=3,
        ma_method='simple',
        step_size_fast=5,
        step_size_slow=15,
        signal_bar=1,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[-1]
        self.indicator = ColorMetroStochasticIndicator(
            self.signal_feed,
            k_period=self.p.k_period,
            d_period=self.p.d_period,
            slowing=self.p.slowing,
            ma_method=self.p.ma_method,
            step_size_fast=self.p.step_size_fast,
            step_size_slow=self.p.step_size_slow,
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
        self.pending_entry_direction = 0
        self.pending_reverse_direction = 0
        self.entry_side = None
        self.last_signal_dt = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.warmup = int(self.p.k_period) + int(self.p.d_period) + int(self.p.slowing) + int(self.p.signal_bar) + 8

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

    def _line_at(self, line, shift):
        idx = max(int(shift) - 1, 0)
        if len(line.array) <= idx:
            return None
        return float(line[-idx] if idx else line[0])

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
        fast_now = self._line_at(self.indicator.fast_line, int(self.p.signal_bar))
        slow_now = self._line_at(self.indicator.slow_line, int(self.p.signal_bar))
        fast_prev = self._line_at(self.indicator.fast_line, int(self.p.signal_bar) + 1)
        slow_prev = self._line_at(self.indicator.slow_line, int(self.p.signal_bar) + 1)
        if None in (fast_now, slow_now, fast_prev, slow_prev):
            return
        buy_open = self.p.buy_pos_open and fast_now > slow_now and fast_prev <= slow_prev
        sell_open = self.p.sell_pos_open and fast_now < slow_now and fast_prev >= slow_prev
        sell_close = self.p.sell_pos_close and fast_now > slow_now
        buy_close = self.p.buy_pos_close and fast_now < slow_now
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        if self.position.size > 0:
            if buy_close:
                self.pending_reverse_direction = -1 if sell_open else 0
                self.order = self.close()
                self.log('CLOSE long ColorMETRO_Stochastic signal')
            return
        if self.position.size < 0:
            if sell_close:
                self.pending_reverse_direction = 1 if buy_open else 0
                self.order = self.close()
                self.log('CLOSE short ColorMETRO_Stochastic signal')
            return
        if buy_open:
            self._submit_entry(1, 'ColorMETRO_Stochastic bullish cloud flip')
            return
        if sell_open:
            self._submit_entry(-1, 'ColorMETRO_Stochastic bearish cloud flip')
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
                self._submit_entry(reverse_direction, 'reverse after ColorMETRO_Stochastic signal')
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
