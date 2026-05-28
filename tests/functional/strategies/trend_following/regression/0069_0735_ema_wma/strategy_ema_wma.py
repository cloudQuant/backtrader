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


class EMAWMAStrategy(bt.Strategy):
    params = dict(
        period_ema=28,
        period_wma=8,
        stop_loss=50,
        take_profit=50,
        risk=10.0,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        min_lot=0.01,
        max_lot=100.0,
        lot_precision=2,
        margin_per_lot=250.0,
    )

    def __init__(self):
        self.ema = bt.indicators.ExponentialMovingAverage(self.data.open, period=self.p.period_ema)
        self.wma = bt.indicators.WeightedMovingAverage(self.data.open, period=self.p.period_wma)

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
        self.pending_side = None
        self.stop_price = None
        self.take_profit_price = None

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _calc_lot(self):
        free_margin = self.broker.getcash()
        margin_required = float(self.p.margin_per_lot)
        lot = free_margin * float(self.p.risk) / 100.0 / margin_required
        lot = max(float(self.p.min_lot), min(float(self.p.max_lot), lot))
        return round(lot, int(self.p.lot_precision))

    def _set_risk(self, side):
        unit = self._unit()
        price = float(self.data.close[0])
        if side == 'buy':
            self.stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits))
        else:
            self.stop_price = round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits))

    def _open_side(self, side):
        size = self._calc_lot()
        self._set_risk(side)
        self.pending_side = side
        if side == 'buy':
            self.order = self.buy(size=size)
        else:
            self.order = self.sell(size=size)

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if high >= self.take_profit_price or low <= self.stop_price:
                self.order = self.close()
                return True
        else:
            if low <= self.take_profit_price or high >= self.stop_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < max(self.p.period_ema, self.p.period_wma) + 2:
            return
        if self.order is not None:
            return
        buy_cross = float(self.ema[0]) < float(self.wma[0]) and float(self.ema[-1]) > float(self.wma[-1])
        sell_cross = float(self.ema[0]) > float(self.wma[0]) and float(self.ema[-1]) < float(self.wma[-1])
        if self.position:
            if buy_cross and self.position.size < 0:
                self.pending_side = 'buy'
                self._set_risk('buy')
                self.order = self.close()
                return
            if sell_cross and self.position.size > 0:
                self.pending_side = 'sell'
                self._set_risk('sell')
                self.order = self.close()
                return
            self._manage_position()
            return
        if buy_cross:
            self.signal_count += 1
            self._open_side('buy')
            return
        if sell_cross:
            self.signal_count += 1
            self._open_side('sell')

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
                if self.pending_side in ('buy', 'sell'):
                    side = self.pending_side
                    self.pending_side = None
                    self.stop_price = None
                    self.take_profit_price = None
                    self._open_side(side)
                    return
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
            self.pending_side = None
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
