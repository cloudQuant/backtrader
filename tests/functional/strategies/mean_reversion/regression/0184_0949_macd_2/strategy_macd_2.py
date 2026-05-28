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


class Macd2Indicator(bt.Indicator):
    lines = ('cloud_a', 'cloud_b', 'hist', 'color')
    params = dict(fast_macd=12, slow_macd=26, signal_macd=9)

    def __init__(self):
        self.macd = bt.indicators.MACD(self.data, period_me1=int(self.p.fast_macd), period_me2=int(self.p.slow_macd), period_signal=int(self.p.signal_macd))
        self.addminperiod(int(self.p.signal_macd) + max(int(self.p.fast_macd), int(self.p.slow_macd)) + 2)

    def next(self):
        main = float(self.macd.macd[0])
        signal = float(self.macd.signal[0])
        hist = 3.0 * (main - signal)
        self.lines.cloud_a[0] = main
        self.lines.cloud_b[0] = signal
        self.lines.hist[0] = hist
        color = 2
        if len(self) > 1:
            prev_hist = float(self.lines.hist[-1])
            if hist > 0:
                if hist > prev_hist:
                    color = 4
                elif hist < prev_hist:
                    color = 3
            elif hist < 0:
                if hist < prev_hist:
                    color = 0
                elif hist > prev_hist:
                    color = 1
        self.lines.color[0] = color


class Macd2Strategy(bt.Strategy):
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
        fast_macd=12,
        slow_macd=26,
        signal_macd=9,
        trend_mode='cloud',
        signal_bar=1,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[-1]
        self.indicator = Macd2Indicator(
            self.signal_feed,
            fast_macd=self.p.fast_macd,
            slow_macd=self.p.slow_macd,
            signal_macd=self.p.signal_macd,
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
        self.warmup = int(self.p.signal_macd) + max(int(self.p.fast_macd), int(self.p.slow_macd)) + int(self.p.signal_bar) + 8

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

    def _mode_signals(self):
        sb = int(self.p.signal_bar)
        if len(self.signal_feed) <= sb + 2:
            return False, False, False, False
        mode = str(self.p.trend_mode).lower()
        if mode == 'histogram':
            v0 = float(self.indicator.hist[-(sb - 1)] if sb > 1 else self.indicator.hist[0])
            v1 = float(self.indicator.hist[-sb])
            v2 = float(self.indicator.hist[-(sb + 1)])
            buy_open = self.p.buy_pos_open and v1 < v2 and v0 > v1
            sell_open = self.p.sell_pos_open and v1 > v2 and v0 < v1
            sell_close = self.p.sell_pos_close and v1 < v2
            buy_close = self.p.buy_pos_close and v1 > v2
            return buy_open, sell_open, buy_close, sell_close
        if mode == 'zero':
            v0 = float(self.indicator.hist[-(sb - 1)] if sb > 1 else self.indicator.hist[0])
            v1 = float(self.indicator.hist[-sb])
            buy_open = self.p.buy_pos_open and v1 > 0 and v0 <= 0
            sell_open = self.p.sell_pos_open and v1 < 0 and v0 >= 0
            sell_close = self.p.sell_pos_close and v1 > 0
            buy_close = self.p.buy_pos_close and v1 < 0
            return buy_open, sell_open, buy_close, sell_close
        up0 = float(self.indicator.cloud_a[-(sb - 1)] if sb > 1 else self.indicator.cloud_a[0])
        up1 = float(self.indicator.cloud_a[-sb])
        dn0 = float(self.indicator.cloud_b[-(sb - 1)] if sb > 1 else self.indicator.cloud_b[0])
        dn1 = float(self.indicator.cloud_b[-sb])
        buy_open = self.p.buy_pos_open and up1 > dn1 and up0 < dn0
        sell_open = self.p.sell_pos_open and up1 < dn1 and up0 > dn0
        sell_close = self.p.sell_pos_close and up1 > dn1
        buy_close = self.p.buy_pos_close and up1 < dn1
        return buy_open, sell_open, buy_close, sell_close

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
        buy_open, sell_open, buy_close, sell_close = self._mode_signals()
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        if self.position.size > 0:
            if buy_close:
                self.pending_reverse_direction = -1 if sell_open else 0
                self.order = self.close()
                self.log(f'CLOSE long MACD-2 mode={self.p.trend_mode}')
            return
        if self.position.size < 0:
            if sell_close:
                self.pending_reverse_direction = 1 if buy_open else 0
                self.order = self.close()
                self.log(f'CLOSE short MACD-2 mode={self.p.trend_mode}')
            return
        if buy_open:
            self._submit_entry(1, f'MACD-2 {self.p.trend_mode} bullish signal')
            return
        if sell_open:
            self._submit_entry(-1, f'MACD-2 {self.p.trend_mode} bearish signal')
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
                self._submit_entry(reverse_direction, f'reverse after MACD-2 {self.p.trend_mode} signal')
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
