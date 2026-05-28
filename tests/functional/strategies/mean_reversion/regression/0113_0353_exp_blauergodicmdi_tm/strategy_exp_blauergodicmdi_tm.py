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


class BlauErgodicMDI(bt.Indicator):
    lines = ('up', 'dn', 'hist', 'color_idx')
    params = dict(xlength=20, xlength1=5, xlength2=5, xlength3=5)

    def __init__(self):
        price = bt.indicators.ExponentialMovingAverage(self.data.close, period=max(2, self.p.xlength))
        xprice = bt.indicators.ExponentialMovingAverage(price, period=max(2, self.p.xlength1))
        dif = price - xprice
        xdif = bt.indicators.ExponentialMovingAverage(dif, period=max(2, self.p.xlength1))
        xxdif = bt.indicators.ExponentialMovingAverage(xdif, period=max(2, self.p.xlength2))
        xxxdif = bt.indicators.ExponentialMovingAverage(xxdif, period=max(2, self.p.xlength3))
        self.lines.hist = xxdif
        self.lines.up = xxdif
        self.lines.dn = xxxdif
        self.addminperiod(self.p.xlength + self.p.xlength1 + self.p.xlength2 + self.p.xlength3 + 2)


class ExpBlauErgodicMDITmStrategy(bt.Strategy):
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
        mode='twist',
        time_trade=True,
        start_hour=0,
        start_minute=0,
        end_hour=23,
        end_minute=59,
        xlength=20,
        xlength1=5,
        xlength2=5,
        xlength3=5,
        signal_bar=1,
        relaxed_entry=False,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.exec_feed = self.datas[0]
        self.signal_feed = self.datas[1]
        price = bt.indicators.ExponentialMovingAverage(self.signal_feed.close, period=max(2, self.p.xlength))
        xprice = bt.indicators.ExponentialMovingAverage(price, period=max(2, self.p.xlength1))
        dif = price - xprice
        xdif = bt.indicators.ExponentialMovingAverage(dif, period=max(2, self.p.xlength1))
        xxdif = bt.indicators.ExponentialMovingAverage(xdif, period=max(2, self.p.xlength2))
        xxxdif = bt.indicators.ExponentialMovingAverage(xxdif, period=max(2, self.p.xlength3))
        self.ind = type('BlauErgodicLines', (), {})()
        self.ind.hist = xxdif
        self.ind.up = xxdif
        self.ind.dn = xxxdif
        self.order = None
        self.entry_side = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None
        self.buy_count = 0
        self.sell_count = 0

    def log(self, text):
        dt = bt.num2date(self.exec_feed.datetime[0])
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

    def _line_value(self, line, signal_bar, shift_extra=0):
        shift = (int(signal_bar) - 1) + int(shift_extra)
        if len(self.signal_feed) <= shift:
            return None
        try:
            value = float(line[-shift] if shift else line[0])
        except (IndexError, ValueError):
            return None
        if not math.isfinite(value):
            return None
        return value

    def _within_trade_window(self, dt):
        if not self.p.time_trade:
            return True
        start = self.p.start_hour * 60 + self.p.start_minute
        end = self.p.end_hour * 60 + self.p.end_minute
        current = dt.hour * 60 + dt.minute
        if start <= end:
            return start <= current <= end
        return current >= start or current <= end

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
        low = float(self.exec_feed.low[0])
        high = float(self.exec_feed.high[0])
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

    def _signals_for_mode(self):
        mode = str(self.p.mode).lower()
        if mode == 'breakdown':
            hist_now = self._line_value(self.ind.hist, self.p.signal_bar, 0)
            hist_prev = self._line_value(self.ind.hist, self.p.signal_bar, 1)
            if None in (hist_now, hist_prev):
                return None
            buy_open = hist_prev > 0 and self.p.buy_pos_open and hist_now <= 0
            sell_close = hist_prev > 0 and self.p.sell_pos_close
            sell_open = hist_prev < 0 and self.p.sell_pos_open and hist_now >= 0
            buy_close = hist_prev < 0 and self.p.buy_pos_close
            return buy_open, sell_close, sell_open, buy_close, dict(hist_now=hist_now, hist_prev=hist_prev)
        if mode == 'cloudtwist':
            up_now = self._line_value(self.ind.up, self.p.signal_bar, 0)
            up_prev = self._line_value(self.ind.up, self.p.signal_bar, 1)
            dn_now = self._line_value(self.ind.dn, self.p.signal_bar, 0)
            dn_prev = self._line_value(self.ind.dn, self.p.signal_bar, 1)
            if None in (up_now, up_prev, dn_now, dn_prev):
                return None
            buy_open = up_prev > dn_prev and self.p.buy_pos_open and up_now <= dn_now
            sell_close = up_prev > dn_prev and self.p.sell_pos_close
            sell_open = up_prev < dn_prev and self.p.sell_pos_open and up_now >= dn_now
            buy_close = up_prev < dn_prev and self.p.buy_pos_close
            return buy_open, sell_close, sell_open, buy_close, dict(up_now=up_now, up_prev=up_prev, dn_now=dn_now, dn_prev=dn_prev)
        hist_now = self._line_value(self.ind.hist, self.p.signal_bar, 0)
        hist_prev = self._line_value(self.ind.hist, self.p.signal_bar, 1)
        hist_prev2 = self._line_value(self.ind.hist, self.p.signal_bar, 2)
        if None in (hist_now, hist_prev, hist_prev2):
            return None
        buy_open = hist_prev < hist_prev2 and self.p.buy_pos_open and hist_now > hist_prev
        sell_close = hist_prev < hist_prev2 and self.p.sell_pos_close
        sell_open = hist_prev > hist_prev2 and self.p.sell_pos_open and hist_now < hist_prev
        buy_close = hist_prev > hist_prev2 and self.p.buy_pos_close
        if self.p.relaxed_entry and not buy_open and not sell_open:
            buy_open = hist_now > hist_prev and self.p.buy_pos_open
            sell_open = hist_now < hist_prev and self.p.sell_pos_open
            sell_close = buy_open and self.p.sell_pos_close
            buy_close = sell_open and self.p.buy_pos_close
        return buy_open, sell_close, sell_open, buy_close, dict(hist_now=hist_now, hist_prev=hist_prev, hist_prev2=hist_prev2)

    def next(self):
        exec_dt = bt.num2date(self.exec_feed.datetime[0])
        if self.order is not None:
            return
        if self.position and self._check_exit_levels():
            return
        if self.p.time_trade and not self._within_trade_window(exec_dt):
            if self.position:
                self.order = self.close()
                self.log('CLOSE outside trading window')
            return
        signal_dt = bt.num2date(self.signal_feed.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        warmup = self.p.xlength + self.p.xlength1 + self.p.xlength2 + self.p.xlength3 + self.p.signal_bar + 3
        if len(self.signal_feed) < warmup:
            return
        signals = self._signals_for_mode()
        if signals is None:
            if not self.p.relaxed_entry or len(self.signal_feed) < 2:
                return
            close_delta = float(self.signal_feed.close[0]) - float(self.signal_feed.close[-1])
            details = dict(close_delta=close_delta)
            signals = (
                close_delta > 0 and self.p.buy_pos_open,
                close_delta > 0 and self.p.sell_pos_close,
                close_delta < 0 and self.p.sell_pos_open,
                close_delta < 0 and self.p.buy_pos_close,
                details,
            )
        self.last_signal_dt = signal_dt
        buy_open, sell_close, sell_open, buy_close, details = signals
        if self.position.size > 0 and buy_close:
            self.order = self.close()
            self.log(f'CLOSE long {details}')
            return
        if self.position.size < 0 and sell_close:
            self.order = self.close()
            self.log(f'CLOSE short {details}')
            return
        if self.position:
            return
        size = self._position_size()
        if buy_open:
            self.entry_side = 'long'
            self.order = self.buy(size=size)
            self.log(f'OPEN LONG size={size:.2f} mode={self.p.mode} details={details}')
        elif sell_open:
            self.entry_side = 'short'
            self.order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size:.2f} mode={self.p.mode} details={details}')

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
