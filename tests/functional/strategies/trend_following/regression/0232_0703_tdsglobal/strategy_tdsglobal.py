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


def resample_daily(df):
    out = df.resample('1D', label='right', closed='right').agg({
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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class TDSGlobalStrategy(bt.Strategy):
    params = dict(
        lots=1,
        take_profit=999,
        stoploss=0,
        trailing_stop=10,
        williams_l=-75,
        williams_h=-25,
        point=0.0001,
        digits_adjust=1,
        price_digits=5,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.daily = self.datas[1]
        self.macd = bt.indicators.MACD(self.daily.close, period_me1=12, period_me2=23, period_signal=9)
        self.osma = self.macd.macd - self.macd.signal
        self.wpr = bt.indicators.WilliamsR(self.base, period=14)

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
        self.pending_side = None
        self.pending_price = None

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _prepare_direction(self):
        if len(self.daily) < 3:
            return 0, False, False
        macd_prev = float(self.macd.macd[-1])
        macd_prev2 = float(self.macd.macd[-2])
        osma_prev = float(self.osma[-1])
        osma_prev2 = float(self.osma[-2])
        direction = 0
        if macd_prev > macd_prev2 and osma_prev > osma_prev2:
            direction = 1
        elif macd_prev < macd_prev2 and osma_prev < osma_prev2:
            direction = -1
        williams_buy = float(self.wpr[0]) < float(self.p.williams_l)
        williams_sell = float(self.wpr[0]) > float(self.p.williams_h)
        return direction, williams_buy, williams_sell

    def _set_pending(self, side):
        unit = self._unit()
        if side == 'buy':
            price_open = float(self.base.high[-1]) + 1 * unit
            trigger = max(price_open, float(self.base.close[0]) + 16 * unit)
            self.pending_side = 'buy'
            self.pending_price = round(trigger, int(self.p.price_digits))
            self.stop_price = round(float(self.base.low[-1]) - 1 * unit, int(self.p.price_digits))
            self.take_profit_price = round(self.pending_price + float(self.p.take_profit) * unit, int(self.p.price_digits))
        else:
            price_open = float(self.base.low[-1]) - 1 * unit
            trigger = min(price_open, float(self.base.close[0]) - 16 * unit)
            self.pending_side = 'sell'
            self.pending_price = round(trigger, int(self.p.price_digits))
            self.stop_price = round(float(self.base.high[-1]) + 1 * unit, int(self.p.price_digits))
            self.take_profit_price = round(self.pending_price - float(self.p.take_profit) * unit, int(self.p.price_digits))

    def _clear_pending(self):
        self.pending_side = None
        self.pending_price = None

    def _manage_pending(self):
        if self.pending_side is None:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.pending_side == 'buy' and high >= float(self.pending_price):
            self.signal_count += 1
            self.order = self.buy(size=self.p.lots)
            self._clear_pending()
            return True
        if self.pending_side == 'sell' and low <= float(self.pending_price):
            self.signal_count += 1
            self.order = self.sell(size=self.p.lots)
            self._clear_pending()
            return True
        return False

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        close = float(self.base.close[0])
        unit = self._unit()
        if self.position.size > 0:
            if high >= float(self.take_profit_price) or (self.stop_price is not None and low <= float(self.stop_price)):
                self.order = self.close()
                return True
            if float(self.p.trailing_stop) > 0 and close - float(self.position.price) > float(self.p.trailing_stop) * unit:
                candidate = round(close - float(self.p.trailing_stop) * unit, int(self.p.price_digits))
                if self.stop_price is None or candidate > float(self.stop_price):
                    self.stop_price = candidate
        else:
            if low <= float(self.take_profit_price) or (self.stop_price is not None and high >= float(self.stop_price)):
                self.order = self.close()
                return True
            if float(self.p.trailing_stop) > 0 and float(self.position.price) - close > float(self.p.trailing_stop) * unit:
                candidate = round(close + float(self.p.trailing_stop) * unit, int(self.p.price_digits))
                if self.stop_price is None or candidate < float(self.stop_price):
                    self.stop_price = candidate
        return False

    def next(self):
        self.bar_num += 1
        if len(self.base) < 20 or len(self.daily) < 5:
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        if self._manage_pending():
            return
        if self.pending_side is not None:
            return
        direction, williams_buy, williams_sell = self._prepare_direction()
        if direction == 1 and williams_buy:
            self._set_pending('buy')
            return
        if direction == -1 and williams_sell:
            self._set_pending('sell')

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
