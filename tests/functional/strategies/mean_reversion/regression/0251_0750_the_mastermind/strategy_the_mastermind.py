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
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
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


class TheMastermindStrategy(bt.Strategy):
    params = dict(
        lots=20.0,
        stop_loss=15,
        take_profit=45,
        trade_at_close_bar=False,
        trailing_stop=35,
        trailing_step=8,
        break_even=0,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        stoch_buy_level=3,
        stoch_sell_level=97,
        wpr_buy_level=-99.9,
        wpr_sell_level=-0.1,
    )

    def __init__(self):
        self.stoch = bt.indicators.Stochastic(self.data, period=5, period_dfast=3, period_dslow=3)
        self.wpr = bt.indicators.WilliamsR(self.data, period=5)

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
        self.last_trade_side = 0
        self.stop_price = None
        self.take_profit_price = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _buy_signal(self):
        sig_buy = float(self.stoch.percD[0])
        sig_high = float(self.wpr[-1]) if len(self) > 1 else float(self.wpr[0])
        return sig_buy < float(self.p.stoch_buy_level) and sig_high < float(self.p.wpr_buy_level)

    def _sell_signal(self):
        sig_sell = float(self.stoch.percD[0])
        sig_low = float(self.wpr[-1]) if len(self) > 1 else float(self.wpr[0])
        return sig_sell > float(self.p.stoch_sell_level) and sig_low > float(self.p.wpr_sell_level)

    def _set_risk(self, side):
        unit = self._unit()
        price = float(self.data.close[0])
        if side == 'buy':
            self.take_profit_price = None if self.p.take_profit == 0 else round(price + float(self.p.take_profit) * unit, int(self.p.price_digits))
            self.stop_price = None if self.p.stop_loss == 0 else round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits))
        else:
            self.take_profit_price = None if self.p.take_profit == 0 else round(price - float(self.p.take_profit) * unit, int(self.p.price_digits))
            self.stop_price = None if self.p.stop_loss == 0 else round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits))

    def _maybe_break_even(self):
        if not self.position or self.p.break_even <= 0 or self.stop_price is None:
            return
        unit = self._unit()
        price = float(self.data.close[0])
        if self.position.size > 0 and (price - self.position.price) > float(self.p.break_even) * unit and self.stop_price < self.position.price:
            self.stop_price = round(self.position.price, int(self.p.price_digits))
        if self.position.size < 0 and (self.position.price - price) > float(self.p.break_even) * unit and self.stop_price > self.position.price:
            self.stop_price = round(self.position.price, int(self.p.price_digits))

    def _maybe_trail(self):
        if not self.position or self.p.trailing_stop <= 0:
            return
        unit = self._unit()
        price = float(self.data.close[0])
        if self.position.size > 0 and (price - self.position.price) > float(self.p.trailing_stop) * unit:
            new_stop = round(price - float(self.p.trailing_stop) * unit, int(self.p.price_digits))
            threshold = round(price - (float(self.p.trailing_stop) + float(self.p.trailing_step) - 1.0) * unit, int(self.p.price_digits))
            if self.stop_price is None or self.stop_price < threshold:
                self.stop_price = new_stop
        if self.position.size < 0 and (self.position.price - price) > float(self.p.trailing_stop) * unit:
            new_stop = round(price + float(self.p.trailing_stop) * unit, int(self.p.price_digits))
            threshold = round(price + (float(self.p.trailing_stop) + float(self.p.trailing_step) - 1.0) * unit, int(self.p.price_digits))
            if self.stop_price is None or self.stop_price > threshold:
                self.stop_price = new_stop

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        buy_close = self._sell_signal()
        sell_close = self._buy_signal()
        if self.position.size > 0 and buy_close:
            self.order = self.close()
            return True
        if self.position.size < 0 and sell_close:
            self.order = self.close()
            return True
        self._maybe_break_even()
        self._maybe_trail()
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < 6:
            return
        if self.order is not None:
            return
        if self.position:
            if self._manage_position():
                return
            return
        buy_signal = self._buy_signal()
        sell_signal = self._sell_signal()
        if sell_signal and self.last_trade_side != -1:
            self.signal_count += 1
            self._set_risk('sell')
            self.order = self.sell(size=self.p.lots)
            self.last_trade_side = -1
            return
        if buy_signal and self.last_trade_side != 1:
            self.signal_count += 1
            self._set_risk('buy')
            self.order = self.buy(size=self.p.lots)
            self.last_trade_side = 1

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
