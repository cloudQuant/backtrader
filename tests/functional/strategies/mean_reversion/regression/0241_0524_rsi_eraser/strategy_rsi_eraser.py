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


class RSIEraserStrategy(bt.Strategy):
    params = dict(
        ma_period=14,
        stop_loss=50,
        risk=5.0,
        point=0.01,
        price_digits=2,
        contract_multiplier=100.0,
        min_lot=0.01,
    )

    def __init__(self):
        self.h1 = self.datas[1]
        self.d1 = self.datas[2]
        self.rsi = bt.ind.RSI(self.h1.close, period=int(self.p.ma_period))
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
        self.stop_price = None
        self.take_profit_price = None
        self.last_buy_date = None
        self.last_sell_date = None
        self.pending_entry_direction = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _signal(self):
        if len(self.h1) < int(self.p.ma_period) + 2:
            return 0
        rsi = float(self.rsi[-1])
        if rsi > 50.0:
            return 1
        if rsi < 50.0:
            return -1
        return 0

    def _risk_size(self, entry, stop):
        risk_cash = float(self.broker.getcash()) * float(self.p.risk) / 100.0
        stop_distance = abs(float(entry) - float(stop))
        if stop_distance <= 0:
            return float(self.p.min_lot)
        size = risk_cash / max(stop_distance * float(self.p.contract_multiplier), 1e-9)
        size = max(float(self.p.min_lot), size)
        return round(size, 2)

    def _manage(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        stop_dist = float(self.p.stop_loss) * self._point()
        current = float(self.data.close[0])
        if self.position.size > 0:
            if current - float(self.position.price) > stop_dist and self.stop_price is not None and not self._compare(self.stop_price, self.position.price):
                self.stop_price = self._round(float(self.position.price))
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close(); return
        else:
            if float(self.position.price) - current > stop_dist and self.stop_price is not None and not self._compare(self.stop_price, self.position.price):
                self.stop_price = self._round(float(self.position.price))
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close(); return

    def _compare(self, value1, value2, eps=1e-7):
        return abs(float(value1) - float(value2)) <= eps

    def next(self):
        self.bar_num += 1
        if len(self) < 20 or len(self.h1) < int(self.p.ma_period) + 2 or len(self.d1) < 2 or self.order is not None:
            return
        if self.position:
            self._manage()
            return
        signal = self._signal()
        if signal == 0:
            return
        current_date = bt.num2date(self.data.datetime[0]).date()
        if signal == 1 and self.last_buy_date == current_date:
            return
        if signal == -1 and self.last_sell_date == current_date:
            return
        stop_dist = float(self.p.stop_loss) * self._point()
        if signal == 1:
            sl_low = float(self.d1.low[-1]) - 10.0 * self._point()
            price = float(self.data.close[0])
            sl = price - stop_dist if stop_dist > 0 else None
            if sl is None or sl_low < sl:
                return
            tp = price + 3.0 * stop_dist if stop_dist > 0 else None
            size = self._risk_size(price, sl)
            self.stop_price = self._round(sl)
            self.take_profit_price = self._round(tp) if tp is not None else None
            self.signal_count += 1
            self.pending_entry_direction = 'buy'
            self.order = self.buy(size=size)
        else:
            sl_high = float(self.d1.high[-1]) + 10.0 * self._point()
            price = float(self.data.close[0])
            sl = price + stop_dist if stop_dist > 0 else None
            if sl is None or sl_high > sl:
                return
            tp = price - 3.0 * stop_dist if stop_dist > 0 else None
            size = self._risk_size(price, sl)
            self.stop_price = self._round(sl)
            self.take_profit_price = self._round(tp) if tp is not None else None
            self.signal_count += 1
            self.pending_entry_direction = 'sell'
            self.order = self.sell(size=size)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            current_date = bt.num2date(self.data.datetime[0]).date()
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                    self.last_buy_date = current_date
                elif order.executed.size < 0:
                    self.sell_count += 1
                    self.last_sell_date = current_date
            else:
                self.stop_price = None
                self.take_profit_price = None
            self.pending_entry_direction = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
            self.pending_entry_direction = None
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
