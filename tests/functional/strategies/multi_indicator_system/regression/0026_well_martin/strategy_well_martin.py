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
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class WellMartinStrategy(bt.Strategy):
    params = dict(
        bb_period=84,
        bb_dev=1.8,
        adx_period=40,
        adx_level=45,
        take_profit=1200,
        stop_loss=1400,
        slip=50,
        stealth=0,
        klot=2.0,
        max_lot=5.0,
        lot=0.1,
        point=0.00001,
        price_digits=5,
    )

    def __init__(self):
        self.bb = bt.indicators.BollingerBands(self.data.close, period=self.p.bb_period, devfactor=self.p.bb_dev)
        self.adx = bt.indicators.ADX(self.data, period=self.p.adx_period)

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.pending_order = None
        self.stop_price = None
        self.take_profit_price = None
        self.current_side = None
        self.current_entry_size = self.p.lot
        self.next_lot = self.p.lot
        self.last_closed_position_side = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print('{0}, {1}'.format(dt.isoformat(), text))

    def _trade_unit(self):
        return self.p.point

    def _can_buy(self):
        return self.last_closed_position_side in (None, 'short')

    def _can_sell(self):
        return self.last_closed_position_side in (None, 'long')

    def _set_risk_prices(self, side):
        price = float(self.data.close[0])
        unit = self._trade_unit()
        if side == 'buy':
            self.stop_price = round(price - self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None

    def _manage_risk(self):
        if not self.position:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.pending_order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.pending_order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.pending_order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.pending_order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self.pending_order is not None:
            return
        if len(self.data) < max(self.p.bb_period, self.p.adx_period) + 5:
            return
        if self._manage_risk():
            return
        if self.position:
            return

        buy_signal = float(self.data.close[0]) < float(self.bb.bot[-1]) and float(self.adx[-1]) < self.p.adx_level and self._can_buy()
        sell_signal = float(self.data.close[0]) > float(self.bb.top[-1]) and float(self.adx[-1]) < self.p.adx_level and self._can_sell()

        if buy_signal:
            self.current_entry_size = self.next_lot
            self.current_side = 'buy'
            self._set_risk_prices('buy')
            self.log('buy size={0:.2f} close={1:.5f} bb_low_prev={2:.5f} adx_prev={3:.2f}'.format(self.current_entry_size, float(self.data.close[0]), float(self.bb.bot[-1]), float(self.adx[-1])))
            self.pending_order = self.buy(size=self.current_entry_size)
            return

        if sell_signal:
            self.current_entry_size = self.next_lot
            self.current_side = 'sell'
            self._set_risk_prices('sell')
            self.log('sell size={0:.2f} close={1:.5f} bb_up_prev={2:.5f} adx_prev={3:.2f}'.format(self.current_entry_size, float(self.data.close[0]), float(self.bb.top[-1]), float(self.adx[-1])))
            self.pending_order = self.sell(size=self.current_entry_size)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.pending_order is not None and order.ref == self.pending_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
            self.next_lot = self.p.lot
        else:
            self.loss_count += 1
            self.next_lot = self.current_entry_size * self.p.klot
            if self.next_lot > self.p.max_lot:
                self.next_lot = self.p.lot
        self.last_closed_position_side = 'long' if self.current_side == 'buy' else 'short'
        self.current_side = None
        self.log('trade closed pnl={0:.2f} next_lot={1:.2f}'.format(trade.pnlcomm, self.next_lot))
