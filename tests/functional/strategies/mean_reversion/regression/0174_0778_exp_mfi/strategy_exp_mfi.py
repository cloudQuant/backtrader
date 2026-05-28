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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
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


def resample_frame(df, rule):
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class MoneyFlowIndex(bt.Indicator):
    lines = ('mfi',)
    params = (('period', 14),)

    def __init__(self):
        self.addminperiod(self.p.period + 1)

    def next(self):
        positive = 0.0
        negative = 0.0
        for i in range(0, self.p.period):
            tp_now = (float(self.data.high[-i]) + float(self.data.low[-i]) + float(self.data.close[-i])) / 3.0
            tp_prev = (float(self.data.high[-i - 1]) + float(self.data.low[-i - 1]) + float(self.data.close[-i - 1])) / 3.0
            money_flow = tp_now * float(self.data.volume[-i])
            if tp_now > tp_prev:
                positive += money_flow
            elif tp_now < tp_prev:
                negative += money_flow
        if negative == 0:
            self.lines.mfi[0] = 100.0
            return
        ratio = positive / negative
        self.lines.mfi[0] = 100.0 - (100.0 / (1.0 + ratio))


class ExpMfiStrategy(bt.Strategy):
    params = dict(
        mm=0.1,
        mm_mode='LOT',
        stop_loss=1000,
        take_profit=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        trend='DIRECT',
        mfi_period=14,
        high_level=60,
        low_level=40,
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h4 = self.datas[1]
        self.mfi = MoneyFlowIndex(self.h4, period=self.p.mfi_period)

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.entry_order = None
        self.stop_price = None
        self.take_profit_price = None
        self.current_side = None
        self.last_signal_dt = None

    def log(self, text):
        dt = bt.num2date(self.m15.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _enough_history(self):
        return len(self.h4) >= self.p.mfi_period + max(3, self.p.signal_bar + 2)

    def _close_long_signal(self, buy_close):
        return buy_close and self.position and self.position.size > 0

    def _close_short_signal(self, sell_close):
        return sell_close and self.position and self.position.size < 0

    def _evaluate_signals(self):
        idx = -self.p.signal_bar
        prev_idx = idx - 1
        mfi_now = float(self.mfi[idx])
        mfi_prev = float(self.mfi[prev_idx])

        buy_open = buy_close = sell_open = sell_close = False

        if self.p.trend == 'DIRECT':
            if mfi_prev > self.p.low_level and mfi_now <= self.p.low_level:
                if self.p.buy_pos_open:
                    buy_open = True
                if self.p.sell_pos_close:
                    sell_close = True
            if mfi_prev < self.p.high_level and mfi_now >= self.p.high_level:
                if self.p.sell_pos_open:
                    sell_open = True
                if self.p.buy_pos_close:
                    buy_close = True
        else:
            if mfi_prev > self.p.low_level and mfi_now <= self.p.low_level:
                if self.p.sell_pos_open:
                    sell_open = True
                if self.p.buy_pos_close:
                    buy_close = True
            if mfi_prev < self.p.high_level and mfi_now >= self.p.high_level:
                if self.p.buy_pos_open:
                    buy_open = True
                if self.p.sell_pos_close:
                    sell_close = True
        return buy_open, buy_close, sell_open, sell_close, mfi_now, mfi_prev

    def _manage_risk(self):
        if not self.position:
            return False
        high = float(self.m15.high[0])
        low = float(self.m15.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.entry_order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.entry_order = self.close()
                return True
        return False

    def _set_risk_prices(self, side):
        price = float(self.m15.close[0])
        unit = self._trade_unit()
        if side == 'buy':
            self.stop_price = round(price - self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None
        self.current_side = side

    def next(self):
        self.bar_num += 1
        if not self._enough_history():
            return
        if self.entry_order is not None:
            return
        if self._manage_risk():
            return

        signal_dt = bt.num2date(self.h4.datetime[-self.p.signal_bar])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        buy_open, buy_close, sell_open, sell_close, mfi_now, mfi_prev = self._evaluate_signals()
        self.log(f'mfi signal prev={mfi_prev:.2f} now={mfi_now:.2f} buy_open={buy_open} sell_open={sell_open}')

        if self._close_long_signal(buy_close):
            self.entry_order = self.close()
            return
        if self._close_short_signal(sell_close):
            self.entry_order = self.close()
            return

        if buy_open and (not self.position or self.position.size <= 0):
            if self.position and self.position.size < 0:
                self.entry_order = self.close()
                return
            self._set_risk_prices('buy')
            self.entry_order = self.buy(size=self.p.size)
            return
        if sell_open and (not self.position or self.position.size >= 0):
            if self.position and self.position.size > 0:
                self.entry_order = self.close()
                return
            self._set_risk_prices('sell')
            self.entry_order = self.sell(size=self.p.size)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
                self.log(f'entry filled price={order.executed.price:.2f} size={order.executed.size:.2f}')
            else:
                self.stop_price = None
                self.take_profit_price = None
                self.current_side = None
                self.log(f'position closed price={order.executed.price:.2f} size={order.executed.size:.2f}')
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.log(f'order failed status={order.getstatusname()}')
        if self.entry_order is not None and order.ref == self.entry_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
