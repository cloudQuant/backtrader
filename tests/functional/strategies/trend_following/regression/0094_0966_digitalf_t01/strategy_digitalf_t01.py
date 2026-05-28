from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import pandas as pd


DIGITAL_WEIGHTS = [
    0.24470985659780,
    0.23139774006970,
    0.20613796947320,
    0.17166230340640,
    0.13146907903600,
    0.08950387549560,
    0.04960091651250,
    0.01502270569607,
    -0.01188033734430,
    -0.02989873856137,
    -0.03898967104900,
    -0.04014113626390,
    -0.03511968085800,
    -0.02611613850342,
    -0.01539056955666,
    -0.00495353651394,
    0.00368588764825,
    0.00963614049782,
    0.01265138888314,
    0.01307496106868,
    0.01169702291063,
    0.00974841844086,
    0.00898900012545,
    -0.00649745721156,
]


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


class DigitalFT01Indicator(bt.Indicator):
    lines = ('digital', 'trigger')
    params = dict(halfchannel=25, applied_price_code=1, point=0.01, signal_period_minutes=180)

    def __init__(self):
        self.addminperiod(len(DIGITAL_WEIGHTS) + 10)

    def _price_value(self, shift):
        o = float(self.data.open[-shift] if shift else self.data.open[0])
        h = float(self.data.high[-shift] if shift else self.data.high[0])
        l = float(self.data.low[-shift] if shift else self.data.low[0])
        c = float(self.data.close[-shift] if shift else self.data.close[0])
        code = int(self.p.applied_price_code)
        if code == 1:
            return c
        if code == 2:
            return o
        if code == 3:
            return h
        if code == 4:
            return l
        if code == 5:
            return (h + l) / 2.0
        if code == 6:
            return (h + l + c) / 3.0
        if code == 7:
            return (h + l + c + c) / 4.0
        if code == 8:
            return (o + h + l + c) / 4.0
        if code == 12:
            base = h + l + c
            if c < o:
                return (base + l) / 4.0
            if c > o:
                return (base + h) / 4.0
            return (base + c) / 4.0
        return c

    def next(self):
        if len(self.data) < len(DIGITAL_WEIGHTS):
            return
        digital = 0.0
        for shift, weight in enumerate(DIGITAL_WEIGHTS):
            digital += weight * self._price_value(shift)
        dt = bt.num2date(self.data.datetime[0])
        period_minutes = max(int(self.p.signal_period_minutes), 1)
        bars_from_day_start = int(round((dt.hour * 60 + dt.minute) / float(period_minutes)) + 1)
        if len(self.data) <= bars_from_day_start:
            return
        ref_close = float(self.data.close[-bars_from_day_start])
        halfchannel = float(self.p.halfchannel) * float(self.p.point)
        trigger = ref_close + halfchannel if digital >= ref_close else ref_close - halfchannel
        self.lines.digital[0] = digital
        self.lines.trigger[0] = trigger


class DigitalFT01Strategy(bt.Strategy):
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
        signal_bar=1,
        halfchannel=25,
        applied_price_code=1,
        signal_period_minutes=180,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[-1]
        self.indicator = DigitalFT01Indicator(
            self.signal_feed,
            halfchannel=self.p.halfchannel,
            applied_price_code=self.p.applied_price_code,
            point=self.p.point,
            signal_period_minutes=self.p.signal_period_minutes,
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
        self.warmup = len(DIGITAL_WEIGHTS) + 12

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

    def _buffer_value(self, line, signal_bar, previous=False):
        shift = (int(signal_bar) - 1) + (1 if previous else 0)
        if len(line.array) <= shift:
            return None
        value = float(line[-shift] if shift else line[0])
        if not math.isfinite(value):
            return None
        return value

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
        osc_now = self._buffer_value(self.indicator.digital, self.p.signal_bar)
        osc_prev = self._buffer_value(self.indicator.digital, self.p.signal_bar, previous=True)
        trg_now = self._buffer_value(self.indicator.trigger, self.p.signal_bar)
        trg_prev = self._buffer_value(self.indicator.trigger, self.p.signal_bar, previous=True)
        if None in (osc_now, osc_prev, trg_now, trg_prev):
            return
        buy_open = osc_prev > trg_prev and self.p.buy_pos_open and osc_now < trg_now
        sell_close = osc_prev > trg_prev and self.p.sell_pos_close
        sell_open = osc_prev < trg_prev and self.p.sell_pos_open and osc_now > trg_now
        buy_close = osc_prev < trg_prev and self.p.buy_pos_close
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        if self.position.size > 0:
            if buy_close:
                self.pending_reverse_direction = -1 if sell_open else 0
                self.order = self.close()
                self.log(f'CLOSE long osc_prev={osc_prev:.5f} trg_prev={trg_prev:.5f} osc_now={osc_now:.5f} trg_now={trg_now:.5f}')
            return
        if self.position.size < 0:
            if sell_close:
                self.pending_reverse_direction = 1 if buy_open else 0
                self.order = self.close()
                self.log(f'CLOSE short osc_prev={osc_prev:.5f} trg_prev={trg_prev:.5f} osc_now={osc_now:.5f} trg_now={trg_now:.5f}')
            return
        if buy_open:
            self._submit_entry(1, f'osc_prev={osc_prev:.5f} trg_prev={trg_prev:.5f} osc_now={osc_now:.5f} trg_now={trg_now:.5f}')
            return
        if sell_open:
            self._submit_entry(-1, f'osc_prev={osc_prev:.5f} trg_prev={trg_prev:.5f} osc_now={osc_now:.5f} trg_now={trg_now:.5f}')
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
                self._submit_entry(reverse_direction, 'reverse after DigitalF-T01 crossover')
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
