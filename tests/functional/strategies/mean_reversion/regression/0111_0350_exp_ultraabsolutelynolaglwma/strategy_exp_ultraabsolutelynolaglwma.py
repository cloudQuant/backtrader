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


class UltraAbsolutelyNoLagLwmaColor(bt.Indicator):
    lines = ('bulls', 'bears', 'color_idx')
    params = dict(flength=7, start_length=5, pstep=2, psteps_total=10, smooth_length=3, up_level=80.0, dn_level=20.0)

    def __init__(self):
        lookback = max(self.p.flength * 2, self.p.start_length + self.p.pstep * self.p.psteps_total, self.p.smooth_length + 2)
        self.range_high = bt.indicators.Highest(self.data.high, period=max(2, self.p.flength * 2))
        self.range_low = bt.indicators.Lowest(self.data.low, period=max(2, self.p.flength * 2))
        self.smooth_close = bt.indicators.WeightedMovingAverage(self.data.close, period=max(2, self.p.start_length + self.p.pstep))
        self.smooth_signal = bt.indicators.WeightedMovingAverage(self.smooth_close, period=max(2, self.p.smooth_length))
        self.addminperiod(lookback + 2)

    def next(self):
        high = float(self.range_high[0])
        low = float(self.range_low[0])
        spread = high - low
        if spread <= 0:
            bulls = 50.0
        else:
            bulls = (float(self.smooth_close[0]) - low) / spread * 100.0
        bulls = max(0.0, min(100.0, bulls))
        bears = 100.0 - bulls
        self.lines.bulls[0] = bulls
        self.lines.bears[0] = bears
        prev_bulls = float(self.lines.bulls[-1]) if len(self) > 1 and math.isfinite(float(self.lines.bulls[-1])) else bulls
        prev_bears = float(self.lines.bears[-1]) if len(self) > 1 and math.isfinite(float(self.lines.bears[-1])) else bears
        color = 0.0
        if bulls > bears:
            if bulls > self.p.up_level or bears < self.p.dn_level:
                color = 7.0 if prev_bulls <= bulls else 8.0
            else:
                color = 5.0 if prev_bulls <= bulls else 6.0
        elif bulls < bears:
            if bulls < self.p.dn_level or bears > self.p.up_level:
                color = 1.0 if prev_bears <= bears else 2.0
            else:
                color = 3.0 if prev_bears <= bears else 4.0
        self.lines.color_idx[0] = color


class ExpUltraAbsolutelyNoLagLwmaStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        risk_percent=0.0,
        point_size=0.01,
        stoploss_pips=1000,
        takeprofit_pips=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        flength=7,
        start_length=5,
        pstep=2,
        psteps_total=10,
        smooth_length=3,
        up_level=80.0,
        dn_level=20.0,
        signal_bar=1,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[1]
        self.ind = UltraAbsolutelyNoLagLwmaColor(
            self.signal_feed,
            flength=self.p.flength,
            start_length=self.p.start_length,
            pstep=self.p.pstep,
            psteps_total=self.p.psteps_total,
            smooth_length=self.p.smooth_length,
            up_level=self.p.up_level,
            dn_level=self.p.dn_level,
        )
        self.order = None
        self.entry_side = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None
        self.buy_count = 0
        self.sell_count = 0

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
        stop_distance = self.p.stoploss_pips * self.p.point_size
        if stop_distance <= 0 or self.p.risk_percent <= 0:
            return self._round_size(self.p.lot_min)
        risk_money = self.broker.getvalue() * (self.p.risk_percent / 100.0)
        raw_size = risk_money / (stop_distance * self.p.contract_multiplier)
        return self._round_size(raw_size)

    def _line_value(self, line, signal_bar, previous=False):
        shift = (int(signal_bar) - 1) + (1 if previous else 0)
        if len(line.array) <= shift:
            return None
        value = float(line[-shift] if shift else line[0])
        if not math.isfinite(value):
            return None
        return value

    def _set_entry_risk(self, price, direction):
        stop_distance = self.p.stoploss_pips * self.p.point_size
        take_distance = self.p.takeprofit_pips * self.p.point_size
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stoploss_pips > 0 else None
            self.take_profit_price = price + take_distance if self.p.takeprofit_pips > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stoploss_pips > 0 else None
            self.take_profit_price = price - take_distance if self.p.takeprofit_pips > 0 else None

    def _clear_risk(self):
        self.stop_price = None
        self.take_profit_price = None

    def _check_exit_levels(self):
        if not self.position:
            return False
        low = float(self.data0_feed.low[0])
        high = float(self.data0_feed.high[0])
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

    def next(self):
        signal_dt = bt.num2date(self.signal_feed.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        warmup = max(self.p.flength * 2, self.p.start_length + self.p.pstep * self.p.psteps_total, self.p.smooth_length + 2) + self.p.signal_bar + 1
        if len(self.signal_feed) < warmup:
            return
        if self.order is not None:
            return
        if self.position and self._check_exit_levels():
            return
        color_now = self._line_value(self.ind.color_idx, self.p.signal_bar)
        color_prev = self._line_value(self.ind.color_idx, self.p.signal_bar, previous=True)
        if None in (color_now, color_prev):
            return
        buy_open = color_prev > 4.0 and self.p.buy_pos_open and color_now < 5.0 and color_now != 0.0
        sell_close = color_prev > 4.0 and self.p.sell_pos_close
        sell_open = color_prev < 5.0 and color_prev != 0.0 and self.p.sell_pos_open and color_now > 4.0
        buy_close = color_prev < 5.0 and color_prev != 0.0 and self.p.buy_pos_close
        if self.position.size > 0 and buy_close:
            self.order = self.close()
            self.log(f'CLOSE long color_now={color_now} color_prev={color_prev}')
            return
        if self.position.size < 0 and sell_close:
            self.order = self.close()
            self.log(f'CLOSE short color_now={color_now} color_prev={color_prev}')
            return
        if self.position:
            return
        size = self._position_size()
        if buy_open:
            self.entry_side = 'long'
            self.order = self.buy(size=size)
            self.log(f'OPEN LONG size={size:.2f} color_now={color_now} color_prev={color_prev}')
        elif sell_open:
            self.entry_side = 'short'
            self.order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size:.2f} color_now={color_now} color_prev={color_prev}')

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if order == self.order and self.entry_side == 'long' and order.isbuy() and self.position.size > 0:
                self.buy_count += 1
                self._set_entry_risk(order.executed.price, 1)
                self.log(f'ENTRY FILLED LONG price={order.executed.price:.5f} size={order.executed.size:.2f}')
            elif order == self.order and self.entry_side == 'short' and order.issell() and self.position.size < 0:
                self.sell_count += 1
                self._set_entry_risk(order.executed.price, -1)
                self.log(f'ENTRY FILLED SHORT price={order.executed.price:.5f} size={order.executed.size:.2f}')
            elif not self.position:
                self._clear_risk()
                self.log(f'EXIT FILLED price={order.executed.price:.5f} size={order.executed.size:.2f}')
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            if order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
                self.log(f'ORDER FAILED status={order.getstatusname()}')
            self.order = None
            if not self.position:
                self.entry_side = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self._clear_risk()
            self.entry_side = None
