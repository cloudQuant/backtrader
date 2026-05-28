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


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class CandelsHighOpenStrategy(bt.Strategy):
    params = dict(
        threshold_open=10,
        threshold_close=10,
        price_level=0.0,
        stop_level=50.0,
        take_level=50.0,
        expiration=4,
        reverse_signals=False,
        weight=1.0,
        trailing_step=0.02,
        trailing_maximum=0.2,
        risk_percent=10.0,
        size=0.1,
        point=0.01,
        digits_adjust=1,
        price_digits=2,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.psar = bt.indicators.ParabolicSAR(self.data0, af=self.p.trailing_step, afmax=self.p.trailing_maximum)

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
        dt = bt.num2date(self.data0.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _signal_value(self):
        highs = [float(self.data0.high[-i]) for i in [1, 2, 3, 4]]
        opens = [float(self.data0.open[-i]) for i in [1, 2, 3, 4]]
        up = highs[0] > highs[1] > highs[2] > highs[3] and opens[0] > opens[1] > opens[2] > opens[3]
        down = highs[0] < highs[1] < highs[2] < highs[3] and opens[0] < opens[1] < opens[2] < opens[3]
        signal = 1 if up else -1 if down else 0
        if self.p.reverse_signals:
            signal *= -1
        return signal

    def _enough_history(self):
        return len(self.data0) >= 6

    def _manage_risk(self):
        if not self.position:
            return False
        high = float(self.data0.high[0])
        low = float(self.data0.low[0])
        psar = float(self.psar[0])

        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.entry_order = self.close()
                return True
            if psar > (self.stop_price if self.stop_price is not None else float('-inf')) and psar < float(self.data0.close[0]):
                self.stop_price = round(psar, self.p.price_digits)
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.entry_order = self.close()
                return True
            if psar < (self.stop_price if self.stop_price is not None else float('inf')) and psar > float(self.data0.close[0]):
                self.stop_price = round(psar, self.p.price_digits)
        return False

    def _set_risk_prices(self, side):
        price = float(self.data0.close[0])
        unit = self._trade_unit()
        if side == 'buy':
            self.stop_price = round(price - self.p.stop_level * unit, self.p.price_digits) if self.p.stop_level > 0 else None
            self.take_profit_price = round(price + self.p.take_level * unit, self.p.price_digits) if self.p.take_level > 0 else None
        else:
            self.stop_price = round(price + self.p.stop_level * unit, self.p.price_digits) if self.p.stop_level > 0 else None
            self.take_profit_price = round(price - self.p.take_level * unit, self.p.price_digits) if self.p.take_level > 0 else None
        self.current_side = side

    def next(self):
        self.bar_num += 1
        if not self._enough_history():
            return
        if self.entry_order is not None:
            return
        if self._manage_risk():
            return

        signal_dt = bt.num2date(self.data0.datetime[-1])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        signal = self._signal_value()
        self.log(f'cho signal={signal}')

        if signal > 0:
            if self.position and self.position.size < 0:
                self.entry_order = self.close()
                return
            if not self.position:
                self._set_risk_prices('buy')
                self.entry_order = self.buy(size=self.p.size)
                return

        if signal < 0:
            if self.position and self.position.size > 0:
                self.entry_order = self.close()
                return
            if not self.position:
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
